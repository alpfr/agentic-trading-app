"""
Retirement Portfolio Risk Gatekeeper
======================================
Deterministic risk evaluation for long-term, buy-and-hold investing.
All gates are pure math — the LLM cannot bypass any of them.

Gate sequence for BUY signals:
  1.  Account viability     — drawdown limit, halt flag
  2.  Valuation quality     — P/E cap, blocks extreme overvaluation
  3.  Dividend safety       — payout ratio cap (dividend stocks)
  4.  Portfolio concentration — single stock cap, sector cap
  5.  Buying power          — available cash check
  6.  Position sizing       — 3% of portfolio per buy

Gate sequence for SELL signals:
  1.  Position exists       — verify long position in DB
  2.  Account viability     — always allow sells
"""

import logging
from dataclasses import dataclass
from typing import Optional

from core.portfolio_state import PortfolioState, MarketContext
from trading_interface.events.schemas import (
    SignalCreated, RiskApproved, RiskRejected, RiskMetrics
)

logger = logging.getLogger("RetirementRiskManager")


class HardConstraintViolation(Exception):
    def __init__(self, metric: str, reason: str, detail: str = ""):
        self.metric = metric
        self.reason = reason
        self.detail = detail
        super().__init__(reason)


@dataclass
class RetirementRiskConfig:
    # Account-level protection
    max_drawdown_pct: float   = 0.20     # 20% drawdown halts new buys (long-term tolerance)
    max_daily_loss:   float   = 0.05     # 5% daily loss — less sensitive for retirement

    # Valuation gates
    MAX_PE_RATIO:     float   = 50.0     # Block extreme overvaluation
    MAX_PAYOUT_RATIO: float   = 0.85     # Flag dividend risk
    MIN_FCF_POSITIVE: bool    = False    # Soft check — just warns, doesn't block ETFs

    # Concentration limits
    max_single_stock_pct: float = 0.10   # 10% max any single holding
    max_sector_exposure:  float = 0.25   # 25% max any sector
    MAX_OPEN_POSITIONS:   int   = 25     # Room for full 14-stock retirement portfolio + cash

    # Position sizing
    MAX_POSITION_PCT:    float  = 0.10   # Alias for max_single_stock_pct
    risk_per_trade_pct:  float  = 0.03   # Buy 3% of portfolio per new position
    RISK_PER_TRADE:      float  = 0.03

    # Not used for retirement (no ATR-based intraday stops)
    ATR_MULTIPLIER: float = 0.0


