# Alpaca Integration Guide

The Agentic Trading App routes all approved trade signals to **Alpaca Markets** via the `AlpacaPaperBroker`. The paper trading API is enforced by default — live trading requires an explicit code change.

---

## Your Paper Account

| Field | Value |
|---|---|
| API Endpoint | `https://paper-api.alpaca.markets/v2` |
| Account ID | `PA31MF1P0QZ5` |
| Environment | Paper (simulated) |

API keys are stored in the Kubernetes Secret `trading-app-secrets` and never appear in source code.

---

## Setup

### 1. Get API Keys
1. Log in at [app.alpaca.markets](https://app.alpaca.markets)
2. Ensure you are on the **Paper Trading** dashboard
3. Click **View API Keys** → Generate a key pair (Key ID + Secret Key)

### 2. Store Keys

**In Kubernetes (production):**
```bash
kubectl create secret generic trading-app-secrets \
  --from-literal=alpaca-api-key="PK..." \
  --from-literal=alpaca-secret-key="..." \
  --dry-run=client -o yaml \
  -n agentic-trading-platform | kubectl apply -f -
```

**In GitHub Secrets (CI/CD):**
- `ALPACA_API_KEY` → your Key ID
- `ALPACA_SECRET_KEY` → your Secret Key

**Locally:**
```bash
# backend/.env
ALPACA_API_KEY=PK...
ALPACA_SECRET_KEY=...
```

---

## How Orders Are Routed

```
RiskApproved event
    │
    ▼
ExecutionAgent.execute_approved_risk()
    │  staleness check (< 5 min)
    │  build OrderRequest
    ▼
AlpacaPaperBroker.place_order(OrderRequest)
    │  POST https://paper-api.alpaca.markets/v2/orders
    │  {
    │    symbol:        ticker,
    │    qty:           shares,
    │    side:          buy | sell,
    │    type:          market,
    │    time_in_force: day,
    │    client_order_id: <uuid>    ← idempotency key
    │  }
    ▼
Alpaca fills order (simulated)
    ▼
StoredPosition updated in DB
```

---

## Order Types Used

| Scenario | Order Type | TIF |
|---|---|---|
| BUY_TO_OPEN | market | day |
| SELL_TO_CLOSE | market | day |
| EOD_CLOSE | market | day |

Market orders are used for simplicity and guaranteed fill. Future versions may add limit orders for better fill prices.

---

## Monitoring Fills

Alpaca paper fills can be monitored at:
- **Dashboard:** `https://app.alpaca.markets/paper/dashboard/overview`
- **Orders page:** Shows all placed, filled, and cancelled orders
- **App audit log:** `GET /api/logs` or the Audit Journal tab in the UI

The `SyncWorker` reconciles broker positions against the internal DB every few minutes.

---

## Live Trading (Disabled by Default)

Live trading is **not configurable via environment variable** — it requires a code change to prevent accidental live execution.

To enable (advanced users only):
1. Change `AlpacaPaperBroker` base URL from `paper-api.alpaca.markets` to `api.alpaca.markets`
2. Use Live account API keys (different from paper keys)
3. Add explicit human confirmation gates before each order
4. Thoroughly review and test all risk parameters

> ⚠️ The authors accept no responsibility for financial losses from live trading.

---

## Alpaca Rate Limits

| Endpoint | Limit |
|---|---|
| Orders (place) | 200 req/min |
| Account info | 200 req/min |
| Positions | 200 req/min |

The `ExecutionAgent` handles `429 Too Many Requests` with exponential backoff (base 2s, max 3 retries).

---

## Supported Assets

Alpaca paper trading supports US equities traded on NYSE, NASDAQ, and AMEX. Your current watchlist:

| Ticker | Exchange | Notes |
|---|---|---|
| AAOI | NASDAQ | Applied Optoelectronics — small cap, volatile |
| BWIN | OTC | Better World Acquisition — lower liquidity, watch spreads |
| DELL | NYSE | Dell Technologies — liquid, mid-large cap |
| FIGS | NYSE | FIGS Inc — consumer/healthcare |
| SSL | NYSE | Sasol Ltd (ADR) — commodity-linked, lower volume |

> ⚠️ **BWIN** trades OTC. Alpaca may have limited or no support for OTC securities. If BWIN orders are rejected, remove it from the watchlist via `PUT /api/watchlist`.
