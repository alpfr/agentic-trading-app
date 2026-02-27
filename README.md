# 🤖 Agentic Trading App

A full-stack, cloud-native agentic trading platform built on **FastAPI**, **React**, and **Kubernetes**. An LLM-powered Strategy Agent proposes trades, a deterministic Risk Manager gatekeeps every signal with hard mathematical constraints, and an Execution Agent routes approved orders to Alpaca's paper trading API.

> ⚠️ **NOT FINANCIAL ADVICE.** This application is for educational and research purposes only. Do not use with real capital without extensive professional review.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    React Frontend (Vite)                     │
│         SSE stream · Quote Lookup · Audit Journal           │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP + SSE (X-API-Key auth)
┌──────────────────────────▼──────────────────────────────────┐
│                  FastAPI Backend (Python)                    │
│                                                             │
│  MarketDataAgent → StrategyAgent (LLM) → RiskManager        │
│                                        → ExecutionAgent     │
│                                        → AlpacaPaperBroker  │
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
| 1 | **MarketDataAgent** | Fetches live price, ATR, SMA, VIX, earnings dates via yfinance |
| 2 | **StrategyAgent** | Feeds context to OpenAI GPT-4o-mini (or mock LLM) for BUY/SELL/HOLD signal |
| 3 | **DeterministicRiskManager** | Hard mathematical gates — LLM cannot bypass these |
| 4 | **ExecutionAgent** | Routes `RiskApproved` events to broker with exponential backoff |
| 5 | **SyncWorker** | Periodic reconciliation — broker is always source of truth |

---

## Risk Constraints (Hardcoded — LLM Cannot Override)

| Constraint | Value |
|---|---|
| Max account drawdown (HWM) | 10% |
| Daily loss circuit breaker | 3% |
| Max single position size | 5% equity |
| Max sector exposure | 20% equity |
| Min average daily volume | 5,000,000 shares |
| Max VIX for new longs | 35.0 |
| Earnings blackout window | 3 days |
| Risk per trade | 1% equity |

---

## Quick Start (Local Development)

### Prerequisites
- Python 3.11+
- Node.js 18+
- (Optional) OpenAI API key
- (Optional) Alpaca paper trading account

### Backend

```bash
cd backend
cp .env.example .env
# Edit .env — add OPENAI_API_KEY if you have one (mock LLM used otherwise)

pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

### Frontend

```bash
cd frontend
cp .env.example .env
# Edit .env — set VITE_API_BASE_URL=http://127.0.0.1:8000

npm install
npm run dev
```

Visit `http://localhost:5173`

---

## Environment Variables

### Backend (`backend/.env`)

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | No | GPT-4o-mini key. Omit to use deterministic mock LLM |
| `ALPACA_API_KEY` | No | Alpaca paper account key |
| `ALPACA_SECRET_KEY` | No | Alpaca paper account secret |
| `APP_API_KEY` | **Yes (prod)** | Random secret for `X-API-Key` header auth |
| `DATABASE_URL` | No | Defaults to SQLite. Set PostgreSQL URL for production |
| `CORS_ALLOWED_ORIGINS` | No | Comma-separated allowed frontend origins |

Generate a secure `APP_API_KEY`:
```bash
openssl rand -hex 32
```

### Frontend (`frontend/.env`)

| Variable | Description |
|---|---|
| `VITE_API_BASE_URL` | Backend URL (e.g. `http://127.0.0.1:8000`) |
| `VITE_API_KEY` | Must match backend `APP_API_KEY` |

---

## API Endpoints

All endpoints require `X-API-Key` header (or `?api_key=` query param for SSE).

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | K8s liveness/readiness probe |
| `POST` | `/api/trigger` | Kick off agent loop for a ticker |
| `GET` | `/api/stream` | SSE stream — real-time logs, insights, positions |
| `GET` | `/api/portfolio` | Current open positions + account value |
| `GET` | `/api/quote/{ticker}` | Company info and fundamentals |
| `GET` | `/api/movers` | Top gainers, losers, most active |
| `GET` | `/api/logs` | Last 20 audit log entries |
| `GET` | `/api/insights` | Last 20 AI strategy insights |
| `GET` | `/api/market-data` | Stored market data snapshots |
| `DELETE` | `/api/market-data` | Clear market data records |