class DeterministicRiskManager:
    """
    Retirement portfolio risk gatekeeper.
    Evaluates every LLM signal against hard mathematical constraints.
    """

    def __init__(self):
        cfg = RetirementRiskConfig()
        # Copy all config fields as instance attributes
        # (so apply_retirement_config() can patch them)
        for field in cfg.__dataclass_fields__:
            setattr(self, field, getattr(cfg, field))

    def evaluate_signal(
        self,
        signal: SignalCreated,
        portfolio: PortfolioState,
        market: MarketContext,
        fundamentals: Optional[dict] = None,
    ) -> RiskApproved | RiskRejected:
        """
        Main evaluation entry point.
        Returns RiskApproved (with sizing) or RiskRejected (with reason).
        """
        try:
            action = self._map_action(signal.suggested_action)

            if action == "BUY_TO_OPEN":
                self._check_account_viability(portfolio)
                self._check_valuation_gates(market, fundamentals)
                self._check_portfolio_concentration(signal, portfolio, market.ticker)
                shares, price, stop = self._size_retirement_position(market, portfolio, fundamentals)

            elif action == "SELL_TO_CLOSE":
                self._check_position_exists(signal.ticker, portfolio)
                shares = self._get_position_shares(signal.ticker, portfolio)
                price  = market.current_price
                stop   = None

            else:
                raise HardConstraintViolation("NO_ACTION", "HOLD signals are not executed.")

            metrics = RiskMetrics(
                approved_quantity=shares,
                hard_stop_loss=stop or 0.0,
                position_size_pct=round((shares * price) / max(portfolio.total_equity, 1) * 100, 2),
            )

            return RiskApproved(
                ticker=market.ticker,
                action=action,
                approved_quantity=shares,
                approved_limit_price=price,
                signal_id=signal.signal_id,
                risk_metrics=metrics,
            )

        except HardConstraintViolation as v:
            logger.warning(f"RISK REJECTED [{market.ticker}] {v.metric}: {v.reason}")
            return RiskRejected(
                ticker=market.ticker,
                failing_metric=v.metric,
                reason=v.reason,
                signal_id=signal.signal_id,
            )
        except Exception as e:
            logger.error(f"Risk evaluation error for {market.ticker}: {e}")
            return RiskRejected(
                ticker=market.ticker,
                failing_metric="INTERNAL_ERROR",
                reason=str(e),
                signal_id=signal.signal_id,
            )

    # ── Gate implementations ──────────────────────────────────────────────────

    def _check_account_viability(self, portfolio: PortfolioState):
        if getattr(portfolio, "halt_flag", False):
            raise HardConstraintViolation("HALTED", "Manual halt active.")
        if portfolio.current_drawdown_pct >= self.max_drawdown_pct:
            raise HardConstraintViolation(
                "DRAWDOWN_HALT",
                f"Portfolio down {portfolio.current_drawdown_pct*100:.1f}% from high-water mark "
                f"(limit: {self.max_drawdown_pct*100:.0f}%). Pausing new buys."
            )
        if portfolio.daily_loss_pct >= self.max_daily_loss:
            raise HardConstraintViolation(
                "DAILY_LOSS",
                f"Daily loss {portfolio.daily_loss_pct*100:.1f}% exceeds "
                f"{self.max_daily_loss*100:.0f}% limit."
            )

    def _check_valuation_gates(self, market: MarketContext, fundamentals: Optional[dict]):
        """Blocks egregious overvaluation. Soft on ETFs (no P/E available)."""
        if not fundamentals:
            return   # No fundamentals → allow but log warning

        raw = fundamentals.get("raw", {})
        pe  = raw.get("pe_trailing") or raw.get("pe_forward")
        payout_ratio = raw.get("payout_ratio") or 0.0
        sector = raw.get("sector", "")

        # ETFs typically have no P/E — skip
        etf_sectors = {"", None, "Unknown"}
        if sector in etf_sectors:
            return

        # P/E gate — higher threshold for tech growth names
        tech_sectors = {"Technology", "Communication Services"}
        pe_cap = self.MAX_PE_RATIO * 1.2 if sector in tech_sectors else self.MAX_PE_RATIO

        if pe and pe > pe_cap:
            raise HardConstraintViolation(
                "VALUATION_EXTREME",
                f"{market.ticker} P/E {pe:.0f}× exceeds retirement cap of {pe_cap:.0f}×. "
                f"Overpaying destroys long-term compounding."
            )

        # Dividend payout ratio gate
        if payout_ratio > self.MAX_PAYOUT_RATIO:
            raise HardConstraintViolation(
                "DIVIDEND_RISK",
                f"{market.ticker} payout ratio {payout_ratio*100:.0f}% > "
                f"{self.MAX_PAYOUT_RATIO*100:.0f}%. Dividend sustainability risk — "
                f"review before adding."
            )

    def _check_portfolio_concentration(
        self, signal: SignalCreated, portfolio: PortfolioState, ticker: str
    ):
        """Single-stock and sector concentration limits."""
        total_equity = portfolio.total_equity or 1.0

        for pos in portfolio.positions:
            if pos.ticker == ticker:
                current_exposure_pct = pos.market_value / total_equity
                if current_exposure_pct >= self.MAX_POSITION_PCT:
                    raise HardConstraintViolation(
                        "POSITION_CONCENTRATION",
                        f"{ticker} already at {current_exposure_pct*100:.1f}% of portfolio "
                        f"(max: {self.MAX_POSITION_PCT*100:.0f}%). "
                        f"Run rebalancing instead of adding more."
                    )

        # Sector check
        for pos in portfolio.positions:
            if getattr(pos, "sector", "UNKNOWN") == getattr(
                portfolio, "ticker_sector", {}
            ).get(ticker, "UNKNOWN"):
                sector_total = sum(
                    p.market_value for p in portfolio.positions
                    if getattr(p, "sector", "") == pos.sector
                )
                if sector_total / total_equity >= self.max_sector_exposure:
                    raise HardConstraintViolation(
                        "SECTOR_CONCENTRATION",
                        f"Adding {ticker} would exceed {self.max_sector_exposure*100:.0f}% "
                        f"sector concentration limit."
                    )

    def _size_retirement_position(
        self, market: MarketContext, portfolio: PortfolioState,
        fundamentals: Optional[dict]
    ) -> tuple:
        """
        Size a retirement buy:
          - Buy 3% of total equity per new position
          - Cap at MAX_POSITION_PCT (10%)
          - Use LIMIT price 0.5% below current to avoid chasing
          - No stop-loss (long-term hold; rebalancing handles exits)
        """
        price = market.current_price
        if price <= 0:
            raise HardConstraintViolation("DATA_ERROR", "Price is zero/negative.")

        equity = portfolio.total_equity
        alloc  = equity * self.risk_per_trade_pct    # 3% of portfolio

        # Cap at max position size
        max_alloc = equity * self.MAX_POSITION_PCT
        alloc     = min(alloc, max_alloc)

        shares = max(1, int(alloc / price))

        # Limit price: 0.5% below current (retirement discipline — don't overpay)
        limit_price = round(price * 0.995, 2)

        if shares * limit_price > portfolio.buying_power:
            raise HardConstraintViolation(
                "BUYING_POWER",
                f"Need ${shares * limit_price:,.0f} but only "
                f"${portfolio.buying_power:,.0f} available."
            )

        return shares, limit_price, None   # No stop-loss for retirement holds

    def _check_position_exists(self, ticker: str, portfolio: PortfolioState):
        if not any(p.ticker == ticker for p in portfolio.positions):
            raise HardConstraintViolation(
                "NO_POSITION",
                f"No open long position in {ticker} to sell."
            )

    def _get_position_shares(self, ticker: str, portfolio: PortfolioState) -> int:
        for p in portfolio.positions:
            if p.ticker == ticker:
                return p.quantity
        return 0

    def _map_action(self, string_action: str) -> str:
        action = string_action.upper().strip()
        if action == "BUY":  return "BUY_TO_OPEN"
        if action == "SELL": return "SELL_TO_CLOSE"
        if action == "HOLD": raise HardConstraintViolation("NO_ACTION", "HOLD — no trade.")
        raise HardConstraintViolation("INVALID_ACTION", f"Unknown action: '{action}'")
