import asyncio
import logging
from datetime import datetime
from uuid import UUID

from trading_interface.events.schemas import AuditEvent
from trading_interface.broker.base import AbstractBrokerAPI

logger = logging.getLogger("ReconciliationWorker")

class DriftThresholdBreachedError(Exception):
    """Exception indicating portfolio alignment loss."""
    pass

class SyncWorker:
    """
    CRITICAL: The Broker is the absolute source of truth.
    If the agent's internal state machine (Redis/Postgres) drifted due to a missed
    webhook or crash, this SyncWorker brutally overwrites the internal state to reflect reality.
    """
    def __init__(self, broker: AbstractBrokerAPI, portfolio_db_client, max_drift_tolerance: float = 0.05):
        self.broker = broker
        self.db = portfolio_db_client # Abstracted representation
        self.max_drift_tolerance = max_drift_tolerance

    async def execute_periodic_reconciliation(self) -> None:
        """
        1. Fetch logical snapshot of internal position quantities.
        2. Fetch absolute physical snapshot of broker quantities.
        3. Match hashes/tickers. Calculate raw drift value.
        4. Overwrite local OR throw fatal kill switch.
        """
        logger.info("Beginning Periodic Reconciliation...")
        
        try:
            broker_positions = await self.broker.get_positions()
            internal_positions = await self.db.get_all_positions() 
            
            # Map broker dict: { "MSFT": 15, "AAPL": 10 }
            reality_map = {p.ticker: p.quantity for p in broker_positions}
            local_map = {p["ticker"]: p["quantity"] for p in internal_positions}
            
            total_drift_notional = 0.0
            
            # Identify mismatches
            for ticker, true_qty in reality_map.items():
                local_qty = local_map.get(ticker, 0)
                
                if local_qty != true_qty:
                    price = [p.market_value for p in broker_positions if p.ticker == ticker][0]
                    drift_val = abs(true_qty - local_qty) * price
                    total_drift_notional += drift_val
                    
                    logger.warning(
                        f"STATE MISMATCH! {ticker} Broker={true_qty} Local={local_qty}. "
                        "Overwriting internal DB aggressively."
                    )
                    await self.db.force_overwrite_position(ticker, true_qty)
                    # Emit an AuditEvent about the correction...

            account = await self.broker.get_account()
            
            drift_pct = total_drift_notional / account.portfolio_value
            if drift_pct > self.max_drift_tolerance:
                msg = f"CRITICAL: Portfolio drift breached {self.max_drift_tolerance*100}%. Throwing Kill Switch."
                logger.error(msg)
                raise DriftThresholdBreachedError(msg)
                
            logger.info("Periodic Reconciliation completed safely.")

        except DriftThresholdBreachedError as f:
            # Emit Kill Switch Pub/Sub Event -> Terminate Execution Agent.
            await self._trigger_fatal_killswitch(str(f))

        except Exception as e:
            logger.error(f"Reconciliation completely failed. Broker unreachable? {str(e)}")
            
    async def _trigger_fatal_killswitch(self, reason: str):
        # Implementation to halt trading sequence natively
        logger.critical(f" KILL SWITCH ACTIVATED: {reason}")
