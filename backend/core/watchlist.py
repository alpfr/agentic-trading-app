"""
Watchlist & Trading Config
==========================
Stores user's watchlist and per-session trading configuration.
Config is persisted to DB so it survives pod restarts.
"""

from dataclasses import dataclass, field
from typing import List

# ── Default watchlist ─────────────────────────────────────────────────────────
DEFAULT_WATCHLIST = ["AAOI", "BWIN", "DELL", "FIGS", "SSL"]

# ── Trading style config ──────────────────────────────────────────────────────
@dataclass
class TradingConfig:
    # Watchlist
    watchlist: List[str] = field(default_factory=lambda: list(DEFAULT_WATCHLIST))

    # Style
    style: str = "day_trading"          # day_trading | swing | position | monitor_only

    # Risk profile
    risk_profile: str = "conservative"  # conservative | balanced | aggressive

    # Risk per trade as fraction of equity
    risk_per_trade: float = 0.01        # 1% — conservative

    # ATR multiplier for stop distance (day trading: tighter = 1.0x)
    atr_multiplier: float = 1.0         # vs default 2.0 for swing

    # Max position size as fraction of equity
    max_position_pct: float = 0.03      # 3% — tighter than default 5%

    # Max number of concurrent open positions
    max_open_positions: int = 3

    # Agent scan interval during market hours (minutes)
    scan_interval_minutes: int = 20

    # End-of-day auto-close time (ET) — close all positions before this
    eod_close_time_et: str = "15:45"    # 15 min before close

    # Only trade during regular market hours
    regular_hours_only: bool = True

# ── Singleton config instance (in-memory, updated via API) ───────────────────
TRADING_CONFIG = TradingConfig()


def update_config(**kwargs) -> TradingConfig:
    """Update trading config fields at runtime."""
    for k, v in kwargs.items():
        if hasattr(TRADING_CONFIG, k):
            setattr(TRADING_CONFIG, k, v)
    return TRADING_CONFIG


def get_config() -> TradingConfig:
    return TRADING_CONFIG
