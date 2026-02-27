# Architecture — Retirement Portfolio Advisor

## System Overview

```
┌─────────────────────────────────────────────────────────┐
│                    React Frontend                        │
│  Portfolio │ Watchlist │ Rebalance │ Dividends │ Alerts  │
│            │ AI Advisor│ Audit Log │ Research           │
└─────────────────────┬───────────────────────────────────┘
                      │ SSE stream + REST (X-API-Key)
┌─────────────────────▼───────────────────────────────────┐
│                  FastAPI Backend                         │
│                                                          │
│  RetirementScheduler                                     │
│  ├── Daily 10:00 ET → run_agent_loop(ticker) × 8        │
│  └── Weekly Monday  → _run_rebalance_check()            │
│                                                          │
│  Agent Pipeline (per ticker)                            │
│  MarketDataAgent → FundamentalAgent → StrategyAgent     │
│       │                                    │            │
│  yfinance (thread pool)            GPT-4o-mini          │
│       │                                    │            │
│  MarketContext + Fundamentals    SignalCreated           │
│                                    │                    │
│                      RetirementRiskManager              │
│                      7 deterministic gates              │
│                                    │                    │
│                         RiskApproved / RiskRejected     │
│                                    │                    │
│                           ExecutionAgent               │
│                           Alpaca Paper API             │
│                                                          │
│  Reconciliation Loop (every 5 min)                      │
│  Alpaca positions → DB sync + price refresh             │
└─────────────────────────────────────────────────────────┘
```

---

## Agent Pipeline

### 1. MarketDataAgent
- Fetches OHLCV, SMA-20, SMA-50, ATR-14, volume via `yf.download()`
- All calls run in `loop.run_in_executor(None, ...)` — never blocks the event loop
- 60-second module-level cache per ticker

### 2. FundamentalAgent
- Fetches P/E, P/B, dividend yield, payout ratio, revenue growth, debt/equity
- 6-hour cache (fundamentals change slowly)
- Also runs in thread pool

### 3. StrategyAgent (LLM)
- System prompt: `RETIREMENT_ADVISOR_SYSTEM_PROMPT`
- Evaluates each ticker by category (ETF / Dividend / Growth)
- Category injected into every user prompt
- Output: `SignalCreated` with action (BUY/SELL/HOLD/REDUCE), confidence, rationale

### 4. RetirementRiskManager (7 gates, in order)
```
Gate 1: System halt check
Gate 2: Confidence < 60% → REJECT
Gate 3: Portfolio drawdown > 20% → PAUSE new buys
Gate 4: Action routing (BUY/SELL/REDUCE/HOLD)
Gate 5: Min hold period < 30 days → REJECT sell
Gate 6: Concentration > 10% of portfolio → REJECT buy
Gate 7: Trailing stop alert (soft — log only, never block)
+ Buying power check
```

### 5. ExecutionAgent
- Submits LIMIT+DAY orders to Alpaca paper API
- Exponential backoff retry (3 attempts)
- Persists filled position to DB

---

## Scheduler Cadence

```
Every 60s: scheduler tick
  ├── Is trading day (Mon–Fri)?
  ├── Is 10:00–10:15 ET?
  │   ├── Yes + not scanned today → fire agent loop for all 8 tickers
  │   └── Yes + Monday + not rebalanced today → fire rebalance check
  └── No → sleep
```

---

## Rebalance Engine

```
Current positions → category totals (ETF / Dividend / Growth)
Target allocations: ETF 40% / Dividend 25% / Growth 35%

For each category:
  drift = current_pct - target_pct
  if |drift| > 5%:
    drift < 0 → BUY_MORE (underweight)
    drift > 0 → TRIM (overweight)
  else:
    ON_TARGET
```

---

## Alert System

| Alert Type | Trigger | Severity |
|-----------|---------|---------|
| PRICE_DROP | Daily price change ≤ -5% | WARNING |
| PRICE_DROP | Daily price change ≤ -10% | CRITICAL |
| TRAILING_STOP | Position down ≥ 15% from entry | CRITICAL |
| DIVIDEND | Payout ratio > 85% | WARNING |
| REBALANCE | Category drift > 5% | ACTION |
| DRAWDOWN | 52-week high drawdown ≥ 20% | ACTION (buy opportunity) |

---

## Data Flow

```
Startup:
  DB init → apply_retirement_config(RISK_MANAGER) → RetirementScheduler.run()
                                                   → reconciliation loop

Per ticker scan:
  fetch_market_context(ticker)   [thread pool, 60s cache]
  fetch_fundamentals(ticker)     [thread pool, 6hr cache]
  refresh open position prices   [DB update]
  check_and_generate_alerts()    [price drop, stop breach]
  generate_technical_summary()
  fetch_news_and_sentiment()
  StrategyAgent.evaluate_context() → LLM call
  RetirementRiskManager.evaluate_signal()
  ExecutionAgent.execute_approved_risk()
  persist position to DB

Every 5 min:
  _reconcile_positions_with_broker()
  → update prices from Alpaca source of truth
  → close DB positions not found at broker

Weekly (Monday):
  compute_rebalance_report()
  → log recommendations to audit trail
```

---

## Infrastructure

| Component | Spec |
|-----------|------|
| EKS cluster | `agentic-trading-cluster`, us-east-1, t3.medium |
| Domain | agentictradepulse.opssightai.com |
| TLS | ACM wildcard `*.opssightai.com` |
| Backend | 2 replicas, 256Mi–512Mi RAM, 250m–500m CPU |
| Frontend | 2 replicas, Nginx, 128Mi–256Mi RAM |
| Database | SQLite (pod-local, ephemeral) |
| Container registry | ECR (`agentic-trading-backend`, `agentic-trading-frontend`) |
| Load balancer | AWS ALB via `aws-load-balancer-controller` |
| Secrets | Kubernetes `trading-app-secrets` |

---

## CI/CD Pipeline

```
Push to master
  ├── Job 1: Lint (Python syntax, ESLint)        ~2 min
  ├── Job 2: Build + push to ECR                  ~4 min
  ├── Job 3: Provision EKS (idempotent)           ~3 min
  └── Job 4: Deploy + rollout wait                ~3 min
                                           Total: ~8 min
```
