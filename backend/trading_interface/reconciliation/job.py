import logging
from datetime import datetime

from trading_interface.broker.base import AbstractBrokerAPI

logger = logging.getLogger("ReconciliationWorker")


class DriftThresholdBreachedError(Exception):
    """Portfolio alignment has drifted beyond the acceptable tolerance."""
    pass


class SyncWorker:
    """
    CRITICAL: The broker is the absolute source of truth.
    If the agent's internal state drifted due to a missed webhook or pod restart,
    this worker brutally overwrites internal state to reflect broker reality.
    """

    def __init__(
        self,
        broker: AbstractBrokerAPI,
        portfolio_db_client,
        max_drift_tolerance: float = 0.05,
    ):
        self.broker             = broker
        self.db                 = portfolio_db_client
        self.max_drift_tolerance = max_drift_tolerance

    async def execute_periodic_reconciliation(self) -> None:
        """
        1. Fetch logical snapshot from internal DB.
        2. Fetch physical snapshot from broker.
        3. Calculate drift per ticker.
        4. Overwrite local state OR throw fatal kill switch.
        """
        logger.info("Beginning periodic reconciliation...")
        try:
            broker_positions   = await self.broker.get_positions()
            internal_positions = await self.db.get_all_positions()

            reality_map = {p.ticker: p for p in broker_positions}
            local_map   = {p["ticker"]: p["quantity"] for p in internal_positions}

            total_drift_notional = 0.0

            for ticker, broker_pos in reality_map.items():
                true_qty  = broker_pos.quantity
                local_qty = local_map.get(ticker, 0)

                if local_qty != true_qty:
                    # FIX: Use per-share price, not total market_value.
                    # market_value is the notional total (qty * price), not the unit price.
                    per_share_price = (
                        broker_pos.market_value / true_qty
                        if true_qty > 0
                        else 0.0
                    )
                    drift_val = abs(true_qty - local_qty) * per_share_price
                    total_drift_notional += drift_val

                    logger.warning(
                        f"STATE MISMATCH! {ticker}: broker={true_qty}, local={local_qty}. "
                        f"Drift notional=${drift_val:.2f}. Overwriting internal DB."
                    )
                    await self.db.force_overwrite_position(ticker, true_qty)

            account   = await self.broker.get_account()
            drift_pct = (
                total_drift_notional / account.portfolio_value
                if account.portfolio_value > 0
                else 0.0
            )

            if drift_pct > self.max_drift_tolerance:
                msg = (
                    f"CRITICAL: Portfolio drift {drift_pct * 100:.2f}% "
                    f"breached {self.max_drift_tolerance * 100:.0f}% tolerance. Kill switch."
                )
                logger.error(msg)
                raise DriftThresholdBreachedError(msg)

            logger.info("Reconciliation completed safely.")

        except DriftThresholdBreachedError as f:
            await self._trigger_fatal_killswitch(str(f))

        except Exception as e:
            logger.error(f"Reconciliation failed — broker unreachable? {e}")

    async def _trigger_fatal_killswitch(self, reason: str):
        logger.critical(f"KILL SWITCH ACTIVATED: {reason}")
        # TODO: Publish a KillSwitch event to your message broker (SNS/SQS/Redis pub-sub)
        # to halt all ExecutionAgent instances across all replicas.
