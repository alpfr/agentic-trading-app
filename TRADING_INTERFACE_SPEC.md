# Trading Interface Layer Specification

> **🚨 MANDATORY DISCLAIMER:** *Not Financial Advice. This specification is for architectural and software engineering demonstration purposes only. The system does not guarantee profits, and output must not be assumed to be certain. Market outcomes are unpredictable. This system defaults to PAPER TRADING ONLY.*

---

## A) Architecture Overview

The Trading Interface Layer sits between the Multi-Agent Intelligence Layer and the external Brokerage. It is an event-driven architecture designed to enforce strict isolation of concerns, fail-safe defaults, and immutable auditability.

*   **Signal Source (Strategy Agent):** Proposes trades. It has **zero access** to the BrokerAPI or Execution Agent. It only publishes `SignalCreated` events.
*   **Risk Manager (Hard Gatekeeper):** Consumes `SignalCreated` events, applying deterministic math (not LLM-based logic) against current portfolio state and limits. It publishes `RiskApproved` or `RiskRejected` events.
*   **Execution Agent:** The *only* component authorized to communicate with the BrokerAPI. It consumes `RiskApproved` events, constructs idempotent `OrderRequests`, and manages the order lifecycle.
*   **BrokerAPI (Abstract):** A standardized, broker-agnostic interface wrapping external SDKs (e.g., Alpaca, Interactive Brokers).
*   **MarketDataAPI:** Provides real-time pricing for pre-trade slippage checks and limit order pricing.
*   **PortfolioDB & OrderDB:** Local state stores representing the internal view of orders and positions.
*   **AuditLog:** An append-only, immutable datastore recording every state transition.
*   **EventBus:** A message broker (e.g., Redis Streams, Kafka) handling asynchronous decoupled communication between all services. Guaranteed at-least-once delivery.

**Boundary Justification (Least Privilege):** 
By using an event-driven model, the Strategy Agent cannot ever bypass the Risk Manager. The Execution Agent is completely isolated from the internet (except the strict BrokerAPI domain) and cannot read news or generate signals. If the Strategy Agent is compromised via prompt injection, its malicious signals will still be structurally verified and likely blocked by the Risk Manager's hard exposure constraints.

---

## B) BrokerAPI Abstraction

The `BrokerAPI` is an interface with standardized contracts. It translates internal agnostic payloads to broker-specific formats.

### Required Methods

*   `authenticate(api_key: str, secret: str, environment: str) -> bool`
*   `get_account() -> AccountSchema`
*   `get_positions() -> List[PositionSchema]`
*   `get_open_orders() -> List[OrderSchema]`
*   `place_order(order: OrderRequestSchema) -> OrderResponseSchema`
*   `cancel_order(broker_order_id: str) -> bool`
*   `get_order_status(broker_order_id: str) -> OrderStatusSchema`
*   `get_fills(since: datetime) -> List[FillSchema]`

### JSON Schemas

**OrderRequestSchema**
```json
{
  "internal_order_id": "uuid4",
  "idempotency_key": "uuid4",
  "ticker": "AAPL",
  "action": "BUY_TO_OPEN",
  "order_type": "LIMIT",
  "time_in_force": "GTC",
  "quantity": 10,
  "limit_price": 180.50,
  "extended_hours": false
}
```

**OrderResponseSchema**
```json
{
  "broker_order_id": "brk_991238xa",
  "internal_order_id": "uuid4",
  "status": "ACCEPTED",
  "submitted_at": "2026-02-25T14:30:00Z"
}
```

### Standardized Error Codes
*   **`ERR_RATE_LIMIT` (Retryable):** HTTP 429. Trigger exponential backoff.
*   **`ERR_NETWORK` (Retryable):** HTTP 500/502/504 or timeouts.
*   **`ERR_INSUFFICIENT_FUNDS` (Non-Retryable):** HTTP 403. Halt sequence, alert user.
*   **`ERR_INVALID_TICKER` (Non-Retryable):** HTTP 404/400. Reject.
*   **`ERR_MARKET_CLOSED` (Non-Retryable):** Reject order unless extended hours explicitly authorized.

---

## C) Execution Agent Design

The Execution Agent translates a `RiskApproved` event (which includes the Signal and RiskReport) into a live order.

*   **Inputs:** `Signal` + `RiskReport` + `Portfolio State Snapshot`
*   **Outputs:** `OrderRequest` (to Broker), `OrderStatusUpdated` (to EventBus), `AuditEvent`.

