# 🏦 Retirement Portfolio Advisor

An AI-powered retirement investment research tool — analyzes stocks and ETFs, monitors your paper portfolio, recommends rebalancing, and generates alerts, all with deterministic risk guardrails the AI cannot bypass.

> **Paper trading only.** This tool is a research and learning aid. Keep your actual retirement savings in a tax-advantaged account (401k, IRA, Roth IRA).

---

## Live Deployment

| Item | Value |
|------|-------|
| Platform | AWS EKS (us-east-1) |
| Cluster | `agentic-trading-cluster` |
| Namespace | `agentic-trading-platform` |
| Broker | Alpaca Paper Trading |
| Deploy | GitHub Actions (auto on push to `master`) |

---

## What It Does

| Feature | Description |
|---------|-------------|
| **AI Advisor** | GPT-4o-mini evaluates each holding as a long-term business — fundamentals, dividend sustainability, moat, 5-year thesis |
| **Daily Scan** | Runs every trading day at 10:00 ET across your full watchlist |
| **Rebalance Engine** | Compares current allocation vs targets weekly; flags drift >5% |
| **Alert System** | Price drops >5%, trailing stop breaches, dividend payout risk |
| **Risk Guardrails** | Hard mathematical limits the AI cannot override |
| **Paper Trading** | Executes paper orders via Alpaca; tracks PnL on simulated positions |

---

## Default Portfolio

| Ticker | Name | Category | Target |
|--------|------|----------|--------|
| VTI | Vanguard Total Market ETF | ETF | 40% combined |
| SCHD | Schwab Dividend ETF | ETF | |
| QQQ | Invesco Nasdaq-100 ETF | ETF | |
| JNJ | Johnson & Johnson | Dividend | 25% combined |
| PG | Procter & Gamble | Dividend | |
| MSFT | Microsoft | Growth | 35% combined |
| NVDA | Nvidia | Growth | |
| AAPL | Apple | Growth | |

---

## Risk Guardrails

Enforced in Python — AI recommendation is rejected if any gate fails.

| Gate | Limit | Purpose |
|------|-------|---------|
| Min signal confidence | 60% | Only act on high-conviction signals |
| Max single position | 10% | Prevent over-concentration |
| Portfolio drawdown pause | 20% from peak | Stop buying during major corrections |
| Min hold period | 30 days | Avoid churn + short-term capital gains tax |
| Trailing stop alert | 15% from entry | Soft alert only — review thesis, not auto-sell |
| Rebalance drift trigger | 5% from target | Weekly category rebalance check |

---

## API Reference

All endpoints require `X-API-Key` header.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/api/portfolio` | Open positions + account value |
| GET | `/api/watchlist` | Current watchlist + retirement config |
| PUT | `/api/watchlist` | Update watchlist tickers |
| POST | `/api/watchlist/scan` | Trigger immediate full scan |
| GET | `/api/rebalance` | Category drift report + recommendations |
| POST | `/api/rebalance/run` | Manual rebalance check |
| GET | `/api/alerts` | All portfolio alerts |
| POST | `/api/alerts/{id}/read` | Mark alert as read |
| GET | `/api/dividends` | Dividend income summary |
| GET | `/api/fundamentals/{ticker}` | Full fundamentals for a ticker |
| GET | `/api/quote/{ticker}` | Live quote |
| GET | `/api/insights` | AI advisor recommendation history |
| GET | `/api/logs` | Audit trail |
| POST | `/api/trigger` | Run AI analysis on a ticker |
| GET | `/api/stream` | SSE live data stream |

---

## Project Structure

```
├── backend/
│   ├── app.py                      # FastAPI, all endpoints, startup
│   ├── agents/
│   │   ├── market_data.py          # yfinance (thread pool — non-blocking)
│   │   ├── fundamental.py          # P/E, dividend, revenue data
│   │   ├── strategy.py             # LLM strategy agent
│   │   ├── prompts.py              # Retirement advisor system prompt
│   │   └── movers.py               # Market movers scanner
│   ├── core/
│   │   ├── watchlist.py            # RetirementConfig, target allocations
│   │   ├── risk_gatekeeper.py      # RetirementRiskManager, 7 gates
│   │   ├── scheduler.py            # Daily scan + weekly rebalance
│   │   ├── rebalance.py            # Category drift + recommendations
│   │   ├── alerts.py               # Price/stop/dividend alerts
│   │   ├── database.py             # SQLAlchemy models
│   │   └── portfolio_state.py      # Shared schemas
│   └── trading_interface/
│       ├── broker/alpaca_paper.py  # Alpaca paper broker
│       ├── execution/agent.py      # Order execution
│       └── reconciliation/job.py   # Broker sync (every 5 min)
├── frontend/src/App.jsx            # React UI (8 tabs)
├── k8s-deploy.yaml                 # Kubernetes manifests
└── .github/workflows/
    ├── deploy.yml                  # CI/CD (lint → build → EKS → deploy)
    └── get-app-url.yml             # Retrieve live ALB URL
```

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | GPT-4o-mini for AI advisor |
| `ALPACA_API_KEY` | Alpaca paper trading |
| `ALPACA_SECRET_KEY` | Alpaca paper trading |
| `APP_API_KEY` | Frontend → backend auth |
| `DATABASE_URL` | SQLite (default) or PostgreSQL |
| `AWS_ACCESS_KEY_ID` | ECR + EKS access (GitHub secret) |
| `AWS_SECRET_ACCESS_KEY` | ECR + EKS access (GitHub secret) |

---

## Disclaimer

This application is a research and learning tool only. It does not provide financial advice. AI recommendations are paper-simulated and should never be the sole basis for real investment decisions. Always consult a qualified financial advisor before making retirement investment decisions.
