import asyncio
import logging
import uuid
from datetime import datetime

# Local Architecture Imports
from trading_interface.events.schemas import RiskApproved, RiskMetrics, OrderResponseStatus
from trading_interface.broker.base import AbstractBrokerAPI, AccountSchema, PositionSchema
from trading_interface.execution.agent import ExecutionAgent
from trading_interface.reconciliation.job import SyncWorker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

class MockBroker(AbstractBrokerAPI):
    """A simulated Paper Trading Broker for the Starter Implementation."""
    async def authenticate(self, api_key: str, secret: str, environment: str) -> bool:
        logging.info(f"MockBroker Authenticated: {environment} environment.")
        return True
        
    async def get_account(self) -> AccountSchema:
        return AccountSchema(buying_power=50000.00, portfolio_value=120000.00, is_trading_blocked=False)
        
    async def get_positions(self) -> list[PositionSchema]:
        return [PositionSchema(ticker="AAPL", quantity=10, market_value=182.50, avg_entry_price=175.00)]
        
    async def place_order(self, order) -> OrderResponseStatus:
        logging.info(f"MockBroker received Native Limit Order: {order.quantity} x {order.ticker} @ ${order.limit_price}")
        return OrderResponseStatus(
            broker_order_id=f"brk_{uuid.uuid4().hex[:8]}",
            internal_order_id=order.internal_order_id,
            status="ACCEPTED",
            submitted_at=datetime.utcnow()
        )
        
    async def cancel_order(self, broker_order_id: str) -> bool:
        return True
        
    async def get_fills(self, since: datetime) -> list:
        return []

async def demonstrate_lifecycle():
    broker = MockBroker()
    await broker.authenticate("mock_key", "mock_sec", "PAPER")

    # The Execution Agent is strictly blind to strategy.
    # It requires the explicit "LIVE_MODE=true" flag for production logic.
    executor = ExecutionAgent(broker=broker, is_live_mode=False)

    # 1. The Multi-Agent Layer generates an event...
    # (Pretending the RiskManager successfully validated the signal...)
    
    approved_signal = RiskApproved(
        event_id=uuid.uuid4(),
        signal_id=uuid.uuid4(),
        ticker="MSFT",
        action="BUY_TO_OPEN",
        approved_quantity=15,
        approved_limit_price=415.50,
        risk_metrics=RiskMetrics(
            account_exposure_pct=5.8,
            volatility_atr=8.40,
            hard_stop_loss=398.00
        )
    )

    logging.info("--- TRIGGERING EXECUTION ENGINE ---")
    response = await executor.execute_approved_risk(approved_signal)
    
    if response:
        logging.info(f"--- SUCCESS: Order Processed {response.broker_order_id} ---")
    else:
        logging.error("--- EXECUTION REJECTED (Stale or Macro Block) ---")

    # 2. Simulate Reconciliation loop checking current realities.
    class MockDB:
        async def get_all_positions(self): return [{"ticker": "AAPL", "quantity": 10}]
        async def force_overwrite_position(self, ticker, qty): pass

    reconciler = SyncWorker(broker=broker, portfolio_db_client=MockDB())
    await reconciler.execute_periodic_reconciliation()

if __name__ == "__main__":
    asyncio.run(demonstrate_lifecycle())
