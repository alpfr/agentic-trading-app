import os
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, Text
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime

# Swap to PostgreSQL via DATABASE_URL env var in production (e.g. RDS).
# SQLite is used as a local development fallback only.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./trading_app.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ---------------------------------------------------------------------------
# Market Data Snapshots (unchanged, extended with index)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Positions — replaces GLOBAL_POSITIONS in-memory list
# ---------------------------------------------------------------------------
class StoredPosition(Base):
    __tablename__ = "positions"

    id = Column(String, primary_key=True)       # UUID string
    ticker = Column(String, index=True, nullable=False)
    side = Column(String, nullable=False)        # LONG | SHORT
    shares = Column(Integer, nullable=False)
    entry_price = Column(Float, nullable=False)
    current_price = Column(Float, nullable=False)
    stop_price = Column(Float, nullable=True)
    pnl_pct = Column(Float, default=0.0)
    is_open = Column(Boolean, default=True)
    opened_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Audit Logs — replaces GLOBAL_AUDIT_LOGS in-memory list
# ---------------------------------------------------------------------------
class StoredAuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True)       # UUID string (short)
    time = Column(String, nullable=False)        # HH:MM:SS for display
    agent = Column(String, nullable=False)
    action = Column(String, nullable=False)
    ticker = Column(String, nullable=False)
    reason = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Agent Insights — replaces GLOBAL_AGENT_INSIGHTS in-memory list
# ---------------------------------------------------------------------------
class StoredAgentInsight(Base):
    __tablename__ = "agent_insights"

    id = Column(String, primary_key=True)
    time = Column(String, nullable=False)
    ticker = Column(String, nullable=False)
    action = Column(String, nullable=False)
    confidence = Column(Float, nullable=False)
    rationale = Column(Text, nullable=False)
    technicals = Column(Text, nullable=True)
    sentiment = Column(Text, nullable=True)
    fundamentals = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# Create all tables on startup
Base.metadata.create_all(bind=engine)
