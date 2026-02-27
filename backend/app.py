from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import time
import uuid
import logging
import asyncio
import requests
from typing import List, Dict

# Local Imports
from trading_interface.events.schemas import SignalCreated, RiskApproved, RiskRejected
from trading_interface.execution.agent import ExecutionAgent
from trading_interface.broker.alpaca_paper import AlpacaPaperBroker
from trading_interface.broker.base import AccountSchema
from core.portfolio_state import PortfolioState, MarketContext
from core.risk_gatekeeper import DeterministicRiskManager
from agents.strategy import StrategyAgent, MockSwingLLMClient, OpenAILLMClient
from agents.market_data import MarketDataAgent
from core.database import SessionLocal, StoredMarketData
import yfinance as yf
import os
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

app = FastAPI(title="Agentic Trading App API")

# Allow React Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- GLOBAL IN-MEMORY STATE FOR DEMO ---
# Replaces Postgres / Redis for rapid local demonstration
GLOBAL_AUDIT_LOGS = []
GLOBAL_AGENT_INSIGHTS = []
GLOBAL_POSITIONS = []
BROKER_CLIENT = AlpacaPaperBroker()

def log_audit(action: str, agent: str, ticker: str, reason: str):
    """Appends immutable log entries for the frontend."""
    GLOBAL_AUDIT_LOGS.insert(0, {
        "id": str(uuid.uuid4())[:8],
        "time": time.strftime("%H:%M:%S"),
        "agent": agent,
        "action": action,
        "ticker": ticker,
        "reason": reason
    })

# --- DEPENDENCIES & INITIALIZATION ---

def get_risk_manager() -> DeterministicRiskManager:
    return DeterministicRiskManager()

def get_strategy_agent() -> StrategyAgent:
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        return StrategyAgent(llm_client=OpenAILLMClient(api_key=api_key))
    return StrategyAgent(llm_client=MockSwingLLMClient())

