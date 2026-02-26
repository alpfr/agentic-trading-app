import os
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime

# You can swap this with a real PostgreSQL string if you have one available,
# e.g., "postgresql://user:pass@localhost/market_db"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./market_data.db")

engine = create_engine(
    DATABASE_URL, 
    # check_same_thread false is needed for SQLite to run in FastAPI background tasks
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class StoredMarketData(Base):
    __tablename__ = "market_data"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String, index=True)
    current_price = Column(Float)
    atr_14 = Column(Float)
    avg_daily_volume = Column(Integer)
    sma_20 = Column(Float)
    sma_50 = Column(Float)
    vix_level = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow)

# Ensure tables are created when this module is run or imported
Base.metadata.create_all(bind=engine)
