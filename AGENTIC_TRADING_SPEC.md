# Agentic Retirement Advisor — Technical Specification

## Purpose

A multi-agent system that acts as a personal retirement investment research assistant. It autonomously scans a portfolio of stocks and ETFs daily, evaluates them through a fundamentals-first AI lens, enforces deterministic risk guardrails, and recommends allocation changes — all on paper before any real capital is committed.

---

## Investment Philosophy

- **Time horizon**: 5–10 years
- **Style**: Buy-and-hold; DCA into quality positions
- **Never**: Trade on price momentum alone
- **Never**: Auto-sell on short-term volatility
- **Always**: Evaluate the business, not the chart

---

## Agent Roles

| Agent | Responsibility |
|-------|---------------|
| `MarketDataAgent` | Price, SMA, ATR, volume (yfinance, thread pool) |
| `FundamentalAgent` | P/E, dividend yield, payout ratio, revenue growth (yfinance, 6hr cache) |
| `StrategyAgent` | GPT-4o-mini — synthesizes data into BUY/SELL/HOLD/REDUCE + rationale |
| `RetirementRiskManager` | 7 deterministic gates; blocks any AI signal that violates constraints |
| `ExecutionAgent` | Places LIMIT+DAY orders on Alpaca paper; retry logic |
| `RetirementScheduler` | Orchestrates daily scans + weekly rebalance |
| `SyncWorker` | Reconciles DB positions vs Alpaca every 5 minutes |
| `RebalanceEngine` | Computes category drift and recommendations |
| `AlertSystem` | Generates price, stop, dividend, and rebalance alerts |

---

## Risk Gate Sequence

```
Signal received (BUY/SELL/HOLD/REDUCE, confidence 0-1)
        │
        ▼
Gate 1: System halt? ──────────────────────────────► REJECT
        │
        ▼
Gate 2: Confidence < 60%? ─────────────────────────► REJECT (LOW_CONFIDENCE)
        │
        ▼
Gate 3: Portfolio drawdown > 20%? ─────────────────► REJECT (PORTFOLIO_DRAWDOWN)
        │
        ▼
Gate 4: Action = HOLD? ────────────────────────────► REJECT (no execution needed)
        │
        ▼
Gate 5: SELL within 30 days of open? ──────────────► REJECT (MIN_HOLD)
        │
        ▼
Gate 6: BUY would exceed 10% concentration? ───────► REJECT (CONCENTRATION)
        │
        ▼
Gate 7: Trailing stop breached? (soft) ────────────► LOG ALERT only, continue
        │
        ▼
Buying power check ────────────────────────────────► REJECT if insufficient
        │
        ▼
Position sizing: 2% of equity / current price = qty
        │
        ▼
RiskApproved → ExecutionAgent → Alpaca paper order
```

---

## AI Evaluation by Category

### ETFs (VTI, SCHD, QQQ)
- Primary signal: price vs 52-week mean (DCA opportunity when below)
- Expense ratio and index composition reviewed
- Almost never a SELL — ETFs are permanent core holdings
- Confidence required: 60%+

### Dividend Stocks (JNJ, PG)
- Primary signals: yield vs 5-year average, payout ratio (<60% healthy)
- REVIEW flag: payout ratio >80%, dividend cut, 2+ quarters revenue decline
- Confidence required: 65%+ (slightly higher — individual company risk)

### Growth Stocks (MSFT, NVDA, AAPL)
- Primary signals: revenue growth acceleration, PEG ratio, moat indicators
- HOLD when business excellent but P/E stretched beyond 1.5× sector avg
- REDUCE when growth decelerating materially
- Confidence required: 65%+

---

## Rebalance Targets

| Category | Target | Tickers |
|----------|--------|---------|
| ETF | 40% | VTI, SCHD, QQQ |
| Dividend | 25% | JNJ, PG |
| Growth | 35% | MSFT, NVDA, AAPL |

Rebalance recommended when any category drifts >5% from target.

---

## Audit Trail Events

| Event | Agent | Meaning |
|-------|-------|---------|
| PROCESSING | Supervisor | Agent loop started for ticker |
| SYNCED | MarketDataAgent | Price data fetched successfully |
| PROPOSED | StrategyAgent | LLM recommendation emitted |
| APPROVED | RiskManager | All gates passed, order sizing complete |
| REJECTED | RiskManager | Gate failed — reason logged |
| FILLED | ExecutionAgent | Alpaca paper order confirmed |
| REBALANCE | RebalanceEngine | Weekly drift recommendation logged |
| RECONCILED_CLOSE | SyncWorker | Position closed at broker, DB updated |
| ALERT | AlertSystem | Price/stop/dividend event detected |

---

## UI Tabs

| Tab | Contents |
|-----|---------|
| **Portfolio** | Open paper positions, PnL, risk guardrails status |
| **Watchlist** | Live price cards, daily change, vs SMA%, dividend yield, open position badges |
| **Rebalancing** | Category allocation vs targets, drift chart, BUY_MORE/TRIM recommendations |
| **Dividends** | Projected annual income from current holdings |
| **Alerts** | Price drop, stop breach, dividend risk, rebalance triggers |
| **AI Advisor** | Full history of AI recommendations with rationale and confidence |
| **Audit Log** | Immutable event-by-event execution journal |
| **Research** | On-demand quote + fundamentals for any ticker |
