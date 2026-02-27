# Agentic Trading App Architecture

The Agentic Trading Application is designed following a modular, multi-agent architecture where strictly defined sub-agents perform quantitative lookups, generate probabilistic trading signals via LLM, and execute orders through a deterministically protected risk management layer.

## System Components

### 1. Frontend (React / Vite)

- The user interface is composed of a Single Page Application (SPA) built with React and bundled via Vite.
- Connects asynchronously to the Python backend to poll for `PortfolioPosition`, `AuditLog`, and `AgentInsight` database models.
- **Key Features:**
  - Real-time Portfolio Dashboard with interactive PnL tables.
  - "Market Movers" interface parsing live Yahoo Finance metrics.
  - Interactive Quote Lookups featuring embedded AdvancedRealTimeCharts (TradingView).
  - AI Insights Dashboard rendering exactly what fundamental, technical, and news-based context the Strategy Agent reasoned across.

### 2. Backend API (FastAPI)

- Handles all asynchronous orchestrations.
- Exposes RESTful endpoints (`/api/portfolio`, `/api/trigger`, `/api/insights`, `/api/movers`, `/api/quote/{ticker}`).
- Governs the Multi-Agent Execution Loop via Background Tasks.

### 3. Sub-Agents

#### Market Data Agent (`agents/market_data.py`)

- Acts as the system's "Sensors".
- Fetches deterministic numbers using `yfinance` to bypass expensive API requirements during prototyping.
- Performs localized mathematical aggregation (e.g. Rolling 14-day Average True Range (ATR), 20SMA / 50SMA crossovers).
- Scrapes the latest News Headlines and key Valuation Metrics (Trailing P/E, Margins) to structure for the LLM.

#### Strategy Agent (`agents/strategy.py`)

- Acts as the system's "Brain".
- Combines the raw numerical arrays, narrative news strings, and fundamental strings from the Market Data Agent into a singular synthesized prompt.
- Routes the prompt to either a mock logic gate (if API keys are missing) or an upstream OpenAI (`gpt-4o-mini`) inference model.
- Strictly parses the inference output ensuring the AI returns a cleanly structured JSON response defining Confidence, Action (BUY/SELL/HOLD), and a strict two-sentence Rationale.

#### Execution Agent (`trading_interface/execution/agent.py`)

- Acts as the system's "Hands".
- Directly interfaces with the broker (Alpaca Paper API).
- Responsible for limit order structuring, authentication, and execution verifications.

### 4. Deterministic Risk Gatekeeper (`core/risk_gatekeeper.py`)

- The critical protective layer. LLMs are strictly excluded from executing trades on their own.
- The Risk Gatekeeper catches the proposed `SignalCreated` JSON from the Strategy Agent and evaluates it against mathematical boundaries:
  - Is the VIX too high?
  - Does the asset have sufficient average daily volume (Liquidity rules)?
  - Is the portfolio exceeding its max sector correlation limits?
- If the risk manager flags the trade, the execution halts instantly. If approved, the Gatekeeper accurately sizes the trade based on portfolio VaR bounds and forwards a `RiskApproved` event to the Execution Agent.

## Persistence

- Stores active agent workflows and historical Market Context parameters via `SQLite3` + `SQLAlchemy` ORM natively.
