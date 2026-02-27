"""
Retirement Portfolio Configuration
====================================
Replaces day-trading watchlist with a long-term retirement-focused portfolio.
Horizon: 5-10 years. Style: buy-and-hold with periodic rebalancing.
"""
from dataclasses import dataclass, field
from typing import List, Dict

@dataclass
class RetirementConfig:
    # ── Watchlist ──────────────────────────────────────────────────────────
    watchlist: List[str] = field(default_factory=lambda: [
        # ETFs (target 40% of portfolio)
        "VTI",   # Vanguard Total Market — broad US diversification
        "SCHD",  # Schwab Dividend ETF — dividend growth + quality
        "QQQ",   # Invesco Nasdaq-100 — tech/growth exposure

        # Dividend stocks (target 25% of portfolio)
        "JNJ",   # Johnson & Johnson — healthcare, 60+ yr dividend grower
        "PG",    # Procter & Gamble — consumer staples, recession-resilient

        # Growth stocks (target 35% of portfolio)
        "MSFT",  # Microsoft — cloud dominance, diversified revenue
        "NVDA",  # Nvidia — AI infrastructure, long-term secular trend
        "AAPL",  # Apple — ecosystem moat, growing services revenue
    ])

    # ── Investment style ───────────────────────────────────────────────────
    style: str = "retirement"
    horizon_years: int = 7          # Mid-point of 5-10 yr range

    # ── Target allocations by category (must sum to 1.0) ──────────────────
    target_allocations: Dict[str, float] = field(default_factory=lambda: {
        "ETF":      0.40,   # Core diversification
        "dividend": 0.25,   # Income + stability
        "growth":   0.35,   # Long-term appreciation
    })

    # Ticker → category mapping
    ticker_categories: Dict[str, str] = field(default_factory=lambda: {
        "VTI": "ETF", "SCHD": "ETF", "QQQ": "ETF",
        "JNJ": "dividend", "PG": "dividend",
        "MSFT": "growth", "NVDA": "growth", "AAPL": "growth",
    })

    # ── Risk parameters ────────────────────────────────────────────────────
    max_single_position_pct: float = 0.10   # No single stock > 10% of portfolio
    trailing_stop_pct:       float = 0.15   # 15% drawdown triggers review alert
    rebalance_drift_trigger: float = 0.05   # Rebalance when allocation drifts > 5%
    min_hold_days:           int   = 30     # Don't churn — minimum 30-day hold
    risk_per_trade_pct:      float = 0.02   # 2% of portfolio per new position

    # ── Scan schedule ──────────────────────────────────────────────────────
    scan_interval_hours: int = 24           # Daily scan (not intraday)
    rebalance_check_day: str = "Monday"     # Weekly rebalance review

    # ── Paper trading ──────────────────────────────────────────────────────
    paper_only: bool = True     # Always True until user explicitly enables live


# Module-level singleton
_config = RetirementConfig()


def get_config() -> RetirementConfig:
    return _config


def update_watchlist(tickers: List[str]) -> RetirementConfig:
    _config.watchlist = [t.upper() for t in tickers]
    return _config


def get_ticker_category(ticker: str) -> str:
    return _config.ticker_categories.get(ticker.upper(), "growth")


# Convenience alias used by app.py imports
TARGET_ALLOCATIONS = RetirementConfig().target_allocations
