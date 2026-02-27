"""
Retirement Portfolio Configuration
====================================
Watchlist split across three buckets with target allocations:
  40%  Core ETFs      — broad market / dividend index
  30%  Dividend       — high-quality income compounders
  30%  Growth         — long-duration quality growth

Horizon: 5-10 years to retirement
Risk profile: Moderate — growth with capital preservation
"""

from dataclasses import dataclass, field
from typing import List, Dict

# ── Default watchlist ────────────────────────────────────────────────────────
WATCHLIST_ETF = ["VTI", "SCHD", "DGRO", "QQQ"]          # Core ETF sleeve
WATCHLIST_DIVIDEND = ["JNJ", "KO", "PG", "ABBV", "VZ"]  # Dividend compounders
WATCHLIST_GROWTH = ["MSFT", "AAPL", "NVDA", "GOOGL", "AMZN"]  # Quality growth

DEFAULT_WATCHLIST = WATCHLIST_ETF + WATCHLIST_DIVIDEND + WATCHLIST_GROWTH

# ── Target allocations (% of portfolio) ─────────────────────────────────────
TARGET_ALLOCATIONS: Dict[str, float] = {
    # ETF sleeve — 40%
    "VTI":   0.15,   # Total US market anchor
    "SCHD":  0.10,   # Dividend-weighted US
    "DGRO":  0.08,   # Dividend growth
    "QQQ":   0.07,   # Tech/growth tilt

    # Dividend sleeve — 30%
    "JNJ":   0.07,
    "KO":    0.06,
    "PG":    0.07,
    "ABBV":  0.05,
    "VZ":    0.05,

    # Growth sleeve — 30%
    "MSFT":  0.08,
    "AAPL":  0.07,
    "NVDA":  0.05,
    "GOOGL": 0.05,
    "AMZN":  0.05,
}

# Rebalancing trigger: drift beyond this % of target → flag for rebalancing
REBALANCE_DRIFT_THRESHOLD = 0.05   # 5 percentage points

# ── Portfolio config ─────────────────────────────────────────────────────────
@dataclass
class PortfolioConfig:
    watchlist: List[str] = field(default_factory=lambda: list(DEFAULT_WATCHLIST))
    target_allocations: Dict[str, float] = field(default_factory=lambda: dict(TARGET_ALLOCATIONS))

    # Investment style
    style: str = "retirement"
    risk_profile: str = "moderate"
    horizon_years: int = 7               # Mid-point of 5-10 year range

    # Risk per buy (% of portfolio per new position)
    position_size_pct: float = 0.03      # 3% of portfolio per buy
    max_single_stock_pct: float = 0.10   # 10% max any single position
    max_sector_pct: float = 0.25         # 25% max any single sector
    min_dividend_yield: float = 0.0      # No minimum — ETFs may have low yield

    # Rebalancing
    rebalance_drift_threshold: float = REBALANCE_DRIFT_THRESHOLD
    rebalance_frequency: str = "quarterly"

    # Scan schedule
    scan_interval_hours: int = 24        # Daily scan per ticker
    rebalance_check_days: int = 7        # Weekly rebalance drift check

    # Order settings — LIMIT orders for retirement (don't chase price)
    order_type: str = "LIMIT"
    limit_offset_pct: float = 0.005     # Limit 0.5% below ask (avoid overpaying)

    # No EOD close — hold positions
    auto_close_eod: bool = False


# ── Singleton ────────────────────────────────────────────────────────────────
PORTFOLIO_CONFIG = PortfolioConfig()


def get_config() -> PortfolioConfig:
    return PORTFOLIO_CONFIG


def update_config(**kwargs) -> PortfolioConfig:
    for k, v in kwargs.items():
        if hasattr(PORTFOLIO_CONFIG, k):
            setattr(PORTFOLIO_CONFIG, k, v)
    return PORTFOLIO_CONFIG
