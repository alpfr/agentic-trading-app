"""
Retirement Config Application
================================
Replaces day_trading.py — applies retirement risk parameters to the
module-level RISK_MANAGER singleton at startup.
"""
import logging
from core.risk_gatekeeper import RetirementRiskManager
from core.watchlist import get_config

logger = logging.getLogger("RetirementConfig")


def apply_day_trading_config(risk_manager: RetirementRiskManager) -> None:
    """
    Applies retirement-appropriate parameters to the given RiskManager instance.
    Called at startup on the module-level RISK_MANAGER singleton.
    Kept named apply_day_trading_config for import compatibility with app.py.
    """
    cfg = get_config()

    risk_manager.MAX_SINGLE_POSITION_PCT = cfg.max_single_position_pct   # 10%
    risk_manager.RISK_PER_TRADE_PCT      = cfg.risk_per_trade_pct        # 2%
    risk_manager.TRAILING_STOP_PCT       = cfg.trailing_stop_pct         # 15%
    risk_manager.MIN_HOLD_DAYS           = cfg.min_hold_days             # 30 days
    risk_manager.REBALANCE_DRIFT         = cfg.rebalance_drift_trigger   # 5%

    logger.info(
        f"Retirement config applied: "
        f"max_pos={cfg.max_single_position_pct*100:.0f}% "
        f"risk_per_trade={cfg.risk_per_trade_pct*100:.0f}% "
        f"trailing_stop={cfg.trailing_stop_pct*100:.0f}% "
        f"min_hold={cfg.min_hold_days}d"
    )


async def close_all_positions(broker_client) -> dict:
    """
    Retirement mode: no EOD auto-close. This is a manual emergency-only function.
    Returns a warning rather than closing positions automatically.
    """
    logger.warning(
        "close_all_positions called in retirement mode. "
        "This is a manual emergency action — positions are long-term holds."
    )
    return {"closed": 0, "message": "Retirement mode: positions are not auto-closed. Use manual sell signals."}
