"""
Retirement Portfolio Alert System
===================================
Generates alerts for significant events:
  - Price drops > 5% in a single day
  - Trailing stop breach (position down > 15% from entry)
  - Rebalance required (category drift > 5%)
  - 52-week low breach
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List

logger = logging.getLogger("AlertSystem")


@dataclass
class PortfolioAlert:
    alert_id:    str
    ticker:      str
    alert_type:  str    # PRICE_DROP | TRAILING_STOP | REBALANCE | 52WK_LOW | DIVIDEND_CUT
    severity:    str    # INFO | WARNING | CRITICAL
    message:     str
    timestamp:   datetime = field(default_factory=datetime.utcnow)
    is_read:     bool = False


# In-process store — cleared on restart (use DB for persistence in v2)
_alerts: List[PortfolioAlert] = []


def add_alert(ticker: str, alert_type: str, severity: str, message: str) -> PortfolioAlert:
    import uuid
    alert = PortfolioAlert(
        alert_id   = str(uuid.uuid4())[:8],
        ticker     = ticker,
        alert_type = alert_type,
        severity   = severity,
        message    = message,
    )
    _alerts.append(alert)
    logger.warning(f"ALERT [{severity}] {ticker}: {message}")
    # Keep last 100 alerts
    if len(_alerts) > 100:
        _alerts.pop(0)
    return alert


def check_and_generate_alerts(ticker: str, current_price: float,
                               prev_close: float, positions: list) -> List[PortfolioAlert]:
    """
    Called after each market data fetch. Generates alerts for notable events.
    """
    new_alerts = []
    cfg_trailing_stop = 0.15  # Import would cause circular — use default

    # ── Daily price drop alert ──────────────────────────────────────────
    if prev_close and prev_close > 0:
        day_change = (current_price - prev_close) / prev_close
        if day_change <= -0.05:
            a = add_alert(
                ticker     = ticker,
                alert_type = "PRICE_DROP",
                severity   = "WARNING" if day_change > -0.10 else "CRITICAL",
                message    = (
                    f"{ticker} dropped {abs(day_change)*100:.1f}% today "
                    f"(${prev_close:.2f} → ${current_price:.2f}). "
                    f"Review the fundamental thesis before acting."
                )
            )
            new_alerts.append(a)

    # ── Trailing stop breach on open positions ──────────────────────────
    for pos in positions:
        t = pos.get("ticker") if isinstance(pos, dict) else getattr(pos, "ticker", "")
        if t != ticker:
            continue
        entry = pos.get("entry") if isinstance(pos, dict) else getattr(pos, "entry_price", 0)
        if entry and entry > 0:
            loss_pct = (current_price - entry) / entry
            if loss_pct <= -cfg_trailing_stop:
                a = add_alert(
                    ticker     = ticker,
                    alert_type = "TRAILING_STOP",
                    severity   = "CRITICAL",
                    message    = (
                        f"{ticker} is down {abs(loss_pct)*100:.1f}% from your entry of ${entry:.2f}. "
                        f"Current: ${current_price:.2f}. "
                        f"Consider reviewing whether the investment thesis still holds."
                    )
                )
                new_alerts.append(a)

    return new_alerts


def get_all_alerts(unread_only: bool = False) -> List[PortfolioAlert]:
    if unread_only:
        return [a for a in _alerts if not a.is_read]
    return list(reversed(_alerts))  # Newest first


def mark_read(alert_id: str):
    for a in _alerts:
        if a.alert_id == alert_id:
            a.is_read = True
            break


def get_unread_count() -> int:
    return sum(1 for a in _alerts if not a.is_read)


# ---------------------------------------------------------------------------
# Legacy-compatible function used by /api/alerts endpoint
# ---------------------------------------------------------------------------
@dataclass
class LegacyAlert:
    ticker:     str
    level:      str   # ACTION | WARNING | INFO
    category:   str
    message:    str
    value:      float = 0.0

    def to_dict(self):
        return {
            "ticker":    self.ticker,
            "level":     self.level,
            "category":  self.category,
            "message":   self.message,
            "value":     self.value,
        }


def generate_portfolio_alerts(
    ticker: str,
    fundamentals: dict,
    current_price: float,
    week52_high,
    sma_20,
    drift_pct: float,
    gap_value: float,
    drift_threshold: float = 5.0,
) -> List[LegacyAlert]:
    """Generates structured alerts for the /api/alerts endpoint."""
    alerts = []
    raw = fundamentals.get("raw", {}) if isinstance(fundamentals, dict) else {}

    # Price vs 52-week high
    if week52_high and current_price and week52_high > 0:
        drawdown = (week52_high - current_price) / week52_high
        if drawdown >= 0.20:
            alerts.append(LegacyAlert(
                ticker   = ticker,
                level    = "ACTION",
                category = "DRAWDOWN",
                message  = f"{ticker} is {drawdown*100:.0f}% below 52-week high (${week52_high:.2f}). Potential buy opportunity.",
                value    = round(drawdown * 100, 1),
            ))

    # Rebalance drift
    if abs(drift_pct) > drift_threshold:
        level = "ACTION" if abs(drift_pct) > drift_threshold * 2 else "WARNING"
        action = "underweight — consider adding" if drift_pct < 0 else "overweight — consider trimming"
        alerts.append(LegacyAlert(
            ticker   = ticker,
            level    = level,
            category = "REBALANCE",
            message  = f"{ticker} is {action} (drift: {drift_pct:+.1f}%, gap: ${abs(gap_value):,.0f})",
            value    = round(drift_pct, 1),
        ))

    # Dividend payout ratio warning
    payout = raw.get("payoutRatio", 0) or 0
    if payout > 0.85:
        alerts.append(LegacyAlert(
            ticker   = ticker,
            level    = "WARNING",
            category = "DIVIDEND",
            message  = f"{ticker} payout ratio is {payout*100:.0f}% — dividend may be at risk if earnings decline.",
            value    = round(payout * 100, 1),
        ))

    return alerts
