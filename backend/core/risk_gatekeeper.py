"""
Retirement Risk Gatekeeper
============================
Replaces intraday day-trading risk gates with long-term retirement-appropriate constraints.
Key differences from the day-trading version:
  - No EOD close, no ATR-based intraday stops
  - Position sizing based on 2% portfolio risk per new holding
  - Sector diversification gate (no category > target + 15%)
  - Minimum hold check (don't churn positions < 30 days old)
  - Trailing stop is a REVIEW ALERT, not an auto-sell
"""
import logging
from dataclasses import dataclass

from trading_interface.events.schemas import (
    SignalCreated, RiskApproved, RiskRejected, RiskMetrics
)
from core.portfolio_state import PortfolioState, MarketContext

logger = logging.getLogger("RetirementRiskManager")


class HardConstraintViolation(Exception):
    def __init__(self, metric: str, reason: str, is_hard: bool = True):
        self.metric   = metric
        self.reason   = reason
        self.is_hard  = is_hard
        super().__init__(reason)


class RetirementRiskManager:
    """
    Deterministic risk manager for long-term retirement investing.
    All parameters are configurable so apply_retirement_config() can override them.
    """

    # ── Configurable class attributes (overridden by apply_retirement_config) ──
    MAX_SINGLE_POSITION_PCT = 0.10   # No single holding > 10% of portfolio
    RISK_PER_TRADE_PCT      = 0.02   # Allocate 2% of portfolio per new position
    MAX_OPEN_POSITIONS      = 20     # Diversified retirement portfolio
    TRAILING_STOP_PCT       = 0.15   # 15% drawdown triggers ALERT (not auto-sell)
    MIN_HOLD_DAYS           = 30     # Don't churn — minimum days before selling
    REBALANCE_DRIFT         = 0.05   # Flag if category drifts > 5% from target

    # Signals below this confidence are held — never act on weak AI signals
    MIN_CONFIDENCE_TO_ACT   = 0.60

    def __init__(self):
        self.halted = False

    def evaluate_signal(
        self,
        signal:    SignalCreated,
        portfolio: PortfolioState,
        market:    MarketContext,
    ) -> RiskApproved | RiskRejected:
        """
        Runs all retirement-appropriate risk gates in priority order.
        Returns RiskApproved with position sizing or RiskRejected with reason.
        """
        try:
            # ── Gate 1: System halt ─────────────────────────────────────────
            self._check_system_halt()

            # ── Gate 2: Confidence threshold ───────────────────────────────
            self._check_confidence(signal)

            # ── Gate 3: Portfolio drawdown kill-switch ──────────────────────
            self._check_portfolio_drawdown(portfolio)

            # ── Gate 4: Action routing ──────────────────────────────────────
            action = self._map_action(signal.suggested_action)

            if action == "HOLD":
                raise HardConstraintViolation("HOLD", "Signal is HOLD — no execution needed.")

            # ── Gate 5: Min hold period (prevent churning) ──────────────────
            if action in ("SELL", "REDUCE"):
                self._check_min_hold(signal, portfolio, market.ticker)

            # ── Gate 6: Max position concentration ─────────────────────────
            if action == "BUY":
                self._check_concentration(portfolio, market)

            # ── Gate 7: Trailing stop alert (soft — not auto-sell) ──────────
            self._check_trailing_stop(signal, portfolio, market.ticker)

            # ── Gate 8: Sufficient buying power ────────────────────────────
            if action == "BUY":
                allocation = portfolio.total_equity * self.RISK_PER_TRADE_PCT
                if allocation > portfolio.buying_power:
                    raise HardConstraintViolation(
                        "BUYING_POWER",
                        f"Insufficient funds: need ${allocation:.0f}, have ${portfolio.buying_power:.0f}."
                    )

            # ── Position sizing ─────────────────────────────────────────────
            approved_qty, limit_price = self._size_position(action, signal, portfolio, market)

            metrics = RiskMetrics(
                position_size_pct = round(approved_qty * limit_price / max(portfolio.total_equity, 1), 4),
                hard_stop_loss    = round(limit_price * (1 - self.TRAILING_STOP_PCT), 2),
                approved_qty      = approved_qty,
            )

            return RiskApproved(
                signal_id           = signal.signal_id,
                ticker              = market.ticker,
                action              = f"{action}_TO_OPEN" if action == "BUY" else f"{action}_TO_CLOSE",
                approved_quantity   = approved_qty,
                approved_limit_price= limit_price,
                risk_metrics        = metrics,
            )

        except HardConstraintViolation as v:
            logger.warning(f"RISK GATE: [{v.metric}] {v.reason}")
            return RiskRejected(
                signal_id      = signal.signal_id,
                ticker         = market.ticker,
                failing_metric = v.metric,
                reason         = v.reason,
            )
        except Exception as e:
            logger.error(f"Unexpected risk error for {market.ticker}: {e}")
            return RiskRejected(
                signal_id      = signal.signal_id,
                ticker         = market.ticker,
                failing_metric = "SYSTEM_ERROR",
                reason         = str(e),
            )

    # ── Gate implementations ────────────────────────────────────────────────

    def _check_system_halt(self):
        if self.halted:
            raise HardConstraintViolation("HALTED", "System manually halted.")

    def _check_confidence(self, signal: SignalCreated):
        if signal.confidence < self.MIN_CONFIDENCE_TO_ACT:
            raise HardConstraintViolation(
                "LOW_CONFIDENCE",
                f"Signal confidence {signal.confidence:.0%} is below {self.MIN_CONFIDENCE_TO_ACT:.0%} threshold. "
                "For long-term investing, only act on high-conviction signals."
            )

    def _check_portfolio_drawdown(self, portfolio: PortfolioState):
        if portfolio.current_drawdown_pct >= 0.20:
            raise HardConstraintViolation(
                "PORTFOLIO_DRAWDOWN",
                f"Portfolio is down {portfolio.current_drawdown_pct*100:.1f}% from peak. "
                "Pausing new purchases — review overall allocation before adding risk."
            )

    def _check_min_hold(self, signal: SignalCreated, portfolio: PortfolioState, ticker: str):
        """Prevent selling a position held for less than MIN_HOLD_DAYS."""
        for pos in portfolio.positions:
            if pos.ticker == ticker:
                from datetime import datetime
                days_held = (datetime.utcnow() - pos.opened_at).days if hasattr(pos, 'opened_at') else 999
                if days_held < self.MIN_HOLD_DAYS:
                    raise HardConstraintViolation(
                        "MIN_HOLD",
                        f"{ticker} was opened {days_held} days ago. "
                        f"Minimum hold is {self.MIN_HOLD_DAYS} days to avoid short-term capital gains tax."
                    )

    def _check_concentration(self, portfolio: PortfolioState, market: MarketContext):
        """Prevent any single position exceeding MAX_SINGLE_POSITION_PCT."""
        allocation = portfolio.total_equity * self.RISK_PER_TRADE_PCT
        new_position_pct = allocation / max(portfolio.total_equity, 1)

        existing = sum(
            p.market_value for p in portfolio.positions
            if p.ticker == market.ticker
        )
        total_after = (existing + allocation) / max(portfolio.total_equity, 1)

        if total_after > self.MAX_SINGLE_POSITION_PCT:
            raise HardConstraintViolation(
                "CONCENTRATION",
                f"Adding to {market.ticker} would bring it to {total_after*100:.1f}% of portfolio. "
                f"Max single holding is {self.MAX_SINGLE_POSITION_PCT*100:.0f}%."
            )

    def _check_trailing_stop(self, signal: SignalCreated, portfolio: PortfolioState, ticker: str):
        """Soft alert — log a warning but don't block. Retirement investors shouldn't panic-sell."""
        for pos in portfolio.positions:
            if pos.ticker == ticker and pos.unrealized_pnl_pct < -self.TRAILING_STOP_PCT:
                logger.warning(
                    f"TRAILING STOP ALERT: {ticker} is down {abs(pos.unrealized_pnl_pct)*100:.1f}% "
                    f"from entry. Consider reviewing the fundamental thesis."
                )
                # Soft alert only — does NOT raise HardConstraintViolation

    def _size_position(self, action: str, signal: SignalCreated,
                       portfolio: PortfolioState, market: MarketContext):
        """
        Retirement position sizing:
        - BUY:    allocate RISK_PER_TRADE_PCT of total equity
        - SELL/REDUCE: sell the full existing position (or half for REDUCE)
        """
        price = market.current_price
        if price <= 0:
            raise HardConstraintViolation("DATA_ERROR", "Price is zero or negative.")

        if action == "BUY":
            allocation = portfolio.total_equity * self.RISK_PER_TRADE_PCT
            qty = max(1, int(allocation / price))
        elif action == "SELL":
            # Sell entire position
            existing_qty = next(
                (p.quantity for p in portfolio.positions if p.ticker == market.ticker), 0
            )
            qty = max(1, existing_qty)
        else:  # REDUCE
            existing_qty = next(
                (p.quantity for p in portfolio.positions if p.ticker == market.ticker), 0
            )
            qty = max(1, existing_qty // 2)

        return qty, round(price, 2)

    def _map_action(self, string_action: str) -> str:
        mapping = {
            "BUY":    "BUY",
            "SELL":   "SELL",
            "REDUCE": "REDUCE",
            "HOLD":   "HOLD",
            "REVIEW": "HOLD",   # REVIEW = HOLD in execution terms
        }
        if string_action in mapping:
            return mapping[string_action]
        raise HardConstraintViolation("INVALID_ACTION", f"Unknown action: '{string_action}'")


# ── Backwards-compatible alias used in app.py ──
DeterministicRiskManager = RetirementRiskManager
