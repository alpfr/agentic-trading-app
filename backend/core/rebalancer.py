"""
Portfolio Rebalancer
======================
Compares current portfolio allocations against target allocations.
Detects drift and produces suggested trades to restore balance.

Used for:
  1. Weekly drift check (scheduler)
  2. /api/rebalance endpoint (on-demand)
  3. Rebalancing tab in frontend
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger("Rebalancer")


@dataclass
class AllocationStatus:
    ticker: str
    target_pct: float           # Target % of portfolio
    current_pct: float          # Actual % of portfolio right now
    drift_pct: float            # current - target (positive = overweight)
    current_value: float        # Dollar value currently held
    target_value: float         # Dollar value at target allocation
    gap_value: float            # Dollar gap (positive = need to buy more)
    action: str                 # "BUY", "SELL", "HOLD" — based on drift
    shares_to_trade: int        # Estimated shares to close the gap
    current_price: float        # Last known price


@dataclass
class RebalanceReport:
    total_portfolio_value: float
    buys: List[AllocationStatus] = field(default_factory=list)
    sells: List[AllocationStatus] = field(default_factory=list)
    holds: List[AllocationStatus] = field(default_factory=list)
    untracked: List[str] = field(default_factory=list)  # Positions outside target watchlist
    drift_threshold: float = 0.05
    needs_rebalancing: bool = False
    summary: str = ""


def compute_rebalance(
    current_positions: List[dict],    # [{ticker, shares, current_price, market_value}]
    target_allocations: Dict[str, float],   # {ticker: target_pct}
    total_portfolio_value: float,
    drift_threshold: float = 0.05,
    prices: Optional[Dict[str, float]] = None,   # override prices if available
) -> RebalanceReport:
    """
    Compare current holdings against target allocations.
    Returns a RebalanceReport with actionable trade suggestions.
    """
    if total_portfolio_value <= 0:
        return RebalanceReport(
            total_portfolio_value=0,
            summary="Portfolio value unavailable — cannot compute rebalancing.",
        )

    report = RebalanceReport(
        total_portfolio_value=total_portfolio_value,
        drift_threshold=drift_threshold,
    )

    # Build current state map
    current_map: Dict[str, dict] = {}
    for pos in current_positions:
        t = pos.get("ticker", "")
        if t:
            current_map[t] = pos

    all_tickers = set(target_allocations.keys()) | set(current_map.keys())

    for ticker in sorted(all_tickers):
        target_pct = target_allocations.get(ticker, 0.0)
        pos        = current_map.get(ticker)

        if pos:
            current_value = pos.get("market_value") or (
                pos.get("shares", 0) * pos.get("current_price", 0)
            )
            price = pos.get("current_price", 0) or 1.0
        else:
            current_value = 0.0
            price = (prices or {}).get(ticker, 0) or 1.0

        current_pct = current_value / total_portfolio_value
        target_value = target_pct * total_portfolio_value
        gap_value    = target_value - current_value
        drift_pct    = current_pct - target_pct

        # Determine action
        if target_pct == 0.0 and current_value > 0:
            action = "SELL"   # Position exists but no target allocation
            shares_to_trade = int(current_value / price) if price else 0
        elif abs(drift_pct) >= drift_threshold:
            action = "BUY" if gap_value > 0 else "SELL"
            shares_to_trade = max(1, int(abs(gap_value) / price)) if price else 0
        else:
            action = "HOLD"
            shares_to_trade = 0

        status = AllocationStatus(
            ticker=ticker,
            target_pct=round(target_pct * 100, 2),
            current_pct=round(current_pct * 100, 2),
            drift_pct=round(drift_pct * 100, 2),
            current_value=round(current_value, 2),
            target_value=round(target_value, 2),
            gap_value=round(gap_value, 2),
            action=action,
            shares_to_trade=shares_to_trade,
            current_price=round(price, 2),
        )

        if action == "BUY":
            report.buys.append(status)
        elif action == "SELL":
            report.sells.append(status)
        else:
            report.holds.append(status)

    # Sort by urgency (largest drift first)
    report.buys.sort(key=lambda x: x.gap_value, reverse=True)
    report.sells.sort(key=lambda x: abs(x.gap_value), reverse=True)

    report.needs_rebalancing = bool(report.buys or report.sells)

    total_to_buy  = sum(b.gap_value for b in report.buys)
    total_to_sell = sum(abs(s.gap_value) for s in report.sells)

    if report.needs_rebalancing:
        report.summary = (
            f"{len(report.buys)} positions to increase (${total_to_buy:,.0f}), "
            f"{len(report.sells)} to reduce (${total_to_sell:,.0f}). "
            f"Drift threshold: {drift_threshold*100:.0f}%."
        )
    else:
        report.summary = f"Portfolio is within {drift_threshold*100:.0f}% of target allocations."

    return report


def rebalance_report_to_dict(report: RebalanceReport) -> dict:
    """Serialise to JSON-safe dict for API responses."""
    def status_to_dict(s: AllocationStatus) -> dict:
        return {
            "ticker":          s.ticker,
            "target_pct":      s.target_pct,
            "current_pct":     s.current_pct,
            "drift_pct":       s.drift_pct,
            "current_value":   s.current_value,
            "target_value":    s.target_value,
            "gap_value":       s.gap_value,
            "action":          s.action,
            "shares_to_trade": s.shares_to_trade,
            "current_price":   s.current_price,
        }
    return {
        "total_portfolio_value": report.total_portfolio_value,
        "needs_rebalancing":     report.needs_rebalancing,
        "drift_threshold_pct":   report.drift_threshold * 100,
        "summary":               report.summary,
        "buys":  [status_to_dict(s) for s in report.buys],
        "sells": [status_to_dict(s) for s in report.sells],
        "holds": [status_to_dict(s) for s in report.holds],
    }
