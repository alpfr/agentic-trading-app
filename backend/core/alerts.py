"""
Portfolio Alerts
==================
Generates actionable alerts for retirement portfolio events:
  - Significant price drops (entry opportunity on quality names)
  - Dividend cuts or suspensions
  - Rebalancing triggers (drift beyond threshold)
  - Earnings upcoming (review before adding)
  - Valuation extremes (stretched P/E — consider trimming)

Alerts are stored in DB and surfaced via SSE stream + frontend Alerts tab.
"""

import logging
from datetime import datetime
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger("AlertEngine")


@dataclass
class Alert:
    ticker: str
    level: str              # "INFO", "WARNING", "ACTION"
    category: str           # "PRICE_DROP", "DIVIDEND", "REBALANCE", "VALUATION", "EARNINGS"
    title: str
    message: str
    suggested_action: str   # "BUY_OPPORTUNITY", "REVIEW", "REBALANCE", "TRIM", "HOLD"
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat()

    def to_dict(self) -> dict:
        return {
            "ticker":           self.ticker,
            "level":            self.level,
            "category":         self.category,
            "title":            self.title,
            "message":          self.message,
            "suggested_action": self.suggested_action,
            "timestamp":        self.timestamp,
        }


def check_price_alerts(
    ticker: str,
    current_price: float,
    week52_high: Optional[float],
    sma_20: Optional[float],
    sma_200: Optional[float] = None,
) -> List[Alert]:
    alerts = []

    if week52_high and week52_high > 0:
        drawdown = (current_price - week52_high) / week52_high
        if drawdown <= -0.20:
            alerts.append(Alert(
                ticker=ticker,
                level="ACTION",
                category="PRICE_DROP",
                title=f"{ticker} down {abs(drawdown)*100:.0f}% from 52-week high",
                message=f"Price ${current_price:.2f} is {abs(drawdown)*100:.0f}% below "
                        f"the 52-week high of ${week52_high:.2f}. For quality holdings, "
                        f"this may represent a long-term accumulation opportunity.",
                suggested_action="BUY_OPPORTUNITY",
            ))
        elif drawdown <= -0.10:
            alerts.append(Alert(
                ticker=ticker,
                level="WARNING",
                category="PRICE_DROP",
                title=f"{ticker} down {abs(drawdown)*100:.0f}% from 52-week high",
                message=f"Price ${current_price:.2f} is {abs(drawdown)*100:.0f}% off its "
                        f"52-week high of ${week52_high:.2f}. Monitor for continued weakness "
                        f"before adding.",
                suggested_action="REVIEW",
            ))

    return alerts


def check_dividend_alerts(
    ticker: str,
    div_yield: Optional[float],
    payout_ratio: Optional[float],
    div_5yr_avg: Optional[float],
) -> List[Alert]:
    alerts = []

    if payout_ratio and payout_ratio > 0.85:
        alerts.append(Alert(
            ticker=ticker,
            level="WARNING",
            category="DIVIDEND",
            title=f"{ticker} payout ratio {payout_ratio*100:.0f}% — dividend at risk",
            message=f"A payout ratio above 85% leaves little buffer for dividend maintenance "
                    f"during earnings pressure. Review free cash flow coverage.",
            suggested_action="REVIEW",
        ))

    if div_yield and div_5yr_avg and div_5yr_avg > 0:
        premium = (div_yield - div_5yr_avg) / div_5yr_avg
        if premium >= 0.25:
            alerts.append(Alert(
                ticker=ticker,
                level="ACTION",
                category="DIVIDEND",
                title=f"{ticker} dividend yield {div_yield*100:.1f}% — above 5yr average",
                message=f"Current yield {div_yield*100:.1f}% is {premium*100:.0f}% above the "
                        f"5-year average of {div_5yr_avg:.1f}%. This may signal undervaluation "
                        f"or elevated dividend risk — review fundamentals.",
                suggested_action="BUY_OPPORTUNITY",
            ))

    return alerts


def check_valuation_alerts(
    ticker: str,
    pe_trailing: Optional[float],
    pe_forward: Optional[float],
    sector: str = "Unknown",
) -> List[Alert]:
    alerts = []

    # Sector-adjusted PE thresholds
    tech_sectors = {"Technology", "Communication Services"}
    pe_limit = 40.0 if sector in tech_sectors else 28.0

    if pe_trailing and pe_trailing > pe_limit * 1.5:
        alerts.append(Alert(
            ticker=ticker,
            level="WARNING",
            category="VALUATION",
            title=f"{ticker} P/E {pe_trailing:.0f}× — stretched valuation",
            message=f"Trailing P/E of {pe_trailing:.0f}× is significantly above the "
                    f"{sector} sector threshold of ~{pe_limit:.0f}×. "
                    f"For retirement portfolios, overpaying compresses long-term returns.",
            suggested_action="TRIM" if pe_trailing > pe_limit * 2 else "REVIEW",
        ))

    return alerts


def check_rebalance_alert(
    ticker: str,
    drift_pct: float,
    gap_value: float,
    threshold: float = 5.0,
) -> Optional[Alert]:
    if abs(drift_pct) < threshold:
        return None

    direction = "overweight" if drift_pct > 0 else "underweight"
    action    = "TRIM" if drift_pct > 0 else "BUY_OPPORTUNITY"
    return Alert(
        ticker=ticker,
        level="ACTION",
        category="REBALANCE",
        title=f"{ticker} {direction} by {abs(drift_pct):.1f}%",
        message=f"{ticker} is {abs(drift_pct):.1f} percentage points {direction} of its "
                f"target allocation. ${abs(gap_value):,.0f} {'to add' if drift_pct < 0 else 'to trim'} "
                f"to restore balance.",
        suggested_action=action,
    )


def generate_portfolio_alerts(
    ticker: str,
    fundamentals: dict,
    current_price: float,
    week52_high: Optional[float],
    sma_20: Optional[float],
    drift_pct: float = 0.0,
    gap_value: float = 0.0,
    drift_threshold: float = 5.0,
) -> List[Alert]:
    """Convenience: run all checks and return combined alert list."""
    raw = fundamentals.get("raw", {})
    alerts = []
    alerts += check_price_alerts(ticker, current_price, week52_high, sma_20)
    alerts += check_dividend_alerts(
        ticker,
        raw.get("div_yield"),
        raw.get("payout_ratio"),
        raw.get("div_5yr_avg"),
    )
    alerts += check_valuation_alerts(
        ticker,
        raw.get("pe_trailing"),
        raw.get("pe_forward"),
        raw.get("sector", "Unknown"),
    )
    rebal = check_rebalance_alert(ticker, drift_pct, gap_value, drift_threshold)
    if rebal:
        alerts.append(rebal)
    return alerts
