# Agentic Trading App — Product Specification

> **🚨 MANDATORY DISCLAIMER:** Not Financial Advice. This system is for educational, paper-trading, and algorithmic architectural demonstration purposes only. It does not guarantee profits. Market outcomes are strictly unpredictable. The system enforces **PAPER TRADING ONLY** by default.

---

## Overview

The Agentic Trading App is an autonomous multi-agent orchestration platform that ingests US equities market data, generates LLM-powered trade signals, validates them through a deterministic risk engine, and executes approved orders via Alpaca's paper trading API.

---

## User Journeys

1. **Watchlist Setup** — Configure which tickers to monitor (default: AAOI, BWIN, DELL, FIGS, SSL)
2. **Automated Scanning** — Agent runs every 20 minutes per ticker during market hours (09:35–15:40 ET)
3. **Signal Generation** — StrategyAgent proposes BUY/SELL/HOLD with full rationale
4. **Risk Gatekeeping** — DeterministicRiskManager applies 8 hard mathematical constraints
5. **Paper Execution** — Approved signals routed to Alpaca paper broker
6. **EOD Close** — All positions auto-closed at 15:45 ET (day trading mode)
7. **Monitoring** — Real-time dashboard with SSE stream, audit journal, position tracking

---

## Features

### In Scope
- Default paper trading execution (Alpaca paper API)
- Multi-agent context synthesis (market data + LLM strategy)
- Immutable audit logs (append-only SQLAlchemy model)
- Deterministic risk gatekeeper (math-only, no LLM bypass)
- Maximum drawdown circuit breakers (10% HWM, 3% daily)
- Earnings blackout windows (real dates from yfinance calendar)
- VIX macro regime gate (blocks new longs above 35)
- End-of-day auto-close (day trading mode, 15:45 ET)
- Market-hours scheduler (20-minute scan interval per ticker)
- Configurable risk profile (conservative / balanced / aggressive)
- SSE real-time stream (replaces polling)
- Top gainers/losers/actives (yf.screen() + watchlist fallback)
- API key authentication on all endpoints
- EKS deployment with CI/CD via GitHub Actions

### Out of Scope
- Live trading (requires explicit `LIVE_MODE=true` code change)
- High-frequency trading / sub-second latency
- Options, futures, crypto derivatives
- Black-box neural networks bypassing the risk gatekeeper
- Multi-user / multi-portfolio support
- Mobile native app

---

## UI Screens

| Screen | Description |
|---|---|
| **⭐ Watchlist** | Live price cards for AAOI/BWIN/DELL/FIGS/SSL — price, % change, volume, ATR, SMA, open position badge, Run Agent / Quote buttons |
| **Portfolio & Risk** | Account equity, open positions, P&L, sector exposure |
| **AI Insights** | Last 20 agent signals with rationale and confidence |
| **Market Movers** | Top gainers, losers, most active (refreshed every 60s) |
| **Quote Lookup** | Full quote + fundamentals for any ticker |
| **Audit Journal** | Immutable log of every agent action and risk decision |
| **Market History** | Stored market data snapshots |
| **Constraints** | Active risk parameters (read-only display) |

---

## Trading Config (Current)

| Parameter | Value |
|---|---|
| Watchlist | AAOI, BWIN, DELL, FIGS, SSL |
| Style | Day trading (in/out same session) |
| Risk profile | Conservative |
| Risk per trade | 1% of equity |
| ATR stop multiplier | 1× (tight intraday) |
| Max position size | 3% of equity |
| Max open positions | 3 |
| Scan interval | Every 20 minutes |
| Market hours | 09:35–15:40 ET, Mon–Fri |
| EOD auto-close | 15:45 ET |

---

## Risk Engine — 8 Hard Gates

All gates are deterministic math. The LLM cannot influence or bypass any of them.

| Gate | Constraint | Fail Action |
|---|---|---|
| 1 | Account drawdown > 10% from HWM | HALT — no new trades |
| 2 | Daily loss > 3% of equity | HALT — no new trades |
| 3 | Average daily volume < 5,000,000 | REJECT — LIQUIDITY |
| 4 | Earnings within 3 days | REJECT — EARNINGS_BLACKOUT |
| 5 | VIX > 35 (new longs) | REJECT — VIX_MACRO |
| 6 | Ticker allocation > 3% equity | REDUCE to 3% or REJECT |
| 7 | Sector exposure > 20% equity | REJECT — SECTOR_CONCENTRATION |
| 8 | Buying power < required allocation | REJECT — BUYING_POWER |

VIX fetch failure defaults to 99.0 (blocks new longs — fail-safe, not fail-open).
Earnings fetch failure defaults to 999 days (safe — no blackout triggered on API failure).

---

## Agent Definitions

### MarketDataAgent
- Fetches: price, ATR-14, SMA-20, SMA-50, volume, ^VIX, earnings calendar
- Source: yfinance (curl_cffi transport, handles Yahoo Finance auth)
- Cache: 60 seconds at module level (survives across requests)
- Fail-safes: VIX → 99.0, earnings → 999 days

### StrategyAgent
- LLM: OpenAI GPT-4o-mini (configurable via `OPENAI_API_KEY`)
- Fallback: MockSwingLLMClient (deterministic, no API key needed)
- Output schema: `SignalCreated` (Pydantic) — malformed output → HOLD
- Context includes: price, technicals, macro regime, portfolio state

### DeterministicRiskManager
- Pure Python math — zero LLM involvement
- Configurable via `apply_day_trading_config()` at startup
- Produces: `RiskApproved` or `RiskRejected` (never raises to execution layer)

### ExecutionAgent
- Consumes `RiskApproved` events only
- Staleness check: rejects if signal > 5 minutes old
- Idempotency: UUID per order (Alpaca `client_order_id`)
- Retry: exponential backoff on rate limit / network errors
- Hard stops: insufficient funds, market closed

### MoversAgent (`agents/movers.py`)
- Primary: `yf.screen("day_gainers" | "day_losers" | "most_actives")`
- Fallback: 40-ticker watchlist download + % change computation
- Cache: 2 minutes in-memory

### MarketScheduler (`core/scheduler.py`)
- Wakes every 60 seconds, checks market hours
- Triggers agent loop per ticker if `scan_interval` elapsed
- Fires EOD close at 15:45 ET (day trading mode only)
- Staggered 10s between tickers to avoid Yahoo Finance throttling

---

## Audit Trail

Every agent decision is written to `StoredAuditLog`:

```
time    — ISO timestamp
agent   — which agent produced the event
action  — BUY_TO_OPEN | SELL_TO_CLOSE | HOLD | RISK_REJECTED | EOD_CLOSE | ...
ticker  — equity symbol
reason  — human-readable explanation
```

The audit log is append-only. No record is ever modified or deleted.
