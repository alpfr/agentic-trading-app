# 🤖 Agentic Trading App

A full-stack, cloud-native agentic trading platform built on **FastAPI**, **React**, and **AWS EKS**. An LLM-powered Strategy Agent proposes trades, a deterministic Risk Gatekeeper enforces hard mathematical constraints, and an Execution Agent routes approved orders to Alpaca's paper trading API.

> ⚠️ **NOT FINANCIAL ADVICE.** Paper trading only. For educational and research purposes.

---

## Live Deployment

| | |
|---|---|
| **Cluster** | `agentic-trading-cluster` (AWS EKS, us-east-1) |
| **Namespace** | `agentic-trading-platform` |
| **Get URL** | Run the **Get App URL** GitHub Actions workflow |

To get your live app URL at any time:
1. Go to `Actions → Get App URL → Run workflow`
2. Open the run summary — URL is printed there

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  React Frontend (Vite)                      │
│   ⭐ Watchlist · Dashboard · Market Movers · Quote · Audit  │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP + SSE  (X-API-Key)
┌──────────────────────────▼──────────────────────────────────┐
│                  FastAPI Backend (Python)                    │
│                                                             │
│  MarketScheduler ──► MarketDataAgent ──► StrategyAgent      │
│  (20min / ticker)              (LLM signal)                 │
│                                        │                    │
│                           DeterministicRiskManager          │
│                           (hard math gates — no LLM bypass) │
│                                        │                    │
│                              ExecutionAgent                 │
│                              AlpacaPaperBroker              │
└──────────────┬──────────────────────────────────────────────┘
               │
     ┌─────────▼──────────┐
     │  SQLite (dev)       │
     │  PostgreSQL (prod)  │
     └────────────────────┘
```

### Agent Pipeline

| Stage | Agent | Description |
|---|---|---|
| 1 | **MarketScheduler** | Triggers agent loops every 20 min per ticker, Mon–Fri 09:35–15:40 ET |
| 2 | **MarketDataAgent** | Fetches price, ATR-14, SMA-20/50, VIX, real earnings dates (yfinance) |
| 3 | **StrategyAgent** | GPT-4o-mini signal: BUY / SELL / HOLD with rationale |
| 4 | **DeterministicRiskManager** | 8 hard gates — LLM cannot bypass |
| 5 | **ExecutionAgent** | Routes `RiskApproved` → broker with exponential backoff |
| 6 | **SyncWorker** | Periodic reconciliation — broker is always source of truth |
| 7 | **EOD Sweep** | Auto-closes all positions at 15:45 ET (day trading mode) |

---

## Watchlist & Day Trading Config

Default watchlist: **AAOI, BWIN, DELL, FIGS, SSL**

| Config | Value | Description |
|---|---|---|
| Style | `day_trading` | In/out same session |
| Risk profile | `conservative` | Tight stops, small size |
| Risk per trade | **1%** of equity | Max $ at risk per entry |
| ATR stop | **1×** ATR-14 | Tighter than swing (2×) |
| Max position | **3%** of equity | Per-ticker cap |
| Max open | **3** positions | Concurrent limit |
| Scan interval | **20 min** | Per-ticker during market hours |
| EOD close | **15:45 ET** | All positions auto-closed daily |

---

## Risk Constraints (Hardcoded — LLM Cannot Override)

| Constraint | Value |
|---|---|
| Max account drawdown (HWM) | 10% |
| Daily loss circuit breaker | 3% |
| Max single position size | 3% equity (day trading) / 5% default |
| Max sector exposure | 20% equity |
| Min average daily volume | 5,000,000 shares |
| Max VIX for new longs | 35.0 (defaults to 99.0 on fetch failure) |
| Earnings blackout window | 3 days |
| ATR stop multiplier | 1× (day trading) / 2× (swing) |

---

## Quick Start (Local Development)

### Backend
```bash
cd backend
cp .env.example .env        # Fill in your keys
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

### Frontend
```bash
cd frontend
cp .env.example .env        # Set VITE_API_BASE_URL + VITE_API_KEY
npm install
npm run dev                 # http://localhost:5173
```

---

## API Reference

All endpoints require `X-API-Key` header (or `?api_key=` for SSE).

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Liveness/readiness probe |
| `GET` | `/api/watchlist` | Current watchlist + trading config |
| `PUT` | `/api/watchlist` | Update watchlist tickers |
| `POST` | `/api/watchlist/scan` | Scan all watchlist tickers now |
| `POST` | `/api/watchlist/close-all` | Close all open positions (manual EOD) |
| `POST` | `/api/trigger` | Trigger agent loop for one ticker |
| `GET` | `/api/stream` | SSE — real-time logs, insights, positions |
| `GET` | `/api/portfolio` | Open positions + account value |
| `GET` | `/api/quote/{ticker}` | Quote + fundamentals |
| `GET` | `/api/movers` | Top gainers, losers, most active |
| `GET` | `/api/logs` | Last 20 audit entries |
| `GET` | `/api/insights` | Last 20 AI strategy insights |
| `GET` | `/api/market-data` | Stored market snapshots |
| `DELETE` | `/api/market-data` | Clear market data records |