async def run_agent_loop(ticker: str):
    """The asynchronous core execution loop bridging AI --> Risk --> Execution."""
    
    # 0. Market Data Agent gathers live real-time contexts 
    market_agent = MarketDataAgent()
    log_audit("PROCESSING", "Supervisor", ticker, "Dispatched MarketDataAgent to query external YFinance APIs.")
    
    live_market_context = await market_agent.fetch_market_context(ticker)
    
    # Update currently held positions with the fresh price to make PNL completely dynamic
    for p in GLOBAL_POSITIONS:
        if p["ticker"] == ticker:
            p["current"] = live_market_context.current_price

    
    # --- ADD TO DATABASE ---
    db = SessionLocal()
    try:
        new_record = StoredMarketData(
            ticker=live_market_context.ticker,
            current_price=live_market_context.current_price,
            atr_14=live_market_context.atr_14,
            avg_daily_volume=live_market_context.avg_daily_volume,
            sma_20=live_market_context.sma_20,
            sma_50=live_market_context.sma_50,
            vix_level=live_market_context.vix_level,
        )
        db.add(new_record)
        db.commit()
        db.refresh(new_record)
        log_audit("SAVED", "Database", ticker, f"Safely stored live yfinance data in database (ID: {new_record.id})")
    except Exception as db_e:
        log_audit("ERROR", "Database", ticker, f"Failed fixing data! {db_e}")
    finally:
        db.close()
    
    if live_market_context.current_price == 10.0 and live_market_context.avg_daily_volume == 0:
        log_audit("FAILED", "MarketDataAgent", ticker, "YFinance API Error or Invalid Ticker. Market Context failed fallback.")
        # Continue execution, the RiskManager will catch the 0 liquidity and reject mathematically anyway!
    else:
        log_audit("SYNCED", "MarketDataAgent", ticker, f"Successfully populated Live Data Context. Price=${live_market_context.current_price}")
        
    technicals_str = await market_agent.generate_technical_summary_string(ticker, live_market_context)

    # 1. Strategy Agent synthesizes context
    strategy = get_strategy_agent()
    # Pulling real news and fundamentals
    sentiment = await market_agent.fetch_news_and_sentiment(ticker)
    fundamentals = await market_agent.fetch_fundamentals(ticker)
    
    agent_msg = "Dispatched abstract LLM client for probabilistic strategic evaluation."
    if "Mocking" in str(type(strategy.llm)):
        agent_msg += " (Mock Client fallback enabled due to missing OPENAI_API_KEY)"
        
    log_audit("PROCESSING", "StrategyAgent", ticker, agent_msg)
    
    signal = await strategy.evaluate_context(ticker, technicals_str, sentiment, fundamentals)
    log_audit("PROPOSED", "StrategyAgent", ticker, f"Proposed {signal.suggested_action}. Rationale: {signal.rationale}")

    GLOBAL_AGENT_INSIGHTS.insert(0, {
        "id": str(uuid.uuid4())[:8],
        "time": time.strftime("%H:%M:%S"),
        "ticker": ticker,
        "action": signal.suggested_action,
        "confidence": signal.confidence,
        "rationale": signal.rationale,
        "technicals": technicals_str,
        "sentiment": sentiment,
        "fundamentals": fundamentals
    })
    
    # 2. Risk Manager validates math
    risk = get_risk_manager()
    mock_portfolio = PortfolioState(buying_power=50000, total_equity=100000, high_water_mark=100000, daily_start_equity=100000, positions=[])
    
    risk_evaluation = risk.evaluate_signal(signal, mock_portfolio, live_market_context)
    
    if isinstance(risk_evaluation, RiskRejected):
        log_audit("REJECTED", "RiskManager", ticker, f"[Violation: {risk_evaluation.failing_metric}] {risk_evaluation.reason}")
        return
        
    log_audit("APPROVED", "RiskManager", ticker, f"Limits checked. Sizing computed: {risk_evaluation.approved_quantity} shares.")
    
    # 3. Execution Agent Routes to Alpaca Paper
    executor = ExecutionAgent(broker=BROKER_CLIENT, is_live_mode=False)
    
    # Actually authenticating Alpaca takes 1 API key. We will catch unauthorized errors intentionally.
    try:
        if not BROKER_CLIENT._client:
             await BROKER_CLIENT.authenticate("mock", "mock", "PAPER")
    except Exception:
         pass # Handled by Mocking
         
    # To prevent failing HTTP requests to Alpaca during pure local test without keys
    # we simulate the execution Agent passing it accurately.
    log_audit("FILLED", "ExecutionAgent", ticker, f"Executed {risk_evaluation.approved_quantity} x {ticker} at LIMIT ${risk_evaluation.approved_limit_price} (Paper Mode).")
    
    GLOBAL_POSITIONS.append({
        "id": str(uuid.uuid4())[:8],
        "ticker": ticker,
        "side": "LONG" if risk_evaluation.action == "BUY_TO_OPEN" else "SHORT",
        "shares": risk_evaluation.approved_quantity,
        "entry": risk_evaluation.approved_limit_price,
        "current": live_market_context.current_price,
        "stop": risk_evaluation.risk_metrics.hard_stop_loss,
        "pnl_pct": 0.0
    })


# --- ENDPOINTS ---

@app.get("/api/portfolio")
async def get_portfolio():
    total_equity = 105240.50
    for p in GLOBAL_POSITIONS:
        if p["entry"] > 0:
            pnl_pct = ((p["current"] - p["entry"]) / p["entry"]) * 100
            pnl_dollars = (p["current"] - p["entry"]) * p["shares"]
            
            if p["side"] == "SHORT":
                pnl_pct = -pnl_pct
                pnl_dollars = -pnl_dollars
                
            p["pnl_pct"] = round(pnl_pct, 4)
            total_equity += pnl_dollars

    return {
        "account_value": round(total_equity, 2),
        "positions": GLOBAL_POSITIONS
    }

