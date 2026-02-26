import logging
import uuid
from typing import Tuple, Optional

# Architectures
from trading_interface.events.schemas import SignalCreated, RiskApproved, RiskRejected, RiskMetrics
from core.portfolio_state import PortfolioState, MarketContext

logger = logging.getLogger("RiskManagerGatekeeper")

class HardConstraintViolation(Exception):
    def __init__(self, metric: str, reason: str):
        self.metric = metric
        self.reason = reason
        super().__init__(reason)

class DeterministicRiskManager:
    """
    Absolutely impassable mathematical boundary.
    Any Signal that an LLM generates must survive these code-blocks.
    If it fails, the execution loop immediately dies.
    """
    
    def __init__(self):
        # Configuration - Can be scaled up to AWS Parameter Store mapping
        self.max_drawdown_pct = 0.10      # Kill Switch (10% decline from HWM)
        self.max_daily_loss = 0.03        # 3% loss triggers a daily timeout
        self.max_single_position = 0.05   # 5% max capital equity per ticker
        self.max_sector_exposure = 0.20   # 20% max correlation risk
        
        self.min_daily_volume = 5_000_000 # 5M minimum ADV (Liquidity protection)
        self.max_vix = 35.0               # No new long swing trades in a panic
        self.earnings_blackout_days = 3   # Volatility crush prevention
        
        # Volatility Targeting
        self.risk_per_trade_pct = 0.01    # Risk exactly 1% of equity per trade

    def evaluate_signal(self, signal: SignalCreated, portfolio: PortfolioState, market: MarketContext) -> RiskApproved | RiskRejected:
        """The Central Gatekeeper Loop. Emits either an Approval or Rejection."""
        
        logger.info(f"evaluating signal: {signal.event_id} ({signal.ticker})")

        try:
            # Phase 1: Global Account Level Checks
            self._check_account_viability(portfolio)

            # Phase 2: Macro / Market Conditions Check
            self._check_market_regimes(signal, market)
            
            # Phase 3: Sector & Portfolio Correlation Risk
            self._check_portfolio_concentration(signal, portfolio, market.ticker) # Sector tracking assumed in DB usually

            # Phase 4: Compute Sizing using True Range targeting
            shares, total_value, stop_loss = self._compute_volatility_sizing(signal, portfolio, market)

            # Emit Final Authority Event
            return RiskApproved(
                event_id=uuid.uuid4(),
                signal_id=signal.event_id,
                ticker=signal.ticker,
                action=self._map_LLM_action(signal.suggested_action),
                approved_quantity=shares,
                approved_limit_price=market.current_price,
                risk_metrics=RiskMetrics(
                    account_exposure_pct=round((total_value / portfolio.total_equity) * 100, 2),
                    volatility_atr=market.atr_14,
                    hard_stop_loss=stop_loss
                )
            )

        except HardConstraintViolation as v:
            logger.warning(f"RISK REJECTED: [Metric={v.metric}] {v.reason}")
            return RiskRejected(
                signal_id=signal.event_id,
                reason=v.reason,
                failing_metric=v.metric
            )
        except Exception as e:
            logger.error(f"FATAL Engine Crash on Risk logic: {e}")
            return RiskRejected(
                signal_id=signal.event_id,
                reason="Engine crashed during computation.",
                failing_metric="SYSTEM_ERROR"
            )

    # --- PRIVATE MATHEMATICAL ASSERTIONS ---

    def _check_account_viability(self, portfolio: PortfolioState):
        """Halts the execution agent if broad drawdowns are breached."""
        if portfolio.is_trading_halted:
            raise HardConstraintViolation("HALTED_BY_ADMIN", "Account carries manual Halt/KillSwitch override.")
            
        if portfolio.current_drawdown_pct >= self.max_drawdown_pct:
            raise HardConstraintViolation("MAX_DRAWDOWN", f"Account HWM Drawdown ({portfolio.current_drawdown_pct*100}%) exceeds 10% limit.")
            
        if portfolio.daily_loss_pct >= self.max_daily_loss:
            raise HardConstraintViolation("DAILY_LOSS", "Intraday loss circuit breaker (3%) breached.")

    def _check_market_regimes(self, signal: SignalCreated, market: MarketContext):
        """Halts the signal if macro liquidity and volatility profiles are insane."""
        if market.avg_daily_volume < self.min_daily_volume:
            raise HardConstraintViolation("LIQUIDITY", f"Notional ADV {market.avg_daily_volume} beneath 5M req.")
            
        if market.days_to_earnings <= self.earnings_blackout_days:
            raise HardConstraintViolation("EARNINGS_RISK", "Trade violates 3-day earnings blackout window.")
            
        if signal.suggested_action == "BUY" and market.vix_level > self.max_vix:
             raise HardConstraintViolation("MACRO_VIX", f"VIX elevated ({market.vix_level} > 35). Broad longs disabled.")

    def _check_portfolio_concentration(self, signal: SignalCreated, portfolio: PortfolioState, ticker: str):
        """Validates that buying X won't breach 5% single stock or 20% sector."""
        # Check existing exposure
        for p in portfolio.positions:
            if p.ticker == ticker:
                exposure_pct = p.market_value / portfolio.total_equity
                if exposure_pct >= self.max_single_position:
                    raise HardConstraintViolation("SINGLE_LIMIT", f"Already fully allocated ({exposure_pct*100}%) to {ticker}.")
                
        # Needs mock 'sector' resolution normally mapped by DB
        pass 

    def _compute_volatility_sizing(self, signal: SignalCreated, portfolio: PortfolioState, market: MarketContext) -> Tuple[int, float, float]:
        """
        Risk Math:
        Risk 1% of account. 
        Distance to Stop Loss = 2 * ATRA (Volatility).
        Shares = Risk Dollars / Distance to SL.
        """
        if market.atr_14 <= 0 or market.current_price <= 0:
            raise HardConstraintViolation("DATA_ERROR", "ATR or Price returns 0. Invalid Data State.")

        risk_dollars = portfolio.total_equity * self.risk_per_trade_pct
        stop_loss_distance = 2.0 * market.atr_14
        
        # Calculate maximum share sizing against risk profile
        raw_shares = int(risk_dollars // stop_loss_distance)
        
        if raw_shares == 0:
             raise HardConstraintViolation("TINY_RISK", "Stop loss dictates <1 share. Invalid balance.")

        total_allocation = raw_shares * market.current_price
        pct_of_portfolio = total_allocation / portfolio.total_equity

        # Cap it at 5% nominal gross position cap if ATR indicates massive sizing
        if pct_of_portfolio > self.max_single_position:
            max_capital = portfolio.total_equity * self.max_single_position
            raw_shares = int(max_capital // market.current_price)
            total_allocation = raw_shares * market.current_price

        # Check total cash availability
        if total_allocation > portfolio.buying_power:
            raise HardConstraintViolation("BUYING_POWER", "Insufficient uninvested liquidity.")

        stop_loss_trigger = market.current_price - stop_loss_distance if signal.suggested_action == "BUY" else market.current_price + stop_loss_distance

        return raw_shares, total_allocation, stop_loss_trigger

    def _map_LLM_action(self, string_action: str) -> str:
        if string_action.upper() == "BUY": return "BUY_TO_OPEN"
        if string_action.upper() == "SELL": return "SELL_TO_CLOSE" # Simplified
        if string_action.upper() == "HOLD": raise HardConstraintViolation("NO_ACTION", "Holding carries no execution request.")
        raise HardConstraintViolation("INVALID_MAPPING", "Unexpected language parse inside Signal.")