---

## Project Structure

```
agentic-trading-app/
├── .github/
│   └── workflows/
│       ├── deploy.yml          # CI/CD: lint → build → provision EKS → deploy
│       ├── get-app-url.yml     # Manual: prints live ALB URL
│       └── destroy.yml         # Manual: tear down all infrastructure
├── backend/
│   ├── agents/
│   │   ├── market_data.py      # yfinance data + earnings calendar (module-level cache)
│   │   ├── movers.py           # Gainers/losers: yf.screen() + watchlist fallback
│   │   ├── strategy.py         # LLM client + StrategyAgent
│   │   └── prompts.py          # System & user prompt templates
│   ├── core/
│   │   ├── database.py         # SQLAlchemy models
│   │   ├── day_trading.py      # Day trading risk overrides + EOD close
│   │   ├── portfolio_state.py  # PortfolioState + MarketContext (Pydantic)
│   │   ├── risk_gatekeeper.py  # DeterministicRiskManager (configurable ATR/pos)
│   │   ├── scheduler.py        # MarketScheduler (20min scan, EOD sweep)
│   │   └── watchlist.py        # TradingConfig + watchlist singleton
│   ├── trading_interface/
│   │   ├── broker/             # AbstractBrokerAPI + AlpacaPaperBroker
│   │   ├── events/schemas.py   # Pydantic event schemas
│   │   ├── execution/agent.py  # ExecutionAgent + exponential backoff
│   │   ├── reconciliation/     # SyncWorker (broker = source of truth)
│   │   └── security/           # API key auth + ticker sanitization
│   ├── app.py                  # FastAPI app + all endpoints + startup scheduler
│   ├── main.py                 # Standalone lifecycle demo
│   ├── .env.example
│   └── requirements.txt
├── frontend/
│   └── src/
│       └── App.jsx             # React UI (Watchlist, Dashboard, Movers, Quote, Audit)
├── k8s-deploy.yaml             # EKS manifests (secrets, resource limits, probes)
├── deploy.sh                   # One-shot local deployment script
├── README.md
├── ARCHITECTURE.md
├── DEPLOYMENT.md
├── AGENTIC_TRADING_SPEC.md
├── ALPACA_INTEGRATION.md
├── SOC2_COMPLIANCE.md
└── TRADING_INTERFACE_SPEC.md
```

---

## GitHub Actions Workflows

| Workflow | Trigger | What it does |
|---|---|---|
| `deploy.yml` | Push to `master` | Lint → ECR build/push → EKS provision → rolling deploy |
| `get-app-url.yml` | Manual | Prints live ALB URL + pod status |
| `destroy.yml` | Manual (`DESTROY`) | Tears down cluster + all AWS resources |

---

## Environment Variables

### Backend (`backend/.env`)

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | No | GPT-4o-mini. Omit for deterministic mock LLM |
| `ALPACA_API_KEY` | No | Alpaca paper account key |
| `ALPACA_SECRET_KEY` | No | Alpaca paper account secret |
| `APP_API_KEY` | **Yes (prod)** | `X-API-Key` header secret. Generate: `openssl rand -hex 32` |
| `DATABASE_URL` | No | Defaults to SQLite. Set PostgreSQL URL for production |
| `CORS_ALLOWED_ORIGINS` | No | Comma-separated allowed frontend origins |

### Frontend (`frontend/.env`)

| Variable | Description |
|---|---|
| `VITE_API_BASE_URL` | Backend URL (e.g. `http://your-alb.elb.amazonaws.com`) |
| `VITE_API_KEY` | Must match backend `APP_API_KEY` |

---

## Security

- All API endpoints protected by `X-API-Key` authentication
- All credentials stored in Kubernetes Secrets — never in YAML or source control
- AWS Account ID never committed — injected at deploy time via `envsubst`
- Ticker inputs validated against `^[A-Z]{1,5}$` regex
- `/api/trigger` rate-limited (10s cooldown per ticker)
- Paper broker URL hardcoded — live mode requires explicit code change
- ECR image scanning enabled on push

---

## Docs

- [Architecture Deep Dive](ARCHITECTURE.md)
- [Deployment Guide](DEPLOYMENT.md)
- [Agentic Trading Spec](AGENTIC_TRADING_SPEC.md)
- [Alpaca Integration](ALPACA_INTEGRATION.md)
- [Trading Interface Spec](TRADING_INTERFACE_SPEC.md)
- [SOC2 Compliance Notes](SOC2_COMPLIANCE.md)
