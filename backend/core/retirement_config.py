"""
Retirement Portfolio Risk Configuration
=========================================
Replaces day_trading.py — configures the risk gatekeeper for
long-term, buy-and-hold retirement investing.
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

    # Position sizing — use actual RetirementConfig field names
    risk_manager.MAX_POSITION_PCT    = config.max_single_position_pct  # 10%
    risk_manager.MAX_OPEN_POSITIONS  = 20
    risk_manager.risk_per_trade_pct  = config.risk_per_trade_pct        # 2%

    # Retirement does not use ATR-based stops
    risk_manager.ATR_MULTIPLIER      = 0.0

    # Retirement-specific quality gates
    risk_manager.MAX_PE_RATIO        = 50.0   # Block extreme valuation
    risk_manager.MAX_PAYOUT_RATIO    = 0.85   # Flag dividend risk above 85%
    risk_manager.MIN_FCF_POSITIVE    = True

    logger.info(
        f"Retirement config applied: max_pos={config.max_single_position_pct*100:.0f}% "
        f"per_buy={config.risk_per_trade_pct*100:.0f}% "
        f"max_PE={risk_manager.MAX_PE_RATIO}"
    )
