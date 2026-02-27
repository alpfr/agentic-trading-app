# Architecture Deep Dive

## Event-Driven Pipeline

Every trade follows a strict unidirectional flow. The LLM cannot skip steps or touch the broker directly.

```
MarketScheduler (every 20 min, Mon–Fri 09:35–15:40 ET)
        │  triggers per watchlist ticker
        ▼
MarketDataAgent.fetch_market_context(ticker)
  · yfinance: price, ATR-14, SMA-20/50, volume
  · yfinance: ^VIX level (fail-safe: defaults to 99.0 if unavailable)
  · yfinance .calendar: real earnings date (fail-safe: 999 days if unavailable)
  · Module-level cache TTL: 60s (survives across requests)
        │
        ▼
StrategyAgent.evaluate_context(ticker, technicals, sentiment, fundamentals)
  · Calls OpenAI GPT-4o-mini (or MockSwingLLMClient if no key)
  · Returns SignalCreated { BUY | SELL | HOLD, confidence, rationale }
  · Pydantic schema enforced — malformed LLM output → HOLD fallback
        │
        ▼
DeterministicRiskManager.evaluate_signal(signal, portfolio, market)
  · Phase 1: Account viability  — drawdown (10%), daily loss (3%), halt flag
  · Phase 2: Macro regime       — ADV liquidity, earnings blackout (3d), VIX (35)
  · Phase 3: Concentration      — single ticker cap (3%), sector cap (20%)
  · Phase 4: Volatility sizing  — 1% equity risk / ATR-stop distance
  · Returns RiskApproved or RiskRejected
        │
        ▼
ExecutionAgent.execute_approved_risk(risk_event)
  · Staleness check: rejects signals > 5 minutes old
  · Idempotency key: UUID per order (Alpaca client_order_id)
  · Exponential backoff: RateLimitError / NetworkError
  · Hard stops: InsufficientFundsError / MarketClosedError
        │
        ▼
AlpacaPaperBroker.place_order(order)
  · Hardcoded paper-api.alpaca.markets URL
  · Live mode requires explicit code change (not a config flag)
        │
        ▼
SyncWorker (periodic reconciliation)
  · Broker is always source of truth
  · Per-share drift = market_value / quantity (not total market_value)
  · Kill switch if drift > 5% of portfolio
        │
        ▼
EOD Sweep (15:45 ET — day trading mode only)
  · Closes all open StoredPosition records via broker
  · Logs each close to StoredAuditLog
```

---

## Scheduler

`core/scheduler.py` — `MarketScheduler` class

```
Every 60 seconds, _tick() checks:

  ┌─ Weekend? ─────────────────────────────────────────────── skip
  │
  ├─ Before 09:35 ET? ─────────────────────────────────────── reset EOD flag, skip
  │
  ├─ After 15:45 ET and EOD not fired? (day trading) ──────── fire close_all_positions()
  │                                                            set _eod_fired = True
  │
  ├─ Outside 09:35–15:40 ET (regular hours only mode)? ────── skip
  │
  ├─ Style = monitor_only? ────────────────────────────────── skip
  │
  └─ For each ticker in watchlist:
       If now - last_scan[ticker] >= scan_interval (20 min):
         asyncio.create_task(run_agent(ticker))
         last_scan[ticker] = now
         await asyncio.sleep(10)    ← stagger to avoid Yahoo Finance burst
```

---

## Day Trading Configuration

Applied at startup via `apply_day_trading_config(RISK_MANAGER)`:

| Parameter | Day Trading | Default (Swing) |
|---|---|---|
| `risk_per_trade_pct` | 1% | 1% |
| `ATR_MULTIPLIER` | **1.0×** | 2.0× |
| `MAX_POSITION_PCT` | **3%** | 5% |
| `MAX_OPEN_POSITIONS` | **3** | 10 |
| `scan_interval_minutes` | 20 | — |
| `eod_close_time_et` | 15:45 | — |

### Position Sizing Math (Day Trading)
```
risk_dollars    = total_equity × 0.01           # 1% risk
stop_distance   = 1.0 × ATR_14                  # 1× ATR (tighter)
raw_shares      = floor(risk_dollars / stop_distance)
total_alloc     = raw_shares × current_price

if total_alloc / total_equity > 0.03:           # Cap at 3% nominal
    raw_shares = floor(total_equity × 0.03 / current_price)

if total_alloc > buying_power:
    → BUYING_POWER violation
```