### Order Lifecycle State Machine
`CREATED` → (Submit to Broker) → `SUBMITTED` → (Broker ACKs) → `ACKNOWLEDGED` → (Execution) → `PARTIALLY_FILLED` → `FILLED`
*Failure Paths:* `REJECTED` (Broker denied), `CANCELED` (User or logic aborted), `FATAL_ERROR` (Max retries exceeded).

### Idempotency and Deduplication
The Execution Agent maps the `SignalID` to a unique `idempotency_key` (UUIDv4) stored in Redis before calling `place_order()`. The BrokerAPI relies on this key (passed via `Client-Order-ID` HTTP headers). If a network timeout occurs and the agent retries the POST request, the broker will return the existing order rather than executing a duplicate.

### Pre-Trade Checks (Hard Execution Limits)
Right before submission, the Execution Agent verifies:
1.  **Staleness:** Is current time > 5 minutes since `RiskApproved` timestamp? If yes -> `REJECT`.
2.  **Trading Hours:** Is the market open? Are we within 15 minutes of the closing bell? (Avoid EOD volatility).
3.  **Data Integrity:** Does the `MarketDataAPI` report a bid/ask spread > 2%? (Illiquid, `REJECT`).

---

## D) Reconciliation & Source of Truth

**Source of Truth:** The external Broker is the absolute source of truth for all executions, fills, and cash balances. Local `OrderDB` and `PortfolioDB` are strictly materialized views for low-latency agent querying.

**Reconciliation Job:**
A background worker (Reconciliation Agent) runs via Cron.
1.  **Event-Driven:** Listens for webhook pushes from the broker (e.g., execution updates) to update `OrderDB`.
2.  **Periodic (Every 5 minutes):** Calls `get_positions()` and `get_open_orders()`.
3.  **Mismatch Handling:** Compares local `PortfolioDB` quantities against the Broker. If Local `AAPL shares = 10` but Broker `AAPL = 15` (perhaps due to a missed webhook):
    *   The `PortfolioDB` is forcefully overwritten with the Broker's state.
    *   A massive `STATE_DRIFT` alert is triggered to Slack/PagerDuty.
    *   If drift exceeds 5% of total account value, the `Kill Switch` is activated holding all future orders.

---

## E) Event Contracts & Message Topics

### Topics
*   `trading.signal.created`
*   `trading.risk.approved` / `trading.risk.rejected`
*   `trading.execution.submitted`
*   `trading.execution.fill`
*   `system.killswitch.activated`

### Payloads

**Topic: `trading.risk.approved`**
```json
{
  "event_id": "evt_88192a",
  "timestamp": "2026-02-25T14:31:00Z",
  "signal_id": "sig_112",
  "ticker": "MSFT",
  "action": "BUY",
  "approved_quantity": 15,
  "approved_limit_price": 415.50,
  "hard_stop_loss": 395.00,
  "risk_metrics": {
    "account_exposure_pct": 5.8,
    "strategy": "swing_momentum"
  }
}
```

**Topic: `trading.execution.fill`**
```json
{
  "event_id": "evt_99211b",
  "timestamp": "2026-02-25T14:31:05Z",
  "internal_order_id": "ord_551",
  "broker_order_id": "brk_xyz123",
  "ticker": "MSFT",
  "fill_price": 415.48,
  "filled_quantity": 15,
  "status": "FILLED"
}
```

**Topic: `system.killswitch.activated`**
```json
{
  "timestamp": "2026-02-25T15:00:00Z",
  "reason": "MAX_DAILY_DRAWDOWN_EXCEEDED",
  "triggered_by": "DriftMonitorAgent",
  "action_taken": "ALL_OPEN_ORDERS_CANCELED"
}
```

---

## F) Observability & Audit Logging

### AuditEvent Schema (Immutable)
Every single topic event above writes a row to the PostgreSQL `AuditLogDB` table.
```json
{
  "timestamp": "ISO8601",
  "correlation_id": "sig_112", 
  "component": "RiskManager",
  "input_hash": "sha256(signal_payload)",
  "decision": "APPROVED",
  "risk_checks": {"max_exposure": "PASS", "max_drawdown": "PASS"},
  "references": ["RsiIndicator_v2", "Fundamentals_Q4"]
}
```

### Logging Requirements
*   **Log:** Execution times, exact UUIDs, mathematical reasons for rejection, API latency timings.
*   **Redact:** Broker API Keys, OAuth tokens, personal account numbers, User PII.

### Metrics & Alerts
*   **Metrics (Prometheus):** `order_submission_latency_ms`, `broker_api_error_rate`, `signal_rejection_percentage`.
*   **Alerts (Grafana/PagerDuty):**
    *   *Critical:* Broker API returning 5XX for > 3 minutes.
    *   *High:* > 3 consecutive order rejections (ERR_INSUFFICIENT_FUNDS).
    *   *Medium:* Market data feed latency > 500ms (Triggers stale-data blocks).

