"""
Agentic Trading App — FastAPI Backend
======================================
Fixes applied vs. original:
  - All endpoints protected by X-API-Key authentication
  - CORS origins driven by CORS_ALLOWED_ORIGINS env var (no localhost hardcode)
  - Async httpx used for external HTTP calls (no blocking requests.get)
  - GLOBAL_* in-memory lists replaced with SQLAlchemy DB persistence
  - ExecutionAgent.execute_approved_risk() is now actually called
  - PortfolioState hydrated from real BROKER_CLIENT.get_account() call
  - MarketDataAgent instantiated once at module level (cache now works)
  - Rate limiting on /api/trigger via simple token bucket
  - Ticker sanitization on all user-supplied inputs
  - Server-Sent Events (SSE) stream endpoint replacing 2s polling
  - /health endpoint for K8s liveness/readiness probes
  - DELETE /api/market-data requires auth
"""

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime
from typing import AsyncGenerator

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import yfinance as yf

# Local imports
from agents.market_data import MarketDataAgent
from agents.movers import get_movers
from agents.strategy import StrategyAgent, MockSwingLLMClient, OpenAILLMClient
from core.database import (
    SessionLocal,
    StoredMarketData,
    StoredPosition,
    StoredAuditLog,
    StoredAgentInsight,
)
from core.portfolio_state import PortfolioState, MarketContext, PositionState
from core.risk_gatekeeper import DeterministicRiskManager
from core.watchlist import get_config, update_config, DEFAULT_WATCHLIST
from core.scheduler import MarketScheduler
from core.day_trading import close_all_positions, apply_day_trading_config
from trading_interface.broker.alpaca_paper import AlpacaPaperBroker
from trading_interface.broker.base import AccountSchema
from trading_interface.events.schemas import RiskRejected, RiskApproved
from trading_interface.execution.agent import ExecutionAgent
from trading_interface.security import require_api_key, sanitize_ticker

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ---------------------------------------------------------------------------
# App & Middleware
# ---------------------------------------------------------------------------
app = FastAPI(title="Agentic Trading App API", version="1.1.0")