---

## Kubernetes Deployment (AWS EKS)

### 1. Create Secrets

```bash
kubectl create secret generic trading-app-secrets \
  --from-literal=openai-api-key="sk-..." \
  --from-literal=alpaca-api-key="PK..." \
  --from-literal=alpaca-secret-key="..." \
  --from-literal=app-api-key="$(openssl rand -hex 32)" \
  --from-literal=database-url="postgresql://user:pass@rds-host:5432/trading"
```

### 2. Build & Push Images

```bash
export AWS_ACCOUNT_ID=<your-account-id>
export AWS_REGION=us-east-1

# Login to ECR
aws ecr get-login-password --region $AWS_REGION | \
  docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

# Build and push
docker build -t agentic-trading-backend ./backend
docker tag agentic-trading-backend:latest $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/agentic-trading-backend:latest
docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/agentic-trading-backend:latest

docker build -t agentic-trading-frontend ./frontend
docker tag agentic-trading-frontend:latest $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/agentic-trading-frontend:latest
docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/agentic-trading-frontend:latest
```

### 3. Deploy

```bash
# Substitute account ID and region into the manifest
export AWS_ACCOUNT_ID=<your-account-id>
export AWS_REGION=us-east-1
envsubst < k8s-deploy.yaml | kubectl apply -f -
```

---

## Security Model

- **Authentication:** All API endpoints protected by `X-API-Key` header validation
- **Secrets:** All credentials stored in Kubernetes Secrets — never in plaintext YAML or source control
- **CORS:** Configured via `CORS_ALLOWED_ORIGINS` environment variable
- **Ticker sanitization:** All user-supplied ticker inputs validated against `^[A-Z]{1,5}$` regex
- **Rate limiting:** `/api/trigger` has a 10-second per-ticker cooldown
- **Paper mode enforcement:** `AlpacaPaperBroker` hardcodes paper API URL regardless of input
- **K8s account ID:** Never committed — injected at deploy time via `envsubst`

---

## Project Structure

```
agentic-trading-app/
├── backend/
│   ├── agents/
│   │   ├── market_data.py        # yfinance data fetcher + earnings calendar
│   │   ├── strategy.py           # LLM client + StrategyAgent
│   │   └── prompts.py            # System & user prompt templates
│   ├── core/
│   │   ├── database.py           # SQLAlchemy models (positions, logs, insights)
│   │   ├── portfolio_state.py    # PortfolioState + MarketContext Pydantic models
│   │   └── risk_gatekeeper.py    # DeterministicRiskManager
│   ├── trading_interface/
│   │   ├── broker/               # AbstractBrokerAPI + AlpacaPaperBroker
│   │   ├── events/schemas.py     # Pydantic event schemas
│   │   ├── execution/agent.py    # ExecutionAgent + retry logic
│   │   ├── reconciliation/job.py # SyncWorker (broker = source of truth)
│   │   └── security/             # API key auth + ticker sanitization
│   ├── app.py                    # FastAPI application + all endpoints
│   ├── main.py                   # Standalone lifecycle demo
│   └── requirements.txt
├── frontend/
│   └── src/
│       └── App.jsx               # React UI with SSE stream
├── k8s-deploy.yaml               # Kubernetes manifests (EKS + ALB)
├── ARCHITECTURE.md
├── DEPLOYMENT.md
└── README.md
```

---

## Docs

- [Architecture Deep Dive](ARCHITECTURE.md)
- [Deployment Guide](DEPLOYMENT.md)
- [Alpaca Integration](ALPACA_INTEGRATION.md)
- [SOC2 Compliance Notes](SOC2_COMPLIANCE.md)
- [Agentic Trading Spec](AGENTIC_TRADING_SPEC.md)
