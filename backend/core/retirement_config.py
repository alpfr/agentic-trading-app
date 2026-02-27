"""
Retirement Portfolio Risk Configuration
=========================================
Replaces day_trading.py — configures the risk gatekeeper for
long-term, buy-and-hold retirement investing.

Key differences from day trading:
  - No EOD auto-close (hold positions)
  - LIMIT orders instead of MARKET
  - P/E and dividend quality gates instead of ATR/liquidity gates
  - Larger position sizes (3% per buy, up to 10% max)
  - Quarterly rebalancing instead of 20-min scans
"""

import logging
from core.watchlist import get_config

logger = logging.getLogger("RetirementConfig")


def apply_retirement_config(risk_manager) -> None:
    """
    Patches DeterministicRiskManager with retirement portfolio parameters.
    Called once at startup against the module-level RISK_MANAGER singleton.
    """
    config = get_config()

    # Position sizing
    risk_manager.MAX_POSITION_PCT    = config.max_single_stock_pct   # 10%
    risk_manager.MAX_OPEN_POSITIONS  = 20                            # Full 14-stock portfolio + room
    risk_manager.risk_per_trade_pct  = config.position_size_pct      # 3% per buy

    # Retirement does not use ATR-based stops
    # Stops are handled by rebalancing drift thresholds, not intraday volatility
    risk_manager.ATR_MULTIPLIER      = 0.0   # Disabled — retirement uses fundamental exits

    # Sector concentration limit
    risk_manager.max_sector_exposure = config.max_sector_pct         # 25%

    # Retirement-specific quality gates (checked in evaluate_signal)
    risk_manager.MAX_PE_RATIO        = 50.0   # Block extreme valuation
    risk_manager.MAX_PAYOUT_RATIO    = 0.85   # Flag dividend risk above 85%
    risk_manager.MIN_FCF_POSITIVE    = True   # Prefer positive free cash flow

    logger.info(
        f"Retirement config applied: max_pos={config.max_single_stock_pct*100:.0f}% "
        f"per_buy={config.position_size_pct*100:.0f}% "
        f"max_sector={config.max_sector_pct*100:.0f}% "
        f"max_PE={risk_manager.MAX_PE_RATIO}"
    )
