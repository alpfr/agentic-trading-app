"""
Day Trading Risk Overrides
==========================
Patches the DeterministicRiskManager for day trading mode:
  - Tighter ATR stop multiplier (1× vs default 2×)
  - Smaller max position size (3% vs default 5%)
  - Intraday position tracking
  - EOD close-all logic
"""

import logging
from typing import List
from sqlalchemy.orm import Session
from core.database import SessionLocal, StoredPosition
from core.watchlist import get_config

logger = logging.getLogger("DayTrading")


async def close_all_positions(broker_client) -> List[str]:
    """
    EOD sweep: close every open position for day trading.
    Called by the scheduler at 15:45 ET.
    Returns list of tickers closed.
    """
    closed = []
    db: Session = SessionLocal()
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
                from trading_interface.events.schemas import OrderRequest, OrderSide, OrderType
                order = OrderRequest(
                    ticker     = pos.ticker,
                    side       = OrderSide.SELL,
                    quantity   = pos.shares,
                    order_type = OrderType.MARKET,
                    notes      = "EOD_DAY_TRADING_CLOSE",
                )
                await broker_client.place_order(order)

                pos.is_open    = False
                pos.exit_price = pos.current_price
                pos.exit_time  = __import__('datetime').datetime.utcnow().isoformat()
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
    Patches a DeterministicRiskManager instance with day-trading parameters
    from the current TradingConfig.
    """
    config = get_config()

    # Override risk parameters inline
    risk_manager.RISK_PER_TRADE         = config.risk_per_trade      # 1%
    risk_manager.ATR_MULTIPLIER         = config.atr_multiplier      # 1× (tight)
    risk_manager.MAX_POSITION_PCT       = config.max_position_pct    # 3%
    risk_manager.MAX_OPEN_POSITIONS     = config.max_open_positions   # 3

    logger.info(
        f"Day trading config applied: risk={config.risk_per_trade*100:.0f}% "
        f"ATR×{config.atr_multiplier} maxPos={config.max_position_pct*100:.0f}% "
        f"maxOpen={config.max_open_positions}"
    )
