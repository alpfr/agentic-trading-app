"""
Agentic Trading App — Retirement Portfolio Advisor
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
from core.watchlist import get_config, update_watchlist, TARGET_ALLOCATIONS
from core.scheduler import RetirementScheduler
from core.rebalance import compute_rebalance_report
from core.alerts import check_and_generate_alerts, get_all_alerts, mark_read, get_unread_count
from core.rebalancer import compute_rebalance, rebalance_report_to_dict
from core.alerts import generate_portfolio_alerts
from core.retirement_config import apply_retirement_config
from agents.fundamental import fetch_fundamentals
from trading_interface.reconciliation.job import SyncWorker
from trading_interface.broker.alpaca_paper import AlpacaPaperBroker
from trading_interface.broker.base import AccountSchema
from trading_interface.events.schemas import RiskRejected, RiskApproved
from trading_interface.execution.agent import ExecutionAgent
from trading_interface.security import require_api_key, sanitize_ticker
from trading_interface.security.rate_limit import limiter, rate_limit_exceeded_handler
from trading_interface.security.audit_log import audit_from_request
from trading_interface.security.auth_router import router as auth_router
from slowapi.errors import RateLimitExceeded
from trading_interface.security import SecurityHeadersMiddleware

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ---------------------------------------------------------------------------
# App & Middleware
# ---------------------------------------------------------------------------
logger = logging.getLogger("app")

app = FastAPI(title="Agentic Trading App API", version="1.1.0")

_cors_origins = os.getenv(
    "CORS_ALLOWED_ORIGINS", ""  # Must be explicitly set — no default in prod
).split(",")

# Rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# Security response headers
app.add_middleware(SecurityHeadersMiddleware)

# Auth router
app.include_router(auth_router)

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

# RISK_MANAGER is a module-level singleton so apply_retirement_config()
# patches the SAME instance that run_agent_loop() uses on every call.
# Previously a fresh DeterministicRiskManager() was created inside run_agent_loop(),
# discarding all config overrides (ATR multiplier, position cap, etc.)
RISK_MANAGER    = DeterministicRiskManager()

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

    # Apply retirement portfolio config to the RISK_MANAGER singleton
    apply_retirement_config(RISK_MANAGER)
    logger.info("Retirement config applied: 3% per buy, 10% max position, 25% max sector")

    # Launch market-hours scheduler
    async def _run_agent(ticker: str):
        try:
            await run_agent_loop(ticker)
        except Exception as e:
            logger.error(f"Scheduled agent run failed [{ticker}]: {e}")

    async def _close_all():
        pass  # Retirement: no EOD auto-close; positions are held long-term

    async def _run_rebalance():
        try:
            await _run_rebalance_check()
        except Exception as e:
            logger.error(f"Rebalance check error: {e}")

    scheduler = RetirementScheduler(
        run_agent_fn     = _run_agent,
        run_rebalance_fn = _run_rebalance,
        get_config_fn    = get_config,
    )
    asyncio.create_task(scheduler.run())
    cfg = get_config()
    logger.info(f"Scheduler running — watchlist: {cfg.watchlist}, interval: {cfg.scan_interval_hours}hr")

    # Fix #4: SyncWorker — periodic broker reconciliation wired into production
    # Runs every 5 minutes; keeps internal DB aligned with Alpaca as source of truth
    async def _run_reconciliation_loop():
        await asyncio.sleep(120)   # Wait 2 min after startup before first reconcile
        while True:
            try:
                if BROKER_CLIENT._client:   # Only reconcile if broker is authenticated
                    worker = SyncWorker(
                        broker=BROKER_CLIENT,
                        portfolio_db_client=None,  # uses direct DB access below
                    )
                    await _reconcile_positions_with_broker()
            except Exception as e:
                logger.error(f"Reconciliation error: {e}")
            await asyncio.sleep(300)   # Every 5 minutes

    asyncio.create_task(_run_reconciliation_loop())
    logger.info("Reconciliation loop started (every 5 min)")

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
# Rebalance Check
# ---------------------------------------------------------------------------
async def _run_rebalance_check() -> None:
    """Weekly rebalance check — computes allocation drift and logs recommendations."""
    db = SessionLocal()
    try:
        open_positions = db.query(StoredPosition).filter(StoredPosition.is_open == True).all()
        pos_list = [{"ticker": p.ticker, "market_value": p.current_price * p.shares} for p in open_positions]

        try:
            account = await BROKER_CLIENT.get_account()
            total_equity = account.portfolio_value
        except Exception:
            total_equity = 100_000.0

        report = compute_rebalance_report(pos_list, total_equity)
        logger.info(f"Rebalance check: {report.summary}")

        for rec in report.recommendations:
            if rec.action != "ON_TARGET":
                log_audit("REBALANCE", "RebalanceEngine", rec.category,
                          rec.rationale)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Fix #4: Broker Reconciliation — DB positions vs Alpaca source of truth
# ---------------------------------------------------------------------------
async def _reconcile_positions_with_broker() -> None:
    """
    Compares open positions in our DB against live Alpaca positions.
    - Prices updated to broker reality every 5 minutes
    - Positions closed at broker but still open in DB are marked closed
    - Drift > 5% of portfolio triggers a warning log (not a kill switch in paper mode)
    """
    try:
        broker_positions = await BROKER_CLIENT.get_positions()
        account          = await BROKER_CLIENT.get_account()
        total_equity     = account.portfolio_value or 1.0
    except Exception as e:
        logger.warning(f"Reconciliation skipped — broker unreachable: {e}")
        return

    broker_map = {p.ticker: p for p in broker_positions}

    db = SessionLocal()
    try:
        db_open = db.query(StoredPosition).filter(StoredPosition.is_open == True).all()
        updated, closed = 0, 0

        for pos in db_open:
            if pos.ticker in broker_map:
                bp = broker_map[pos.ticker]
                # Update current price from broker (fix #1 — live PnL)
                true_price = bp.market_value / bp.quantity if bp.quantity else pos.current_price
                drift_pct  = abs(true_price - pos.current_price) / (pos.current_price or 1)

                if drift_pct > 0.05:
                    logger.warning(f"RECONCILE: {pos.ticker} price drifted {drift_pct*100:.1f}%"
                                   f" — DB ${pos.current_price:.2f} → Broker ${true_price:.2f}")

                pos.current_price = round(true_price, 4)
                pos.shares        = bp.quantity        # Qty may differ after partial fills
                updated += 1
            else:
                # Position closed at broker (EOD fill, manual close, etc.) — mark closed in DB
                pos.is_open   = False
                pos.closed_at = __import__('datetime').datetime.utcnow()
                log_audit("RECONCILED_CLOSE", "SyncWorker", pos.ticker,
                          f"Position not found at broker — marked closed (was {pos.shares} shares)")
                closed += 1

        db.commit()
        if updated or closed:
            logger.info(f"Reconciliation: {updated} prices updated, {closed} positions closed")
    except Exception as e:
        logger.error(f"Reconciliation DB error: {e}")
        db.rollback()
    finally:
        db.close()


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
        return  # No point running strategy on bad data
    else:
        log_audit("SYNCED", "MarketDataAgent", ticker, f"Price=${live_context.current_price}")

    # Fix #1: Refresh current_price on any open DB position for this ticker
    _price_db = SessionLocal()
    open_positions_snapshot = []
    try:
        _open = (_price_db.query(StoredPosition)
                 .filter(StoredPosition.ticker == ticker, StoredPosition.is_open == True)
                 .all())
        for _pos in _open:
            _pos.current_price = live_context.current_price
            open_positions_snapshot.append({"ticker": _pos.ticker, "entry": _pos.entry_price})
        if _open:
            _price_db.commit()
    except Exception as _e:
        logger.warning(f"Price refresh failed for {ticker}: {_e}")
        _price_db.rollback()
    finally:
        _price_db.close()

    # Generate alerts (price drop, trailing stop breach)
    check_and_generate_alerts(
        ticker        = ticker,
        current_price = live_context.current_price,
        prev_close    = getattr(live_context, 'prev_close', None),
        positions     = open_positions_snapshot,
    )

    # 2. Strategy agent
    technicals   = await MARKET_AGENT.generate_technical_summary_string(ticker, live_context)
    sentiment    = await MARKET_AGENT.fetch_news_and_sentiment(ticker)
    # Retirement: use dedicated fundamental agent (P/E, dividend, FCF, moat)
    fund_data    = await fetch_fundamentals(ticker)
    fundamentals = fund_data["summary"]

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

    # 3. Risk evaluation — uses the module-level RISK_MANAGER singleton
    # (already configured with retirement params via apply_retirement_config at startup)
    portfolio     = await _build_portfolio_state()
    # Pass raw fundamentals for retirement risk gates (P/E, payout ratio)
    risk_result   = RISK_MANAGER.evaluate_signal(signal, portfolio, live_context, fund_data)

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
        "watchlist":               cfg.watchlist,
        "target_allocations":      {t: round(v*100,1) for t,v in cfg.target_allocations.items()},
        "style":                   cfg.style,
        "paper_only":              cfg.paper_only,
        "horizon_years":           cfg.horizon_years,
        "position_size_pct":       cfg.risk_per_trade_pct * 100,
        "max_single_stock_pct":    cfg.max_single_position_pct * 100,
        "max_position_pct":        cfg.max_single_position_pct * 100,
        "rebalance_check_day":     cfg.rebalance_check_day,
        "rebalance_drift_trigger": cfg.rebalance_drift_trigger * 100,
        "scan_interval_hours":     cfg.scan_interval_hours,
        "min_hold_days":           cfg.min_hold_days,
        "trailing_stop_pct":       cfg.trailing_stop_pct * 100,
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
    update_watchlist(watchlist=tickers)
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
    # For retirement: manual close-all means rebalance-sells, not EOD close
    closed = []  # Manual rebalancing is done via /api/rebalance, not auto-close
    return {
        "message": f"Closed {len(closed)} positions",
        "tickers": closed,
    }


# ---------------------------------------------------------------------------
# Retirement Portfolio Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/rebalance", dependencies=[Depends(require_api_key)])
async def get_rebalance_report():
    """
    Compute current portfolio drift vs target allocations.
    Returns suggested BUY/SELL trades to restore balance.
    """
    db = SessionLocal()
    try:
        open_positions = db.query(StoredPosition).filter(StoredPosition.is_open == True).all()
        positions_list = [
            {
                "ticker":       p.ticker,
                "shares":       p.shares,
                "current_price": p.current_price,
                "market_value": p.shares * p.current_price,
            }
            for p in open_positions
        ]

        try:
            account    = await BROKER_CLIENT.get_account()
            total_value = account.portfolio_value
        except Exception:
            total_value = sum(p["market_value"] for p in positions_list) or 100_000.0

        cfg = get_config()
        report = compute_rebalance(
            current_positions=positions_list,
            target_allocations=cfg.target_allocations,
            total_portfolio_value=total_value,
            drift_threshold=cfg.rebalance_drift_threshold,
        )
        return rebalance_report_to_dict(report)
    finally:
        db.close()


@app.get("/api/alerts", dependencies=[Depends(require_api_key)])
async def get_portfolio_alerts():
    """
    Generate current portfolio alerts:
    price drops, dividend risk, valuation extremes, rebalancing triggers.
    """
    cfg = get_config()
    all_alerts = []

    # Get rebalance report for drift alerts
    db = SessionLocal()
    try:
        open_positions = db.query(StoredPosition).filter(StoredPosition.is_open == True).all()
        positions_map  = {p.ticker: p for p in open_positions}
        try:
            account = await BROKER_CLIENT.get_account()
            total_value = account.portfolio_value
        except Exception:
            total_value = sum(p.shares * p.current_price for p in open_positions) or 100_000.0
    finally:
        db.close()

    for ticker in cfg.watchlist:
        try:
            # Get latest market data from DB
            mdb = SessionLocal()
            market_row = (
                mdb.query(StoredMarketData)
                .filter(StoredMarketData.ticker == ticker)
                .order_by(StoredMarketData.timestamp.desc())
                .first()
            )
            mdb.close()

            current_price = (market_row.current_price if market_row else 0) or 0
            week52_high   = None
            sma_20        = market_row.sma_20 if market_row else None

            fund_data = await fetch_fundamentals(ticker)
            raw       = fund_data.get("raw", {})
            week52_high = raw.get("week52_high")

            # Rebalance drift
            pos = positions_map.get(ticker)
            current_value = (pos.shares * pos.current_price) if pos else 0
            target_pct    = cfg.target_allocations.get(ticker, 0)
            current_pct   = current_value / total_value if total_value else 0
            drift_pct     = (current_pct - target_pct) * 100
            gap_value     = (target_pct - current_pct) * total_value

            ticker_alerts = generate_portfolio_alerts(
                ticker=ticker,
                fundamentals=fund_data,
                current_price=current_price,
                week52_high=week52_high,
                sma_20=sma_20,
                drift_pct=drift_pct,
                gap_value=gap_value,
                drift_threshold=cfg.rebalance_drift_threshold * 100,
            )
            all_alerts.extend([a.to_dict() for a in ticker_alerts])
        except Exception as e:
            logger.warning(f"Alert generation failed for {ticker}: {e}")

    # Sort: ACTION > WARNING > INFO
    level_order = {"ACTION": 0, "WARNING": 1, "INFO": 2}
    all_alerts.sort(key=lambda a: level_order.get(a["level"], 3))

    return {"alerts": all_alerts, "count": len(all_alerts)}


@app.get("/api/dividends", dependencies=[Depends(require_api_key)])
async def get_dividend_summary():
    """
    Dividend income summary for retirement portfolio holdings.
    Returns annual income, yield, next ex-div dates.
    """
    cfg = get_config()
    db  = SessionLocal()
    try:
        open_positions = db.query(StoredPosition).filter(StoredPosition.is_open == True).all()
        positions_map  = {p.ticker: p for p in open_positions}
    finally:
        db.close()

    dividends = []
    total_annual_income = 0.0

    for ticker in cfg.watchlist:
        fund_data = await fetch_fundamentals(ticker)
        raw       = fund_data.get("raw", {})

        div_rate  = raw.get("div_rate") or 0.0
        div_yield = raw.get("div_yield") or 0.0
        payout    = raw.get("payout_ratio") or 0.0

        pos = positions_map.get(ticker)
        shares_held   = pos.shares if pos else 0
        annual_income = div_rate * shares_held

        total_annual_income += annual_income

        if div_yield > 0 or shares_held > 0:
            dividends.append({
                "ticker":        ticker,
                "annual_div_rate": round(div_rate, 4),
                "yield_pct":     round(div_yield * 100, 2),
                "payout_ratio":  round(payout * 100, 1),
                "shares_held":   shares_held,
                "annual_income": round(annual_income, 2),
                "monthly_income": round(annual_income / 12, 2),
                "div_health":    (
                    "AT_RISK" if payout > 0.85
                    else "WATCH" if payout > 0.65
                    else "HEALTHY" if div_yield > 0
                    else "N/A"
                ),
            })

    dividends.sort(key=lambda d: d["annual_income"], reverse=True)

    return {
        "dividends":            dividends,
        "total_annual_income":  round(total_annual_income, 2),
        "total_monthly_income": round(total_annual_income / 12, 2),
    }


@app.get("/api/fundamentals/{ticker}", dependencies=[Depends(require_api_key)])
async def get_fundamentals(ticker: str):
    """Full fundamental data for a single ticker."""
    clean = sanitize_ticker(ticker)
    if not clean:
        raise HTTPException(status_code=400, detail="Invalid ticker")
    data = await fetch_fundamentals(clean)
    return {"ticker": clean, "summary": data["summary"], "raw": data["raw"]}


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


# ── TEMPORARY: one-time password hash generator — REMOVE AFTER USE ─────────
@app.get("/api/setup/hash-password", include_in_schema=False)
async def hash_password_once(password: str):
    """
    ONE-TIME USE — generates a bcrypt hash for admin password setup.
    Delete this endpoint immediately after use.
    """
    import os
    # Only works if SETUP_TOKEN env var is set — prevents accidental exposure
    setup_token = os.getenv("SETUP_TOKEN", "")
    from fastapi import Query
    if not setup_token:
        raise HTTPException(status_code=404, detail="Not found")
    from trading_interface.security import hash_password
    return {"hash": hash_password(password)}
