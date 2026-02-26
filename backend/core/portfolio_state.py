from pydantic import BaseModel
from typing import List, Dict

class PositionState(BaseModel):
    ticker: str
    sector: str
    quantity: int
    market_value: float
    unrealized_pnl_pct: float

class PortfolioState(BaseModel):
    """
    In-memory representation of the account.
    This data is populated by syncing with the Broker API or Database.
    """
    buying_power: float
    total_equity: float
    high_water_mark: float  
    daily_start_equity: float
    positions: List[PositionState]
    is_trading_halted: bool = False

    @property
    def current_drawdown_pct(self) -> float:
        if self.high_water_mark <= 0:
            return 0.0
        return (self.high_water_mark - self.total_equity) / self.high_water_mark

    @property
    def daily_loss_pct(self) -> float:
        if self.daily_start_equity <= 0:
            return 0.0
        return (self.daily_start_equity - self.total_equity) / self.daily_start_equity

    def get_sector_exposure(self, target_sector: str) -> float:
        sector_value = sum(p.market_value for p in self.positions if p.sector == target_sector)
        return sector_value / self.total_equity if self.total_equity > 0 else 0.0

class MarketContext(BaseModel):
    """
    Data fetched synchronously by the Risk Engine to validate the signal.
    """
    ticker: str
    current_price: float
    atr_14: float
    avg_daily_volume: int
    days_to_earnings: int
    vix_level: float
    sma_20: float = 0.0
    sma_50: float = 0.0

