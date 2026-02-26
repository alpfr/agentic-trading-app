import logging
from datetime import datetime
from typing import List, Optional

import httpx

from trading_interface.events.schemas import OrderRequest, OrderResponseStatus, FillEvent
from trading_interface.broker.base import AbstractBrokerAPI, AccountSchema, PositionSchema
from trading_interface.broker.exceptions import (
    RateLimitError, NetworkError, InsufficientFundsError, InvalidTickerError, MarketClosedError
)

logger = logging.getLogger("AlpacaPaperAdapter")

class AlpacaPaperBroker(AbstractBrokerAPI):
    """
    Concrete implementation of the AbstractBrokerAPI for Alpaca.
    Strictly hardcoded to paper-trading base URLs to prevent accidental live execution.
    """

    def __init__(self):
        self.api_key: Optional[str] = None
        self.api_secret: Optional[str] = None
        self.base_url = "https://paper-api.alpaca.markets/v2"
        self._client: Optional[httpx.AsyncClient] = None

    async def _handle_response_errors(self, response: httpx.Response):
        """Translates Alpaca specific HTTP error codes into our standardized architecture exceptions."""
        if response.status_code == 200:
            return

        if response.status_code == 429:
            raise RateLimitError("Alpaca Rate Limit (HTTP 429) hit.")
            
        if response.status_code == 403: # Forbidden / Insufficient Buy Power in Alpaca is often 403
            try:
                 err_msg = response.json().get('message', '')
                 if 'insufficient buying power' in err_msg.lower():
                     raise InsufficientFundsError(f"Alpaca Rejected: {err_msg}")
            except Exception:
                 pass
            
        if response.status_code == 422: # Unprocessable Entity
            try:
                err_msg = response.json().get('message', '')
                if 'market is closed' in err_msg.lower():
                     raise MarketClosedError("Market is closed.")
                if 'invalid symbol' in err_msg.lower():
                     raise InvalidTickerError(f"Ticker not found: {err_msg}")
            except Exception:
                pass

        if response.status_code >= 500:
            raise NetworkError(f"Alpaca Internal Server Error: {response.status_code}")
            
        # Catch-all
        response.raise_for_status()

    async def authenticate(self, api_key: str, secret: str, environment: str) -> bool:
        """Configures the httpx client with the injected credentials."""
        if environment.upper() != "PAPER":
            logger.warning("Attempted to initiate Alpaca API with non-PAPER mode flag. Enforcing Paper URLs anyway.")
            environment = "PAPER"

        self.api_key = api_key
        self.api_secret = secret
        
        headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
            "accept": "application/json"
        }
        
        self._client = httpx.AsyncClient(headers=headers, timeout=10.0)
        logger.info(f"Alpaca API Client Initialized ({self.base_url})")

        # Validate connection
        try:
             await self.get_account()
             return True
        except Exception as e:
             logger.error(f"Alpaca Authentication Validation Failed: {e}")
             return False

    async def get_account(self) -> AccountSchema:
        """Fetches and abstracts Alpaca 'account' payload."""
        response = await self._client.get(f"{self.base_url}/account")
        await self._handle_response_errors(response)
        
        data = response.json()
        
        return AccountSchema(
            buying_power=float(data.get("buying_power", 0.0)),
            portfolio_value=float(data.get("equity", 0.0)),
            is_trading_blocked=data.get("trading_blocked", False) or data.get("account_blocked", False)
        )

    async def get_positions(self) -> List[PositionSchema]:
        """Fetches current portfolio array and standardizes it to `PositionSchema`."""
        response = await self._client.get(f"{self.base_url}/positions")
        await self._handle_response_errors(response)
        
        data = response.json()
        positions = []
        for p in data:
            positions.append(PositionSchema(
                ticker=p.get("symbol"),
                quantity=int(p.get("qty", 0)),
                market_value=float(p.get("market_value", 0.0)),
                avg_entry_price=float(p.get("avg_entry_price", 0.0))
            ))
        return positions

    async def place_order(self, order: OrderRequest) -> OrderResponseStatus:
        """
        Translates our precise internal definitions to the exact JSON Alpaca expects.
        Uses idempotency key as 'client_order_id' to prevent duplicate fills on network timeouts.
        """
        payload = {
            "symbol": order.ticker,
            "qty": str(order.quantity), 
            "side": order.action.lower(),  # "buy" or "sell"
            "type": order.order_type.lower(),
            "time_in_force": order.time_in_force.lower(),
            "client_order_id": str(order.idempotency_key) # Guarantee no duplicate retries
        }
        
        if order.order_type == "LIMIT":
            if not order.limit_price:
                 raise ValueError("Limit Orders require a limit_price float.")
            payload["limit_price"] = str(round(order.limit_price, 2))
            
        if order.extended_hours:
             payload["extended_hours"] = True

        try:
            response = await self._client.post(f"{self.base_url}/orders", json=payload)
            await self._handle_response_errors(response)
            
            data = response.json()
            
            return OrderResponseStatus(
                broker_order_id=str(data.get("id")),
                internal_order_id=order.internal_order_id,
                status="ACCEPTED",
                submitted_at=datetime.utcnow()
            )
        except httpx.RequestError as exc:
             logger.error(f"HTTP Request failed during order placement: {exc}")
             raise NetworkError(f"HTTPx Request Error: {exc}")

    async def cancel_order(self, broker_order_id: str) -> bool:
        """Cancels open orders by Alpaca ID."""
        response = await self._client.delete(f"{self.base_url}/orders/{broker_order_id}")
        await self._handle_response_errors(response)
        return response.status_code == 204 # 204 No Content is standard success

    async def get_fills(self, since: datetime) -> List[FillEvent]:
        # Fallback polling implementation stub normally served by websockets.
        pass
        
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()