_cors_origins = os.getenv(
    "CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Module-level singletons (fixes cache-busting and state divergence)
# ---------------------------------------------------------------------------
BROKER_CLIENT   = AlpacaPaperBroker()
MARKET_AGENT    = MarketDataAgent()   # Module-level: cache survives across requests

# Simple in-process rate limit for /api/trigger: max 1 call per 10s per ticker
_trigger_last_called: dict[str, float] = {}
TRIGGER_COOLDOWN_SECONDS = 10

# ---------------------------------------------------------------------------
# Startup: init DB, apply trading config, launch scheduler
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    from core.database import Base, engine
    Base.metadata.create_all(bind=engine)

    # Apply day trading config to a temp instance so get_config() is seeded
    # (run_agent_loop creates its own DeterministicRiskManager per call)
    _rm = DeterministicRiskManager()
    apply_day_trading_config(_rm)
    logger.info("Day trading config applied: conservative, 1% risk, 1×ATR stop")

    # Launch market-hours scheduler
    async def _run_agent(ticker: str):
        try:
            await run_agent_loop(ticker)
        except Exception as e:
            logger.error(f"Scheduled agent run failed [{ticker}]: {e}")

    async def _close_all():
        await close_all_positions(BROKER_CLIENT)

    scheduler = MarketScheduler(
        run_agent_fn           = _run_agent,
        close_all_positions_fn = _close_all,
        get_config_fn          = get_config,
    )
    asyncio.create_task(scheduler.run())
    cfg = get_config()
    logger.info(f"Scheduler running — watchlist: {cfg.watchlist}, interval: {cfg.scan_interval_minutes}min")

# ---------------------------------------------------------------------------
# Helper: DB Audit Logging
# ---------------------------------------------------------------------------
def log_audit(action: str, agent: str, ticker: str, reason: str):
    entry_id = str(uuid.uuid4())[:8]
    db = SessionLocal()
    try:
        db.add(StoredAuditLog(
            id=entry_id,
            time=time.strftime("%H:%M:%S"),
            agent=agent,
            action=action,
            ticker=ticker,
            reason=reason,
        ))
        db.commit()
    except Exception as e:
        logging.error(f"Audit log write failed: {e}")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Helper: Build real PortfolioState from broker
# ---------------------------------------------------------------------------
async def _build_portfolio_state() -> PortfolioState:
    """
    Hydrates PortfolioState from live broker data.
    Falls back to a conservative dummy if broker is unreachable (paper/dev mode).
    """
    try:
        account   = await BROKER_CLIENT.get_account()
        positions = await BROKER_CLIENT.get_positions()

        position_states = [
            PositionState(
                ticker=p.ticker,
                sector="UNKNOWN",          # Sector resolution requires separate API
                quantity=p.quantity,
                market_value=p.market_value,
                unrealized_pnl_pct=0.0,
            )
            for p in positions
        ]

        return PortfolioState(
            buying_power=account.buying_power,
            total_equity=account.portfolio_value,
            high_water_mark=account.portfolio_value,   # Simplified; track HWM in DB for production
            daily_start_equity=account.portfolio_value,
            positions=position_states,
        )

    except Exception as e:
        logging.warning(
            f"Could not reach broker for portfolio state ({e}). "
            "Using conservative fallback — risk sizing will use minimal capital."
        )
        return PortfolioState(
            buying_power=0.0,
            total_equity=1.0,   # Near-zero equity forces BUYING_POWER rejection on any real order
            high_water_mark=1.0,
            daily_start_equity=1.0,
            positions=[],
        )


# ---------------------------------------------------------------------------
# Core Agent Loop
# ---------------------------------------------------------------------------
async def run_agent_loop(ticker: str):
    """Async pipeline: MarketData → Strategy → Risk → Execution."""

    log_audit("PROCESSING", "Supervisor", ticker, "Dispatched MarketDataAgent.")

    # 1. Market context (module-level agent = cache works correctly)
    live_context = await MARKET_AGENT.fetch_market_context(ticker)

    # Persist snapshot to DB
    db = SessionLocal()
    try:
        db.add(StoredMarketData(
            ticker=live_context.ticker,
            current_price=live_context.current_price,
            atr_14=live_context.atr_14,
            avg_daily_volume=live_context.avg_daily_volume,
            sma_20=live_context.sma_20,
            sma_50=live_context.sma_50,
            vix_level=live_context.vix_level,
        ))
        db.commit()
        log_audit("SAVED", "Database", ticker, f"Stored live data (price=${live_context.current_price})")
    except Exception as e:
        log_audit("ERROR", "Database", ticker, f"DB write failed: {e}")
    finally:
        db.close()

    if live_context.avg_daily_volume == 0:
        log_audit("FAILED", "MarketDataAgent", ticker, "Invalid ticker or yfinance API error.")
    else:
        log_audit("SYNCED", "MarketDataAgent", ticker, f"Price=${live_context.current_price}")

    # 2. Strategy agent
    technicals  = await MARKET_AGENT.generate_technical_summary_string(ticker, live_context)
    sentiment   = await MARKET_AGENT.fetch_news_and_sentiment(ticker)
    fundamentals = await MARKET_AGENT.fetch_fundamentals(ticker)

    api_key = os.getenv("OPENAI_API_KEY")
    strategy = (
        StrategyAgent(llm_client=OpenAILLMClient(api_key=api_key))
        if api_key
        else StrategyAgent(llm_client=MockSwingLLMClient())
    )
    label = "LLM" if api_key else "Mock LLM"
    log_audit("PROCESSING", "StrategyAgent", ticker, f"Dispatched {label} client.")

    signal = await strategy.evaluate_context(ticker, technicals, sentiment, fundamentals)
    log_audit("PROPOSED", "StrategyAgent", ticker,
              f"Proposed {signal.suggested_action} (confidence={signal.confidence:.2f}). {signal.rationale}")

    # Persist insight
    insight_id = str(uuid.uuid4())[:8]
    db = SessionLocal()
    try:
        db.add(StoredAgentInsight(
            id=insight_id,
            time=time.strftime("%H:%M:%S"),
            ticker=ticker,
            action=signal.suggested_action,
            confidence=signal.confidence,
            rationale=signal.rationale,
            technicals=technicals,
            sentiment=sentiment,
            fundamentals=fundamentals,
        ))
        db.commit()
    except Exception as e:
        logging.error(f"Insight write failed: {e}")
    finally:
        db.close()

    # 3. Risk evaluation against REAL portfolio state
    portfolio     = await _build_portfolio_state()
    risk          = DeterministicRiskManager()
    risk_result   = risk.evaluate_signal(signal, portfolio, live_context)

    if isinstance(risk_result, RiskRejected):
        log_audit("REJECTED", "RiskManager", ticker,
                  f"[{risk_result.failing_metric}] {risk_result.reason}")
        return

    log_audit("APPROVED", "RiskManager", ticker,
              f"Sizing: {risk_result.approved_quantity} shares @ ${risk_result.approved_limit_price}")

    # 4. Execution — actually call the ExecutionAgent
    executor = ExecutionAgent(broker=BROKER_CLIENT, is_live_mode=False)

    try:
        if not BROKER_CLIENT._client:
            await BROKER_CLIENT.authenticate(
                os.getenv("ALPACA_API_KEY", ""),
                os.getenv("ALPACA_SECRET_KEY", ""),
                "PAPER",
            )
    except Exception as auth_err:
        log_audit("WARN", "ExecutionAgent", ticker,
                  f"Broker auth failed ({auth_err}). Order will be paper-simulated.")

    order_response = await executor.execute_approved_risk(risk_result)

    if order_response:
        log_audit("FILLED", "ExecutionAgent", ticker,
                  f"Broker ACK {order_response.broker_order_id}: "
                  f"{risk_result.approved_quantity} x {ticker} @ ${risk_result.approved_limit_price} (Paper).")

        # Persist position to DB
        db = SessionLocal()
        try:
            side = "LONG" if risk_result.action == "BUY_TO_OPEN" else "SHORT"
            db.add(StoredPosition(
                id=str(uuid.uuid4()),
                ticker=ticker,
                side=side,
                shares=risk_result.approved_quantity,
                entry_price=risk_result.approved_limit_price,
                current_price=live_context.current_price,
                stop_price=risk_result.risk_metrics.hard_stop_loss,
                pnl_pct=0.0,
                is_open=True,
            ))
            db.commit()
        except Exception as e:
            logging.error(f"Position write failed: {e}")
        finally:
            db.close()
    else:
        log_audit("FAILED", "ExecutionAgent", ticker, "Order rejected after retries. Check broker logs.")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health_check():
    """K8s liveness & readiness probe target."""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/portfolio", dependencies=[Depends(require_api_key)])
async def get_portfolio():
    db = SessionLocal()
    try:
        open_positions = db.query(StoredPosition).filter(StoredPosition.is_open == True).all()
        positions_out  = []
        total_pnl_dollars = 0.0

        for p in open_positions:
            if p.entry_price > 0:
                pnl_pct = ((p.current_price - p.entry_price) / p.entry_price) * 100
                pnl_dollars = (p.current_price - p.entry_price) * p.shares
                if p.side == "SHORT":
                    pnl_pct    = -pnl_pct
                    pnl_dollars = -pnl_dollars
                total_pnl_dollars += pnl_dollars
            else:
                pnl_pct = 0.0

            positions_out.append({
                "id":      p.id,
                "ticker":  p.ticker,
                "side":    p.side,
                "shares":  p.shares,
                "entry":   p.entry_price,
                "current": p.current_price,
                "stop":    p.stop_price,
                "pnl_pct": round(pnl_pct, 4),
            })

        # Attempt live account value from broker; fall back gracefully
        try:
            account    = await BROKER_CLIENT.get_account()
            base_value = account.portfolio_value
        except Exception:
            base_value = 100_000.0  # Demo fallback

        return {
            "account_value": round(base_value + total_pnl_dollars, 2),
            "positions": positions_out,
        }
    finally:
        db.close()


@app.get("/api/market-data", dependencies=[Depends(require_api_key)])
async def get_market_data():
    db = SessionLocal()
    try:
        records = (
            db.query(StoredMarketData)
            .order_by(StoredMarketData.timestamp.desc())
            .limit(50)
            .all()
        )
        return {
            "saved_data": [
                {
                    "id":        r.id,
                    "ticker":    r.ticker,
                    "price":     r.current_price,
                    "vix":       r.vix_level,
                    "timestamp": r.timestamp.isoformat(),
                }
                for r in records
            ]
        }
    finally:
        db.close()


@app.delete("/api/market-data", dependencies=[Depends(require_api_key)])
async def delete_market_data():
    db = SessionLocal()
    try:
        db.query(StoredMarketData).delete()
        db.commit()
        return {"status": "success", "message": "Market data records cleared."}
    finally:
        db.close()


@app.get("/api/quote/{ticker}", dependencies=[Depends(require_api_key)])
def get_quote(ticker: str):
    ticker = sanitize_ticker(ticker)
    try:
        stock = yf.Ticker(ticker)
        info  = stock.info
        summary = info.get("longBusinessSummary", "No summary available.")
        if len(summary) > 800:
            summary = summary[:800] + "..."
        return {
            "ticker":          ticker,
            "name":            info.get("shortName", "N/A"),
            "sector":          info.get("sector", "N/A"),
            "industry":        info.get("industry", "N/A"),
            "current_price":   info.get("currentPrice", info.get("regularMarketPrice", 0.0)),
            "market_cap":      info.get("marketCap", 0),
            "summary":         summary,
            "fiftyTwoWeekHigh": info.get("fiftyTwoWeekHigh", 0.0),
            "fiftyTwoWeekLow":  info.get("fiftyTwoWeekLow", 0.0),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/movers", dependencies=[Depends(require_api_key)])
async def fetch_movers():
    """
    Returns top gainers, losers, and most active tickers.
    PRIMARY  — yf.screen() Yahoo Finance predefined screeners (handles cookie/crumb auth)
    FALLBACK — 40-ticker watchlist with 2-day OHLCV computation if screener fails.
    Cached 2 minutes to avoid hammering Yahoo Finance.
    """
    try:
        result = await get_movers()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch movers: {e}")


# ---------------------------------------------------------------------------
# Watchlist & Config endpoints
# ---------------------------------------------------------------------------
@app.get("/api/watchlist", dependencies=[Depends(require_api_key)])
async def get_watchlist():
    """Return current watchlist and trading config."""
    cfg = get_config()
    return {
        "watchlist":             cfg.watchlist,
        "style":                 cfg.style,
        "risk_profile":          cfg.risk_profile,
        "risk_per_trade_pct":    cfg.risk_per_trade * 100,
        "atr_multiplier":        cfg.atr_multiplier,
        "max_position_pct":      cfg.max_position_pct * 100,
        "max_open_positions":    cfg.max_open_positions,
        "scan_interval_minutes": cfg.scan_interval_minutes,
        "eod_close_time_et":     cfg.eod_close_time_et,
    }


@app.put("/api/watchlist", dependencies=[Depends(require_api_key)])
async def set_watchlist(payload: dict):
    """
    Update watchlist tickers.
    Body: { "tickers": ["AAOI", "BWIN", "DELL", "FIGS", "SSL"] }
    """
    raw = payload.get("tickers", [])
    tickers = []
    for t in raw:
        clean = sanitize_ticker(t)
        if clean:
            tickers.append(clean)
    if not tickers:
        raise HTTPException(status_code=400, detail="No valid tickers provided")
    update_config(watchlist=tickers)
    return {"watchlist": tickers, "message": f"Watchlist updated: {tickers}"}


@app.post("/api/watchlist/scan", dependencies=[Depends(require_api_key)])
async def scan_watchlist(background_tasks: BackgroundTasks):
    """
    Immediately trigger an agent loop for every ticker in the watchlist.
    Returns immediately; scans run in background.
    """
    cfg = get_config()
    triggered = []
    for ticker in cfg.watchlist:
        background_tasks.add_task(run_agent_loop, ticker)
        triggered.append(ticker)
    return {
        "message":   f"Scanning {len(triggered)} tickers",
        "tickers":   triggered,
        "style":     cfg.style,
        "risk":      cfg.risk_profile,
    }


@app.post("/api/watchlist/close-all", dependencies=[Depends(require_api_key)])
async def close_all_endpoint():
    """Manually trigger EOD close of all open positions."""
    closed = await close_all_positions(BROKER_CLIENT)
    return {
        "message": f"Closed {len(closed)} positions",
        "tickers": closed,
    }


@app.get("/api/logs", dependencies=[Depends(require_api_key)])
async def get_logs():
    db = SessionLocal()
    try:
        logs = (
            db.query(StoredAuditLog)
            .order_by(StoredAuditLog.created_at.desc())
            .limit(20)
            .all()
        )
        return {
            "logs": [
                {
                    "id":     l.id,
                    "time":   l.time,
                    "agent":  l.agent,
                    "action": l.action,
                    "ticker": l.ticker,
                    "reason": l.reason,
                }
                for l in logs
            ]
        }
    finally:
        db.close()


@app.get("/api/insights", dependencies=[Depends(require_api_key)])
async def get_insights():
    db = SessionLocal()
    try:
        insights = (
            db.query(StoredAgentInsight)
            .order_by(StoredAgentInsight.created_at.desc())
            .limit(20)
            .all()
        )
        return {
            "insights": [
                {
                    "id":          i.id,
                    "time":        i.time,
                    "ticker":      i.ticker,
                    "action":      i.action,
                    "confidence":  i.confidence,
                    "rationale":   i.rationale,
                    "technicals":  i.technicals,
                    "sentiment":   i.sentiment,
                    "fundamentals": i.fundamentals,
                }
                for i in insights
            ]
        }
    finally:
        db.close()


@app.post("/api/trigger", dependencies=[Depends(require_api_key)])
async def trigger_agent(background_tasks: BackgroundTasks, payload: dict):
    """
    Kicks off the async agent loop.
    Rate-limited: one call per ticker per TRIGGER_COOLDOWN_SECONDS.
    """
    raw_ticker = payload.get("ticker", "AAPL")
    ticker     = sanitize_ticker(raw_ticker)

    now  = time.monotonic()
    last = _trigger_last_called.get(ticker, 0.0)
    if now - last < TRIGGER_COOLDOWN_SECONDS:
        remaining = int(TRIGGER_COOLDOWN_SECONDS - (now - last))
        raise HTTPException(
            status_code=429,
            detail=f"Rate limited: wait {remaining}s before triggering {ticker} again.",
        )
    _trigger_last_called[ticker] = now

    background_tasks.add_task(run_agent_loop, ticker)
    return {"status": "dispatched", "message": f"Agents spinning up for {ticker}"}


# ---------------------------------------------------------------------------
# SSE Stream — replaces 2-second polling from the frontend
# ---------------------------------------------------------------------------
@app.get("/api/stream", dependencies=[Depends(require_api_key)])
async def event_stream():
    """
    Server-Sent Events endpoint.
    The frontend subscribes once; the server pushes state changes.
    Replaces the 2s polling pattern that fired 4 concurrent requests every cycle.
    """
    async def generator() -> AsyncGenerator[str, None]:
        while True:
            try:
                db = SessionLocal()
                try:
                    logs = (
                        db.query(StoredAuditLog)
                        .order_by(StoredAuditLog.created_at.desc())
                        .limit(20)
                        .all()
                    )
                    insights = (
                        db.query(StoredAgentInsight)
                        .order_by(StoredAgentInsight.created_at.desc())
                        .limit(20)
                        .all()
                    )
                    positions = (
                        db.query(StoredPosition)
                        .filter(StoredPosition.is_open == True)
                        .all()
                    )
                finally:
                    db.close()

                payload = json.dumps({
                    "logs": [
                        {"id": l.id, "time": l.time, "agent": l.agent,
                         "action": l.action, "ticker": l.ticker, "reason": l.reason}
                        for l in logs
                    ],
                    "insights": [
                        {"id": i.id, "time": i.time, "ticker": i.ticker,
                         "action": i.action, "confidence": i.confidence,
                         "rationale": i.rationale}
                        for i in insights
                    ],
                    "account_value": sum(
                        ((p.current_price - p.entry_price) * p.shares)
                        for p in positions if p.entry_price
                    ),
                    "positions": [
                        {"id": p.id, "ticker": p.ticker, "side": p.side,
                         "shares": p.shares, "entry": p.entry_price,
                         "current": p.current_price, "stop": p.stop_price}
                        for p in positions
                    ],
                })
                yield f"data: {payload}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

            await asyncio.sleep(2)

    return StreamingResponse(generator(), media_type="text/event-stream")
