# Architecture Deep Dive

## Event-Driven Pipeline

Every trade follows a strict unidirectional flow. The LLM cannot skip steps or touch the broker directly.

```
User triggers /api/trigger
        │
        ▼
MarketDataAgent.fetch_market_context(ticker)
  · yfinance: price, ATR-14, SMA-20/50, volume
  · yfinance: ^VIX level
  · yfinance .calendar: real earnings date
  · Cache TTL: 60s (module-level, survives requests)
        │
        ▼
StrategyAgent.evaluate_context(ticker, technicals, sentiment, fundamentals)
  · Calls OpenAI GPT-4o-mini (or MockSwingLLMClient)
  · Returns SignalCreated { BUY | SELL | HOLD, confidence, rationale }
  · Pydantic schema enforced — malformed LLM output triggers HOLD fallback
        │
        ▼
DeterministicRiskManager.evaluate_signal(signal, portfolio, market)
  · Phase 1: Account viability (drawdown, daily loss, halt flag)
  · Phase 2: Macro regime (ADV liquidity, earnings blackout, VIX gate)
  · Phase 3: Portfolio concentration (single ticker + sector caps)
  · Phase 4: Volatility sizing (1% equity risk / 2×ATR stop distance)
  · Returns RiskApproved or RiskRejected — NO exceptions propagate to execution
        │
        ▼
ExecutionAgent.execute_approved_risk(risk_event)
  · Staleness check: rejects signals > 5 minutes old
  · Schema translation: RiskApproved → OrderRequest
  · Idempotency key = UUID per order (used as client_order_id at Alpaca)
  · Exponential backoff on RateLimitError / NetworkError
  · Hard stops on InsufficientFundsError / MarketClosedError
        │
        ▼
AlpacaPaperBroker.place_order(order)
  · Hardcoded paper-api.alpaca.markets URL (live mode impossible without code change)
  · Translates internal OrderRequest → Alpaca JSON payload
        │
        ▼
SyncWorker.execute_periodic_reconciliation()
  · Compares broker positions vs internal DB positions
  · Per-share drift = market_value / quantity (not total market_value)
  · Overwrites internal state to match broker reality
  · Kill switch triggered if drift > 5% of portfolio
```

---

## Schema Boundaries

The Pydantic event schemas act as hard interfaces between each layer:

| Schema | Owner | Consumer |
|---|---|---|
| `SignalCreated` | StrategyAgent | RiskManager |
| `RiskApproved` | RiskManager | ExecutionAgent |
| `RiskRejected` | RiskManager | app.py (logs and returns) |
| `OrderRequest` | ExecutionAgent | BrokerAPI |
| `OrderResponseStatus` | BrokerAPI | ExecutionAgent |
| `FillEvent` | BrokerAPI | (reconciliation, future) |

---

## Database Models

```
market_data       — yfinance snapshots per agent run
positions         — open/closed trade records (replaces in-memory list)
audit_logs        — immutable execution journal entries
agent_insights    — LLM strategy signals with full context
```

All models backed by SQLAlchemy. SQLite in dev, PostgreSQL in production via `DATABASE_URL`.

---

## Security Layers

```
Internet
    │
    ▼
AWS ALB (internet-facing)
    │  [optional: WAF ACL for IP allowlist / rate limiting]
    ▼
Kubernetes Ingress
    │
    ▼
FastAPI — require_api_key dependency
    │  X-API-Key header (axios calls)
    │  ?api_key= query param (SSE EventSource)
    ▼
Endpoint Handler
    │
    ▼
sanitize_ticker() — regex ^[A-Z]{1,5}$ on all user-supplied ticker inputs
```

Secrets flow:
```
AWS Secrets Manager (recommended)
  or kubectl create secret
        │
        ▼
Kubernetes Secret (trading-app-secrets)
        │
        ▼
Pod env via secretKeyRef
        │
        ▼
os.getenv() in Python / import.meta.env in Vite
```

---

## Frontend Real-Time Architecture

### Before (polling)
```
Frontend → GET /api/portfolio  ┐
Frontend → GET /api/logs       │  every 2 seconds
Frontend → GET /api/insights   │  = 4 concurrent HTTP requests
Frontend → GET /api/market-data┘
```

### After (SSE)
```
Frontend → GET /api/stream (persistent SSE connection)
                │
                └── Backend pushes { logs, insights, positions } every 2s
                    (single connection, server-initiated, no wasted requests)
```

Market movers and market history still use polling at 30s intervals — acceptable frequency for that data.

---

## Risk Engine Math

### Position Sizing (BUY_TO_OPEN)
```
risk_dollars       = total_equity × 0.01          # 1% of account
stop_distance      = 2.0 × ATR_14                  # 2× Average True Range
raw_shares         = floor(risk_dollars / stop_distance)
total_allocation   = raw_shares × current_price

if total_allocation / total_equity > 0.05:         # Cap at 5% nominal
    raw_shares = floor(total_equity × 0.05 / current_price)

if total_allocation > buying_power:
    → BUYING_POWER violation
```

### Position Sizing (SELL_TO_CLOSE)
```
if no existing long position for ticker:
    → NO_POSITION violation

shares = existing_position.quantity
(close the full position — partial closes not yet implemented)
```

### Drift Calculation (Reconciliation)
```
per_share_price = position.market_value / position.quantity
drift_notional  = |broker_qty - local_qty| × per_share_price
drift_pct       = drift_notional / portfolio_value

if drift_pct > 0.05:
    → KILL SWITCH
```
