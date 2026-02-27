"""
Portfolio Rebalance Engine
===========================
Compares current portfolio allocation against target allocations.
Generates rebalance recommendations when category drift exceeds threshold.
"""
import logging
from dataclasses import dataclass
from typing import List, Dict

from core.watchlist import get_config, get_ticker_category

logger = logging.getLogger("RebalanceEngine")


@dataclass
class RebalanceRecommendation:
    category:         str
    current_pct:      float
    target_pct:       float
    drift_pct:        float
    action:           str     # "BUY_MORE", "TRIM", "ON_TARGET"
    tickers_affected: List[str]
    rationale:        str


@dataclass
class RebalanceReport:
    total_equity:      float
    recommendations:   List[RebalanceRecommendation]
    is_balanced:       bool
    summary:           str


def compute_rebalance_report(positions: list, total_equity: float) -> RebalanceReport:
    """
    Given current open positions and total equity, compute how far each
    category has drifted from its target and what action to take.
    """
    cfg = get_config()

    # ── Current allocation by category ─────────────────────────────────
    category_value: Dict[str, float] = {"ETF": 0.0, "dividend": 0.0, "growth": 0.0}
    category_tickers: Dict[str, List[str]] = {"ETF": [], "dividend": [], "growth": []}

    for pos in positions:
        ticker   = pos.get("ticker", "") if isinstance(pos, dict) else pos.ticker
        value    = pos.get("market_value", 0) if isinstance(pos, dict) else (
            getattr(pos, "market_value", 0) or
            (pos.current_price * pos.shares if hasattr(pos, 'current_price') else 0)
        )
        category = get_ticker_category(ticker)
        if category in category_value:
            category_value[category]   += value
            category_tickers[category].append(ticker)

    invested_total = sum(category_value.values())
    cash_pct = 1.0 - (invested_total / max(total_equity, 1))

    # ── Compute drift and recommendations ──────────────────────────────
    recommendations = []
    all_on_target   = True

    for category, target in cfg.target_allocations.items():
        current = category_value[category] / max(total_equity, 1)
        drift   = current - target

        if abs(drift) > cfg.rebalance_drift_trigger:
            all_on_target = False
            if drift < 0:
                action    = "BUY_MORE"
                rationale = (
                    f"{category.upper()} is underweight by {abs(drift)*100:.1f}%. "
                    f"Target: {target*100:.0f}%, Current: {current*100:.1f}%. "
                    f"Consider adding to {', '.join(category_tickers[category]) or 'new positions in this category'}."
                )
            else:
                action    = "TRIM"
                rationale = (
                    f"{category.upper()} is overweight by {drift*100:.1f}%. "
                    f"Target: {target*100:.0f}%, Current: {current*100:.1f}%. "
                    f"Consider trimming {', '.join(category_tickers[category])}."
                )
        else:
            action    = "ON_TARGET"
            rationale = f"{category.upper()} is within target range ({current*100:.1f}% vs {target*100:.0f}% target)."

        recommendations.append(RebalanceRecommendation(
            category         = category,
            current_pct      = round(current, 4),
            target_pct       = target,
            drift_pct        = round(drift, 4),
            action           = action,
            tickers_affected = category_tickers[category],
            rationale        = rationale,
        ))

    # ── Summary ────────────────────────────────────────────────────────
    if all_on_target:
        summary = "Portfolio is well-balanced. No rebalance action needed this week."
    else:
        needs_action = [r for r in recommendations if r.action != "ON_TARGET"]
        summary = (
            f"{len(needs_action)} category/categories need rebalancing. "
            f"Cash position: {cash_pct*100:.1f}% of portfolio."
        )

    return RebalanceReport(
        total_equity    = round(total_equity, 2),
        recommendations = recommendations,
        is_balanced     = all_on_target,
        summary         = summary,
    )
