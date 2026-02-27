# Trading Interface Specification

## Order Flow

```
RiskApproved event
       │
       ▼
ExecutionAgent._pre_trade_checks()
  ├── Signal age > 5 min? → DROP (stale)
  └── Pass
       │
       ▼
OrderRequest created:
  ticker, action (BUY/SELL/REDUCE)
  order_type = LIMIT
  time_in_force = DAY
  quantity = approved_quantity
  limit_price = approved_limit_price
       │
       ▼
broker.place_order(order)
  ├── RateLimitError → backoff retry (up to 3×)
  ├── NetworkError → retry with idempotency key
  ├── InsufficientFundsError → abort
  ├── MarketClosedError → abort (no overnight)
  └── Success → OrderResponseStatus (broker_order_id)
       │
       ▼
Persist StoredPosition to DB
log_audit("FILLED", ...)
```

## Pydantic Schemas

### SignalCreated
```python
signal_id:        str
ticker:           str
suggested_action: str   # BUY | SELL | HOLD | REDUCE
confidence:       float # 0.0–1.0
rationale:        str
suggested_horizon:str   # long_term
strategy_alias:   str
```

### RiskApproved
```python
signal_id:            str
ticker:               str
action:               str   # BUY_TO_OPEN | SELL_TO_CLOSE | REDUCE_TO_CLOSE
approved_quantity:    int
approved_limit_price: float
risk_metrics:         RiskMetrics
```

### RiskMetrics
```python
position_size_pct: float  # approved_qty × price / total_equity
hard_stop_loss:    float  # entry × (1 - 0.15) — review alert threshold
approved_qty:      int
```

### StoredPosition (DB model)
```python
id:            str   # UUID
ticker:        str
side:          str   # LONG | SHORT
shares:        int
entry_price:   float
current_price: float # Updated by reconciler + agent scan
stop_price:    float # Alert threshold (not auto-triggered)
pnl_pct:       float # Computed at read time
is_open:       bool
opened_at:     datetime
closed_at:     datetime | None
```

## Reconciliation

Runs every 5 minutes via `_reconcile_positions_with_broker()`:

```
Alpaca positions → broker_map {ticker: PositionSchema}
DB open positions → db_open list

For each db_open position:
  if ticker in broker_map:
    true_price = market_value / quantity
    drift = |true_price - db_price| / db_price
    if drift > 5%: log WARNING
    update db current_price = true_price
    update db shares = broker quantity
  else:
    mark is_open = False
    set closed_at = now()
    log_audit("RECONCILED_CLOSE", ...)
```

## Position Sizing

For a BUY signal with portfolio equity $100,000:
```
allocation = 100,000 × 0.02 = $2,000
qty = floor(2,000 / current_price)

Example: MSFT @ $415
qty = floor(2,000 / 415) = 4 shares
position_value = 4 × 415 = $1,660 (1.66% of portfolio)
```

Maximum position after multiple additions: 10% = $10,000
Concentration gate blocks additional buys beyond that threshold.