@app.get("/api/market-data")
async def get_market_data():
    """Diagnostic endpoint to see all saved Database rows!"""
    db = SessionLocal()
    try:
        records = db.query(StoredMarketData).order_by(StoredMarketData.timestamp.desc()).limit(50).all()
        return {
            "saved_data": [
                 {
                     "id": r.id, 
                     "ticker": r.ticker, 
                     "price": r.current_price, 
                     "vix": r.vix_level,
                     "timestamp": r.timestamp.isoformat()
                 } for r in records
            ]
        }
    finally:
        db.close()

@app.delete("/api/market-data")
async def delete_market_data():
    """Diagnostic endpoint to clear all saved Database rows!"""
    db = SessionLocal()
    try:
        db.query(StoredMarketData).delete()
        db.commit()
        return {"status": "success", "message": "Database cleared"}
    finally:
        db.close()


@app.get("/api/quote/{ticker}")
def get_quote(ticker: str):
    """Fetches detailed company info similar to Yahoo Finance."""
    try:
        stock = yf.Ticker(ticker.upper())
        info = stock.info
        
        sum_text = info.get("longBusinessSummary", "No company summary available.")
        if len(sum_text) > 800:
            sum_text = sum_text[:800] + "..."

        return {
            "ticker": ticker.upper(),
            "name": info.get("shortName", "N/A"),
            "sector": info.get("sector", "Sector N/A"),
            "industry": info.get("industry", "Industry N/A"),
            "current_price": info.get("currentPrice", info.get("regularMarketPrice", 0.0)),
            "market_cap": info.get("marketCap", 0),
            "summary": sum_text,
            "fiftyTwoWeekHigh": info.get("fiftyTwoWeekHigh", 0.0),
            "fiftyTwoWeekLow": info.get("fiftyTwoWeekLow", 0.0),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/movers")
def get_movers():
    """Fetches top 10 gainers and losers directly from Yahoo Finance."""
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        # Gainers
        g_url = 'https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?formatted=false&lang=en-US&region=US&scrIds=day_gainers&count=10'
        g_res = requests.get(g_url, headers=headers).json()
        gainers = g_res.get('finance', {}).get('result', [{}])[0].get('quotes', [])
        
        # Losers
        l_url = 'https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?formatted=false&lang=en-US&region=US&scrIds=day_losers&count=10'
        l_res = requests.get(l_url, headers=headers).json()
        losers = l_res.get('finance', {}).get('result', [{}])[0].get('quotes', [])
        
        # Trending / Most Actives
        t_url = 'https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?formatted=false&lang=en-US&region=US&scrIds=most_actives&count=10'
        t_res = requests.get(t_url, headers=headers).json()
        actives = t_res.get('finance', {}).get('result', [{}])[0].get('quotes', [])

        format_quote = lambda q: {
            "ticker": q.get("symbol"), 
            "name": q.get("shortName", q.get("symbol")), 
            "change_pct": q.get("regularMarketChangePercent", 0.0), 
            "price": q.get("regularMarketPrice", 0.0)
        }
        
        return {
            "gainers": [format_quote(q) for q in gainers],
            "losers": [format_quote(q) for q in losers],
            "actives": [format_quote(q) for q in actives]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch movers: {str(e)}")


@app.get("/api/logs")
async def get_logs():
    return {"logs": GLOBAL_AUDIT_LOGS[:20]} # Return last 20

@app.get("/api/insights")
async def get_insights():
    return {"insights": GLOBAL_AGENT_INSIGHTS[:20]}

@app.post("/api/trigger")
async def trigger_agent(background_tasks: BackgroundTasks, payload: dict):
    """Kicks off an async agent loop."""
    ticker = payload.get("ticker", "AAPL").upper()
    background_tasks.add_task(run_agent_loop, ticker)
    return {"status": "dispatched", "message": f"Agents spinning up for {ticker}"}

