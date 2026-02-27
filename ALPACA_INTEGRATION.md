# Alpaca Integration

## Account

| Field | Value |
|-------|-------|
| Environment | Paper Trading |
| Base URL | `https://paper-api.alpaca.markets/v2` |
| Account ID | PA31MF1P0QZ5 |
| Mode | `is_live_mode = False` (hardcoded — cannot be enabled without code change) |

## Order Configuration

| Parameter | Value | Reason |
|-----------|-------|--------|
| Order type | LIMIT | Controlled execution price |
| Time in force | DAY | Expires at market close — no overnight carry |
| Retry attempts | 3 | Exponential backoff on rate limit / network errors |

## Supported Tickers

All default watchlist tickers are NYSE or Nasdaq listed — fully supported by Alpaca paper trading.

| Ticker | Exchange | Notes |
|--------|----------|-------|
| VTI | NYSE Arca | ETF — highly liquid |
| SCHD | NYSE Arca | ETF — highly liquid |
| QQQ | Nasdaq | ETF — highly liquid |
| JNJ | NYSE | Large cap |
| PG | NYSE | Large cap |
| MSFT | Nasdaq | Large cap |
| NVDA | Nasdaq | Large cap |
| AAPL | Nasdaq | Large cap |

> ⚠️ Do not add OTC-listed securities to the watchlist. Alpaca does not support OTC markets.

## Authentication Flow

```python
# Lazy auth — only called when first order is placed
if not BROKER_CLIENT._client:
    await BROKER_CLIENT.authenticate(
        api_key    = os.getenv("ALPACA_API_KEY"),
        secret     = os.getenv("ALPACA_SECRET_KEY"),
        environment= "PAPER",
    )
```

## Enabling Live Trading

Live trading requires an explicit code change. It will never activate accidentally.

```python
# In trading_interface/execution/agent.py
# Change:
executor = ExecutionAgent(broker=BROKER_CLIENT, is_live_mode=False)
# To:
executor = ExecutionAgent(broker=BROKER_CLIENT, is_live_mode=True)
```

> ⚠️ Never enable live trading with retirement savings. Use a dedicated brokerage account with money you can afford to lose.
