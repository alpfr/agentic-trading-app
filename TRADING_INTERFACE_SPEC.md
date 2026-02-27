# Trading Interface Layer Specification

> **🚨 MANDATORY DISCLAIMER:** Not Financial Advice. This specification is for architectural and software engineering demonstration only. The system defaults to PAPER TRADING ONLY.

---

## Architecture Overview

The Trading Interface Layer sits between the Multi-Agent Intelligence Layer and Alpaca. It enforces strict separation of concerns, fail-safe defaults, and complete auditability.

```
StrategyAgent ──(SignalCreated)──► DeterministicRiskManager
                                          │
                              ┌───────────┴───────────┐
                          RiskApproved           RiskRejected
                              │                       │
                              ▼                       ▼
                       ExecutionAgent           AuditLog (append)
                              │
                              ▼
                     AlpacaPaperBroker
                     (paper-api only)
                              │
                              ▼
                       StoredPosition (DB)
                              │
                              ▼
                       SyncWorker (reconcile)
```

**Least Privilege:** StrategyAgent has zero access to ExecutionAgent or BrokerAPI. It only emits `SignalCreated` events. Risk evaluation is fully isolated.

---

## Event Schemas (Pydantic)

### `SignalCreated`
```python
ticker:     str           # e.g. "DELL"
action:     SignalAction  # BUY | SELL | HOLD
confidence: float         # 0.0–1.0
rationale:  str           # LLM explanation (logged to audit)
timestamp:  datetime
```

### `RiskApproved`
```python
ticker:        str
action:        ApprovedAction   # BUY_TO_OPEN | SELL_TO_CLOSE
shares:        int
entry_price:   float
stop_price:    float
position_size: float             # Dollar allocation
timestamp:     datetime
signal_id:     str               # Links back to SignalCreated
```

### `RiskRejected`
```python
ticker:         str
reason:         str              # e.g. "VIX_MACRO", "EARNINGS_BLACKOUT"
constraint:     str              # Which gate failed
signal_action:  str
timestamp:      datetime
```

### `OrderRequest`
```python
ticker:     str
side:       OrderSide    # BUY | SELL
quantity:   int
order_type: OrderType    # MARKET (default) | LIMIT
limit_price: float | None
notes:      str          # e.g. "EOD_DAY_TRADING_CLOSE"
```

---

## Risk Gatekeeper — Gate Sequence

Gates are evaluated in strict order. First failure stops evaluation and returns `RiskRejected`.

```
Phase 1: Account Viability
  Gate 1: drawdown_from_hwm > 10%          → DRAWDOWN_HALT
  Gate 2: daily_loss_pct > 3%              → DAILY_LOSS_HALT
  Gate 3: halt_flag == True                → MANUAL_HALT

Phase 2: Macro Regime
  Gate 4: avg_daily_volume < 5,000,000     → LIQUIDITY
  Gate 5: days_to_earnings <= 3            → EARNINGS_BLACKOUT
  Gate 6: vix_level > 35.0 (new longs)    → VIX_MACRO

Phase 3: Portfolio Concentration
  Gate 7: ticker_exposure >= 3% equity     → POSITION_CONCENTRATION
  Gate 8: sector_exposure >= 20% equity    → SECTOR_CONCENTRATION

Phase 4: Position Sizing (BUY only)
  risk_dollars     = equity × risk_per_trade_pct (1%)
  stop_distance    = ATR_14 × atr_multiplier (1× day trading)
  shares           = floor(risk_dollars / stop_distance)
  total_allocation = shares × price

  if total_allocation / equity > max_position_pct (3%):
    shares = floor(equity × 0.03 / price)

  if total_allocation > buying_power:   → BUYING_POWER

Phase 4: Position Sizing (SELL only)
  Verify long position exists for ticker  → NO_POSITION (if not found)
  shares = existing position quantity
```

---

## Execution Agent — Order Lifecycle

```
1. Receive RiskApproved event
2. Staleness check: if age > 5 minutes → discard (log STALE_SIGNAL)
3. Build OrderRequest from RiskApproved
4. Assign client_order_id = UUID (idempotency)
5. Submit to broker with retry:
     attempt 1: immediate
     attempt 2: 2s delay
     attempt 3: 4s delay
   Hard stops (no retry):
     - InsufficientFundsError
     - MarketClosedError
     - InvalidSymbolError
6. On fill: update StoredPosition in DB
7. Write to StoredAuditLog
```

---

## Broker Interface

```python
class AbstractBrokerAPI:
    async def authenticate(api_key, secret_key) -> None
    async def get_account() -> AccountInfo
    async def get_positions() -> List[PositionInfo]
    async def place_order(order: OrderRequest) -> OrderResponseStatus
    async def cancel_order(order_id: str) -> bool
    async def get_order_status(order_id: str) -> OrderResponseStatus
```

`AlpacaPaperBroker` implements this interface with the paper API URL hardcoded:
```python
BASE_URL = "https://paper-api.alpaca.markets/v2"
# Live URL: "https://api.alpaca.markets/v2" — requires explicit code change
```

---

## SyncWorker — Reconciliation

Runs periodically to ensure internal DB matches broker reality:

```
1. GET /positions from Alpaca
2. For each broker position:
   a. Find matching StoredPosition in DB
   b. Compute per-share drift:
        price_drift = abs(broker_price - db_price)
        drift_pct   = (|broker_qty - db_qty| × broker_price) / portfolio_value
   c. If drift > 5%: trigger KILL_SWITCH
   d. Else: update db price to broker price
3. Close any DB positions not present at broker (broker reconciliation)
```

**Key fix:** Per-share price = `market_value / quantity` (not `total market_value`).

---

## Day Trading EOD Sweep

Triggered by `MarketScheduler` at 15:45 ET when `style == "day_trading"`:

```python
async def close_all_positions(broker_client):
    open_positions = db.query(StoredPosition).filter(is_open=True).all()
    for pos in open_positions:
        order = OrderRequest(
            ticker     = pos.ticker,
            side       = OrderSide.SELL,
            quantity   = pos.shares,
            order_type = OrderType.MARKET,
            notes      = "EOD_DAY_TRADING_CLOSE",
        )
        await broker_client.place_order(order)
        pos.is_open    = False
        pos.exit_price = pos.current_price
        db.commit()
```

The sweep fires only once per trading day (`_eod_fired` flag reset each morning).

---

## Audit Log

All state transitions are written to `StoredAuditLog` (append-only):

| Event | agent | action | reason |
|---|---|---|---|
| Signal generated | StrategyAgent | BUY/SELL/HOLD | LLM rationale |
| Risk approved | RiskManager | BUY_TO_OPEN | Approved: N shares at $X |
| Risk rejected | RiskManager | REJECTED | Gate name + details |
| Order placed | ExecutionAgent | ORDER_PLACED | Order ID |
| Order filled | ExecutionAgent | ORDER_FILLED | Fill price |
| EOD close | ExecutionAgent | EOD_DAY_TRADING_CLOSE | Ticker + shares |
| Reconciliation | SyncWorker | RECONCILE | Drift details |
| Stale signal | ExecutionAgent | STALE_SIGNAL | Age in seconds |