---

## G) Security Model

*   **Default State:** Application boots with `LIVE_MODE=false`. The BrokerAPI is hardcoded to target paper-trading URLs (e.g., `paper-api.alpaca.markets`).
*   **Live Mode Authorization:** Changing to `LIVE_MODE=true` requires an environment variable toggle AND an interactive MFA confirmation via the frontend UI by a user with the `Admin` role.
*   **Secrets Handling:** Broker API keys are never stored in plaintext or `.env` files. They are injected at runtime via AWS Secrets Manager or HashiCorp Vault.
*   **Least Privilege Keys:** The Broker API key utilized by the Execution Agent must be generated with `Trade Only` permissions. It must *not* have permissions to execute ACH transfers or withdraw funds.
*   **Data Retention:** Audit logs are retained for 7 years to comply with standard financial record-keeping principles. Event payloads compress to cold storage (S3) after 30 days.

---

## H) Failure Modes & Safe Defaults

| Failure Mode | Detection Mechanism | Automated Fallback | Trading Status | User Message |
| :--- | :--- | :--- | :--- | :--- |
| **Broker API Down** | HTTP 5XX / Connection Timeout | Exponential backoff (max 3 retries). | **HALT** (Orders queued or dumped) | *"Broker API unreachable. Trading sequence halted to prevent duplicate execution."* |
| **Market Data Stale** | Timestamp of last ticker tick > 15 seconds. | Fallback to secondary data provider API. If both fail, reject signal. | **CONTINUES** (but rejects specific illiquid signals) | *"Signal rejected due to stale market data. Required < 15s latency."* |
| **Rate Limiting** | HTTP 429 from Broker | Token-bucket backoff queue. | **DELAYED** | *"Broker rate limit hit. Throttling execution speed."* |
| **Partial Fills** | Webhook returns `PARTIALLY_FILLED` | Leave limit order open until End of Day, then auto-cancel remainder. | **CONTINUES** | *"Order partially filled. Awaiting liquidity for remainder."* |
| **Network Timeouts** | TCP Timeout on Order POST | Generate identical `Client-Order-ID` and retry. Broker rejects if already possessed. | **CONTINUES** | *"Network degradation. Resubmitting with idempotent key validation."* |
| **Clock Skew** | Local system time differs from NTP by > 2s | Startup health check fails. | **FATAL HALT** | *"Critical Time Sync Error. Halting to prevent market-open anomalies."* |

---

## I) Starter Implementation Blueprint

**Suggested Repo Structure:**
```text
trading_interface/
├── broker/
│   ├── base.py            # Abstract Base Class defining the interface boundaries
│   ├── alpaca_paper.py    # Concrete implementation
│   └── exceptions.py      # Standardized ERR_ codes
├── execution/
│   ├── agent.py           # Execution state machine
│   ├── idempotency.py     # Redis wrapper for UUIDs
│   └── pre_trade.py       # Staleness and liquidity checks
├── reconciliation/
│   └── sync_worker.py     # Periodic Cron pulling Broker actuals
├── events/
│   ├── bus.py             # Kafka/Redis Stream publisher/subscriber
│   └── schemas.py         # Pydantic / JSON validations
└── security/
    └── secrets_manager.py # Vault integration
```

**Technology Choices:**
*   **Language:** Python 3.11+ (asyncio) or Go (goroutines) for high-concurrency event handling.
*   **Event Bus:** Redis Streams (lightweight, supports consumer groups).
*   **Database:** PostgreSQL (AuditLog, Orders) + Redis (Idempotency, Fast Portoflio Cache).

**Execution Sequence Diagram (Text):**
```text
[StrategyAgent] --(SignalCreated)--> [EventBus]
[EventBus]      --(SignalCreated)--> [RiskManager]
[RiskManager]   --(RiskApproved)-->  [EventBus]
[EventBus]      --(RiskApproved)-->  [ExecutionAgent]

ExecutionAgent -> Validates Idempotency
ExecutionAgent -> Verifies Stale Data / Time
ExecutionAgent -> BrokerAPI.place_order(Limit)

[BrokerAPI]     -- HTTP 200 --     > ExecutionAgent
ExecutionAgent  --(OrderSubmitted)-> [EventBus]

Broker Webhook  -- (Fill Event) -- > [ReconciliationWorker]
ReconciliationWorker --(FillReceived)--> [EventBus]
[EventBus]      --(FillReceived)-->  [PortfolioDB / AuditLogDB]
```
