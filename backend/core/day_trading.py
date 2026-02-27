"""
Day Trading Risk Overrides
==========================
Patches the DeterministicRiskManager for day trading mode:
  - Tighter ATR stop multiplier (1× vs default 2×)
  - Smaller max position size (3% vs default 5%)
  - EOD close-all logic via broker client
"""

import logging
from typing import List
from core.database import SessionLocal, StoredPosition
from core.watchlist import get_config

logger = logging.getLogger("DayTrading")


async def close_all_positions(broker_client) -> List[str]:
    """
    EOD sweep: close every open position for day trading.
    Called by the scheduler at 15:45 ET.
    Returns list of tickers closed.
    """
    import datetime as dt
    closed = []
    db = SessionLocal()
    try:
        open_positions = (
            db.query(StoredPosition)
            .filter(StoredPosition.is_open == True)
            .all()
        )

        if not open_positions:
            logger.info("EOD sweep: no open positions to close")
            return []

        for pos in open_positions:
            try:
                # Place market sell via broker if authenticated
                if broker_client and getattr(broker_client, '_client', None):
                    await broker_client._client.submit_order(
                        symbol          = pos.ticker,
                        qty             = pos.shares,
                        side            = "sell",
                        type            = "market",
                        time_in_force   = "day",
                        client_order_id = f"eod-{pos.id}",
                    )

                pos.is_open    = False
                pos.exit_price = pos.current_price
                pos.exit_time  = dt.datetime.utcnow().isoformat()
                db.commit()
                closed.append(pos.ticker)
                logger.info(f"EOD closed: {pos.ticker} × {pos.shares} shares")

            except Exception as e:
                logger.error(f"EOD close failed for {pos.ticker}: {e}")
                db.rollback()

        return closed

    finally:
        db.close()


def apply_day_trading_config(risk_manager) -> None:
    """
    Patches a DeterministicRiskManager instance with conservative
    day-trading parameters from the current TradingConfig.
    """
    config = get_config()

    risk_manager.ATR_MULTIPLIER      = config.atr_multiplier       # 1.0×
    risk_manager.MAX_POSITION_PCT    = config.max_position_pct     # 0.03
    risk_manager.max_single_position = config.max_position_pct     # sync alias
    risk_manager.risk_per_trade_pct  = config.risk_per_trade       # 0.01
    risk_manager.MAX_OPEN_POSITIONS  = config.max_open_positions   # 3

    logger.info(
        f"Day trading config applied: risk={config.risk_per_trade*100:.0f}% "
        f"ATR×{config.atr_multiplier} maxPos={config.max_position_pct*100:.0f}% "
        f"maxOpen={config.max_open_positions}"
    )
