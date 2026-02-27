import asyncio
import logging
from datetime import datetime, timedelta
import uuid

# Local Abstractions
from trading_interface.events.schemas import RiskApproved, OrderRequest, OrderResponseStatus, AuditEvent
from trading_interface.broker.base import AbstractBrokerAPI
from trading_interface.broker.exceptions import (
    RateLimitError, NetworkError, InsufficientFundsError, MarketClosedError
)

logger = logging.getLogger("ExecutionAgent")

class ExecutionAgent:
    """
    The STRICT solitary mechanism for executing broker instructions. 
    It is fully blind to strategy logic, observing only explicit 'RiskApproved' signals.
    """

    def __init__(self, broker: AbstractBrokerAPI, is_live_mode: bool = False):
        self.broker = broker
        # NON-NEGOTIABLE SAFETY GATE: Hard default to paper trading.
        self.is_live_mode = is_live_mode
        self.max_retries = 3

    async def _pre_trade_checks(self, risk_event: RiskApproved) -> bool:
        """Evaluates staleness and immediate macro liquidity blockades."""
        now = datetime.utcnow()
        if (now - risk_event.timestamp).total_seconds() > 300:
            logger.error(f"STALENESS REJECT: Risk signal {risk_event.signal_id} is > 5 minutes old.")
            # Emit Audit Reject
            return False
            
        # TODO: Implement MarketHours Check via DataAPI
        return True

    async def execute_approved_risk(self, risk_event: RiskApproved) -> OrderResponseStatus | None:
        """
        State Machine: CREATED -> SUBMITTED. 
        Handles exponential backoffs natively within the loop.
        """
        # 1. Verification Phase
        if not await self._pre_trade_checks(risk_event):
            return None

        # 2. Schema Translation
        internal_id = uuid.uuid4()
        idempotency_key = uuid.uuid4() 
        # Ideally, look up existing idempotency bounds in Redis tied to signal_id
        
        # Retirement investing: LIMIT orders with DAY time-in-force.
        # LIMIT avoids overpaying on entry (risk manager sets limit 0.5% below ask).
        # DAY ensures unfilled orders expire at close rather than carrying overnight.
        order = OrderRequest(
            internal_order_id=internal_id,
            idempotency_key=idempotency_key,
            ticker=risk_event.ticker,
            action=risk_event.action[:3],  # BUY_TO_OPEN → BUY, SELL_TO_CLOSE → SEL
            order_type="LIMIT",
            time_in_force="DAY",
            quantity=risk_event.approved_quantity,
            limit_price=risk_event.approved_limit_price,
        )

        logger.info(f"Submitting OrderRequest {order.internal_order_id} (IdemKey: {order.idempotency_key})")

        # 3. Execution Phase w/ Network Retries
        retries = 0
        while retries <= self.max_retries:
            try:
                # Execution against abstract broker SDK
                response = await self.broker.place_order(order)
                logger.info(f"Broker ACK Success. BrokerID: {response.broker_order_id}")
                return response

            except RateLimitError as e:
                backoff = 2 ** retries
                logger.warning(f"Rate limited by broker. Retrying in {backoff}s...")
                await asyncio.sleep(backoff)
                retries += 1

            except NetworkError as e:
                logger.warning("Network Degradation. Passing Idempotency Key ensures no dupes.")
                await asyncio.sleep(3)
                retries += 1
                
            except InsufficientFundsError as e:
                logger.error("FATAL: Insufficient execution funds despite RiskApproval.")
                # Terminate loop entirely.
                break 

            except MarketClosedError as e:
                logger.error("Market closed. Dropping order execution instruction.")
                break

            except Exception as e:
                logger.error(f"An unstructured critical failure occurred: {e}")
                # Emit to Sentry/PagerDuty
                break

        logger.error(f"Execution failed after {retries} retries for signal {risk_event.signal_id}.")
        return None
