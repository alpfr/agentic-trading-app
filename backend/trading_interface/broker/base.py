import abc
from typing import List, Optional
from datetime import datetime

# Local Imports
from trading_interface.events.schemas import OrderRequest, OrderResponseStatus, FillEvent

class AccountSchema:
    def __init__(self, buying_power: float, portfolio_value: float, is_trading_blocked: bool):
        self.buying_power = buying_power
        self.portfolio_value = portfolio_value
        self.is_trading_blocked = is_trading_blocked

class PositionSchema:
    def __init__(self, ticker: str, quantity: int, market_value: float, avg_entry_price: float):
        self.ticker = ticker
        self.quantity = quantity
        self.market_value = market_value
        self.avg_entry_price = avg_entry_price

class AbstractBrokerAPI(abc.ABC):
    """
    Standardized, broker-agnostic interface wrapping external SDKs.
    Every concrete class (e.g., AlpacaBroker) MUST implement these methods.
    Returns schema models instead of dynamic JSON dicts to enforce determinism.
    """

    @abc.abstractmethod
    async def authenticate(self, api_key: str, secret: str, environment: str) -> bool:
        """Resolves OAuth/Key connections and validates PAPER vs LIVE configurations."""
        pass

    @abc.abstractmethod
    async def get_account(self) -> AccountSchema:
        """Fetch current margin, equity, and account locking status."""
        pass

    @abc.abstractmethod
    async def get_positions(self) -> List[PositionSchema]:
        """Fetch real-time asset alignment strictly from the Broker's perspective."""
        pass

    @abc.abstractmethod
    async def place_order(self, order: OrderRequest) -> OrderResponseStatus:
        """
        Executes a native order relying STRICTLY on the idempotency_key headers.
        Must raise appropriate standardized BrokerException if the call fails.
        """
        pass

    @abc.abstractmethod
    async def cancel_order(self, broker_order_id: str) -> bool:
        """Attempts to cancel an upstream pending order."""
        pass

    @abc.abstractmethod
    async def get_fills(self, since: datetime) -> List[FillEvent]:
        """Provides REST fallback polling logic if Webhooks drop/fail."""
        pass