---

## Movers Agent

`agents/movers.py` — two-tier strategy with 2-minute cache:

```
PRIMARY: yf.screen("day_gainers" | "day_losers" | "most_actives")
  · Uses yfinance's built-in curl_cffi transport
  · Handles Yahoo Finance cookie/crumb auth internally
  · Returns up to 10 tickers per category

FALLBACK (fires if screener returns empty or throws):
  yf.download(40-ticker watchlist, period="5d", interval="1d")
  · Computes % change: (close[-1] - close[-2]) / close[-2]
  · Sorts for top/bottom gainers and highest volume
  · Covers: AAPL MSFT NVDA GOOGL AMZN META TSLA + 33 others

Cache: 120 seconds (module-level dict with _ts timestamp)
```

---

## Schema Boundaries

Each layer communicates only via typed Pydantic schemas:

| Schema | Producer | Consumer |
|---|---|---|
| `SignalCreated` | StrategyAgent | RiskManager |
| `RiskApproved` | RiskManager | ExecutionAgent |
| `RiskRejected` | RiskManager | app.py (logs) |
| `OrderRequest` | ExecutionAgent | BrokerAPI |
| `OrderResponseStatus` | BrokerAPI | ExecutionAgent |

---

## Database Models

```
StoredMarketData   — yfinance snapshots per agent run
StoredPosition     — open/closed trades (replaces in-memory list)
StoredAuditLog     — immutable execution journal
StoredAgentInsight — LLM signals with full context
```

SQLite in dev, PostgreSQL via `DATABASE_URL` in production.

---

## Security Architecture

```
Internet
    │
    ▼
AWS ALB (internet-facing, us-east-1)
    │
    ▼
Kubernetes Ingress (agentic-trading-ingress)
    │   /api/*  → agentic-trading-backend:8000
    │   /health → agentic-trading-backend:8000
    │   /*       → agentic-trading-frontend:80
    ▼
FastAPI — require_api_key()
    │   X-API-Key header (all endpoints)
    │   ?api_key= query param (SSE EventSource)
    ▼
sanitize_ticker() — regex ^[A-Z]{1,5}$
    ▼
Rate limiter — 10s cooldown per ticker on /api/trigger
```

Secret flow:
```
GitHub Secrets (7 secrets)
    │  injected into workflow at runtime
    ▼
Kubernetes Secret (trading-app-secrets)
    │  secretKeyRef in pod spec
    ▼
Pod environment variables
    │  os.getenv() / import.meta.env
    ▼
Application runtime — never logged, never written to disk
```

---

## Frontend Real-Time Architecture

### SSE Stream (`/api/stream`)
```
Frontend opens one persistent EventSource connection
Backend pushes every 2 seconds:
  {
    logs:          last 20 audit entries,
    insights:      last 20 agent signals,
    positions:     all open positions,
    account_value: sum of open position PnL
  }
```

### Polling (slower-changing data)
```
/api/movers         — every 60s  (backend caches 120s)
/api/quote/{ticker} — on demand  (Quote tab + Watchlist cards every 30s)
/api/market-data    — every 30s  (History tab)
```

---

## CI/CD Pipeline

```
git push → master
    │
    ▼
Job 1: Lint & Syntax Check (~2 min)
  · python -m py_compile on all backend files
  · npm run lint on frontend (warnings allowed, errors fail)
    │
    ▼
Job 2: Build & Push to ECR (~5 min)
  · docker buildx with GitHub Actions cache
  · Tags: {git-sha} + latest
  · ECR scan-on-push enabled
    │
    ▼
Job 3: Provision EKS Cluster (~20 min first run, ~2 min if exists)
  · eksctl create cluster (idempotent — skips if already exists)
  · AWS Load Balancer Controller via Helm
  · Namespace + K8s secrets
    │
    ▼
Job 4: Deploy (~5 min)
  · Rolling update (maxSurge=1, maxUnavailable=0)
  · kubectl rollout status (waits for healthy)
  · ALB URL printed to summary
  · Health check: GET /health → HTTP 200
```
