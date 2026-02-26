# Agentic Trading App Specification

> **🚨 MANDATORY DISCLAIMER:** *Not Financial Advice. The system is designed for educational, paper-trading, and algorithmic architectural demonstration purposes only. The system does not guarantee profits, and output must not be assumed to be certain. Market outcomes are strictly unpredictable. By default, the system requires and enforces PAPER TRADING ONLY.*

---

## A) Product Spec

**Overview:** 
The Agentic Trading App is an autonomous multi-agent orchestration service built to ingest U.S. equities market data, news headlines, and fundamental company metrics. It proposes transparent, explainable trade ideas and validates them against an impenetrable, deterministic risk engine before outputting automated executions natively to a paper-trading broker integration.

**Core User Journeys:**
1. **Setup & Initialization:** User configures hard risk constraints (e.g., target exposure, maximum daily loss) and enables specific style components (e.g., momentum, swing trading).
2. **Context & Idea Generation:** Active agents constantly ingest abstract market APIs and event streams to propose structured trade `Signal` payloads.
3. **Deterministic Validation:** The deterministic Risk Manager gatekeeps every signal against the hard account constraints.
4. **Execution (Paper Trade):** Approved `RiskReport` outputs are translated into limit-based `OrderRequests` executed exclusively via simulated broker endpoints. Live trading demands an explicit manual codebase flag (`LIVE_MODE=true`) coupled with interactive human confirmation gates.
5. **Continuous Review:** The user monitors dashboards providing point-in-time trade explanations, automated journals, and portfolio performance analytics.

**Key Features / Non-Features:**
- **In-Scope (Features):** Default paper trading execution, multi-agent context synthesis, immutable audit logs, deterministic maximum drawdown circuit breakers, adversarial headline prompting safeguards, JSON-based explainable trade journals.
- **Out of Scope (Non-Features):** Guaranteed profit generators, High-Frequency Trading (HFT) latency engineering, Options/Futures/Crypto derivatives (unless individually unlocked), black-box neural networks (deep learning) bypassing the risk gatekeeper.

**UX Screens List:**
- **Dashboard:** Unified portfolio overview, current margin and total cash, live portfolio heatmaps.
- **Watchlist:** Tracked equities enriched with live multidimensional agent sentiment scoring.
- **Signal Detail:** Explanatory modal detailing the *exact* rationale, agent confidences, and rejected reasons for proposed trades.
- **Risk Panel:** Sliders/inputs to re-configure hard constraints (Exposure limits, stop-loss ATR mults).
- **Execution:** Live visibility into the simulated broker’s pending order book, cancellations, and filled slippage.
- **Journal:** Sortable, human-readable post-trade immutable audit records.
- **Settings:** API integration keys, prompt calibration, active sub-agent toggles.

---

## B) System Architecture

**Components/Services Diagram (Text Representation):**
```text
[ External APIs ] --> [ Ingestion Service ]
                              |
                              v
                      [ Feature Store ]
                              |
[ Multi-Agent Intelligence Layer ] <--> [ Supervisor Agent ]
   (Strategy, Market, News, Fund.)              |
                              +-----------------+
                              |
                     [ Proposed Signal ]
                              |
                              v
                [ Risk Management Service ]  <--- (Hard Deterministic Constraints)
                              |
                      [ Risk Report ] (Approved)
                              |
                              v
                    [ Execution Service ]
                              |
                   [ Broker API (Paper) ]
                              |
                   [ Analytics Service ] (Journaling & Drift Configs)
```

**Data Flow:**
1. **Ingest:** Ingestion abstracts API feeds and populates a time-series Feature Store.
2. **Synthesis:** Agents query the Feature Store based on periodic schedules or event-driven triggers to generate a unified context payload.
3. **Signal Integration:** The Strategy Agent consumes the context and crafts a JSON `Signal` (Buy/Sell/Hold).
4. **Risk Gatekeeping:** The Risk Service intercepts the `Signal`, pulls current `PortfolioDB` state, and either modifies the requested position size, rejects the trade entirely, or approves it.
5. **Execution Routing:** The Execution Agent takes the approved `RiskReport`, translates it to native `BrokerAPI` endpoints, and handles retries and idempotent UUIDs.
6. **Reconciliation:** The Monitoring & Drift Agent reconciles the `OrderFill` against expected conditions in `OrderDB` and commits to `AuditLogDB`.

**Storage Subsystems:**
- `PortfolioDB`: Tracks live paper holdings, buying power, execution slippage, and cumulative performance.
- `OrderDB`: Central state machine tracking `PENDING`, `FILLED`, `CANCELED`, and `REJECTED` internal orders.
- `AuditLogDB`: Append-only, immutable database documenting exact prompts sent to agents and explicit JSON responses driving their outputs.
- `FeatureStore`: Low-latency cache (e.g., Redis) or time-series (e.g., TimescaleDB) for rapid technical/news retrieval.
- `ModelRegistry`: Tracks active prompt versions, guardrail configurations, and agent temperature parameters.

---

## C) Agent Design

**1) Supervisor/Orchestrator Agent**
- **Purpose:** Dispatches sub-agents concurrently, handles overarching timeout limits, and compiles outputs for the Strategy Agent.
- **Inputs/Outputs:** `{"task": "Evaluate AAPL"}` -> `{"status": "compiled", "context_hash": "..."}`
- **Safety/Risk Rules:** Triggers circuit breakers if any sub-agent times out or hallucinate incorrect schema structures twice in a row.

**2) Market Data Agent**
- **Purpose:** Synthesizes price-action context, moving averages (SMA/EMA), Average True Range (ATR), and support/resistance zones.
- **Inputs/Outputs:** `{"ticker": "AAPL", "window": "30d"}` -> `{"trend": "bullish", "atr_atr": 3.42, "rsi_14": 58.2}`
- **Safety/Risk Rules:** Enforces a hard rejection if liquidity / average daily volume profiles are below minimum thresholds, preventing data hallucination on micro-caps.

**3) News & Sentiment Agent**
- **Purpose:** Parses aggregated headlines and raw SEC filing texts to construct a deterministic sentiment heat score.
- **Inputs/Outputs:** `{"ticker": "AAPL", "articles": [...]}` -> `{"sentiment": 0.8, "themes": ["Dividend Hike", "M&A Rumor"]}`
- **Safety/Risk Rules (Adversarial):** Specifically instructed to downgrade extreme emotional language. "Ignore clickbait framing. Do not assume 'historic rally' headlines predict continued guarantees. Decline sentiment grading if the text is heavily speculative."

**4) Fundamentals Agent**
- **Purpose:** Retrieves standardized financial ratios (P/E, PEG, Debt-to-Equity, FCF) and determines relative valuation percentiles.
- **Inputs/Outputs:** `{"ticker": "AAPL"}` -> `{"valuation": "fair", "health_score": 85}`
- **Safety/Risk Rules:** Flags missing earnings data as "UNCERTAIN" rather than extrapolating or guessing values.

**5) Strategy Agent (Signal Generation)**
- **Purpose:** Consolidates intelligence into an actionable trade proposition based on the user's active style.
- **Inputs/Outputs:** `Context Array` -> `Signal Payload` (See Blueprint for schema).
- **Example Prompt:** *"You are the Strategy Architect. Your mandated style is: Swing Momentum. Review the supplied Market, News, and Fundamental contexts. Propose a long/short trade ONLY if all signals exhibit robust alignment. If conditions are mixed, emit a HOLD action. You must not claim certainty. Provide a JSON response including confidence (0-1.0) and exactly a 2-sentence rationale."*

**6) Risk Manager Agent (Hard Gatekeeper)**
- **Purpose:** The ultimate authority. Applies deterministic mathematical rules to the `Signal`. It is *not* entirely LLM-based; the LLM merely structures the rejection/approval explanations. The math is executed in raw code.
- **Inputs/Outputs:** `Signal`, `Portfolio Context` -> `RiskReport Payload`.
- **Safety/Risk Rules:** See Section (D). Evaluates single-name exposure, sets exact dollar-value tracking stop losses (e.g., 2x ATR).

**7) Execution Agent**
- **Purpose:** Native translation of approved reports to the backend Broker integration.
- **Inputs/Outputs:** `RiskReport` -> `OrderRequest`, `Broker Fill Data`.
- **Safety/Risk Rules:** Requires configuration `LIVE_MODE=true` environment explicitly. Enforces limit orders natively; never executes raw immediate market orders on low liquidity options.

**8) Monitoring & Drift Agent**
- **Purpose:** Real-time reconciliation. Evaluates if the asset is trailing the stop-loss aggressively or drifting against the original strategy confidence parameter.
- **Inputs/Outputs:** `Market Tick`, `Active Position` -> `Drift Alert` / `Stop Trigger`.

**9) Journal/Explanation Agent**
- **Purpose:** Translates internal JSON routing, execution slippage, and Strategy/Risk rationales into a beautiful, human-readable post-trade journaling format for analysis.
- **Inputs/Outputs:** `OrderFill Event` -> `JournalEntry Payload`.

---

## D) Decision Policy & Risk Rules (Hard Constraints)

- **Position Sizing Method:** Capital sizing is fixed fractional adjusted by volatility targeting (e.g., Risk exactly 1% of account equity dynamically divided by the current 14-day ATR to calculate raw share quantity).
- **Exposure Limits:**
  - **Single Name Maximum:** 5% of total portfolio equity.
  - **Sector Maximum:** 20% total exposure correlation.
  - **Gross/Net Exosure:** 100% allowed Gross (Zero total leverage).
- **Stop-Loss/Take-Profit Logic:**
  - **Stop-Loss:** Dynamically applied at exactly `2 * ATR(14)` below execution price upon entry, transitioning to trailing on highly profitable conditions.
  - **Take-Profit:** Employs scaled exits at `1.5` and `3.0` Reward/Risk ratios.
- **Max Loss / Circuit Breakers:**
  - **Max Daily Loss:** 3%. If hit, `Trading Halt` is flipped to `true`.
  - **Max Drawdown (Kill Switch):** Drops below 10% from the High Water Mark totally disables the execution service. It requires an explicit user reset via CLI/Database to restart.
- **Trade Frequency & Assumptions:** Capped at 5 executions per rolling 24-hours to avoid hallucination loops. Fixed assumption cost of 0.05% slippage applied to backtests. 
- **"No-Trade" Conditions:** 
  - Sub $5 Million Daily Notional Volume.
  - Within 3 trading days of scheduled earnings (Vol-crush protection).
  - Broad VIX > 35 (Unless market-neutral strategy is explicitly toggled).
  - If any data source (e.g., Fundamentals API) returns HTTP 500 or missing values.

---

## E) Execution & Order Lifecycle

- **Order Types Supported:** 
  - Standard entries use exact **Limit Orders** targeting the currently observed Mid-Price. 
  - Stop Losses utilize **Stop Market** orders to guarantee execution upon downside threshold violations.
- **Pre-trade Checks:** Validates identical ticker hasn't been ordered in the last 15 minutes. Validates paper buying power encompasses the gross limit value.
- **Post-trade Checks:** Computes slippage against the expected algorithm price. Reconciles exact internal OrderDB state with remote BrokerAPI position syncs.
- **Idempotency & Handling:** All `OrderRequests` generate a standard `uuid(v4)`. Any network timeouts or HTTP 50X errors trigger an exponential backoff sequence (T+1s, T+5s, T+15s). After 3 failures, order transitions internally to a `FATAL_ERROR` state and alerts human operators without re-execution guarantees.

---

## F) Explainability & Audit Logging

- **Human-Readable Explanation Template:**
> *"On **[Date]**, Strategy Agent identified a **[Swing/Momentum]** execution to **[Buy]** **[AAPL]**. Rationale: Strong fundamental dividend yield coupled with a breakout above 50SMA support lines. Risk constraints approved the transaction, allocating precisely **[$X.XX]** corresponding to **[X%]** total portfolio equity targeting a Stop Loss boundary of **[$Y.YY]**. Assumption: Favorable broader Q4 macro environment. As always, this decision carries market condition and macroeconomic assumption risks and is not to be interpreted as financial advice."*

- **Required `AuditEvent` Record Schema:**
```json
{
  "timestamp": "2026-02-25T14:00:00Z",
  "actor_agent": "risk_manager_agent",
  "action_uuid": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "inputs_hash": "sha256_d8e8fca2dc0f8...",
  "decision_output": "APPROVED",
  "confidence_level": 0.88,
  "risk_checks_passed": true,
  "data_references_ids": ["news_119", "fmp_metric_31"]
}
```

---

## G) Evaluation & Backtesting Plan

- **Validation:** Walk-forward out-of-sample backtesting ensuring rigid temporal boundaries (e.g., models trained or analyzed on 2021-2023 data evaluate unconditionally on strictly unseen 2024 configurations to prevent data leakage).
- **Core Optimization Metrics:**
  - **Sharpe/Sortino Ratios:** Assumes 5% risk-free rate threshold for true excess baseline determination.
  - **Maximum Drawdown:** Core risk evaluation tracking deepest equity curve drop.
  - **Profit Factor & Hit Rate:** Tracks gross wins / gross losses and trade-level victory percentages.
- **Paper Trading Gates:** 
  - **Gate 1:** Code cannot utilize `LIVE_MODE` until a mathematical historical backtesting unit test passes profitability margins.
  - **Gate 2:** An explicit 30-day "Paper Trading Incubation" period validates actual latency and slippage differences prior to capital deployments.

---

## H) Security & Reliability

- **Secrets Handling:** The Orchestrator ingests configurations via native cloud platforms (AWS Secrets Manager / Azure Key Vault). Zero hard-coded logic API endpoints. Kubernetes/Docker limits enforce least privilege (ReadOnly volumes where logical).
- **Rate Limits & Fail-Safes:** Both APIs and Agent inference calls incorporate strict rate-limit counting (e.g., token-bucket architecture) protecting massive bill shocks. If the application crashes, default state is entirely closed.
- **Monitoring Alerts:** Prometheus metric exports track LLM inference latency timeouts, unexpected trade rejection rates (> 50% signal rejection implies data errors), and fatal connectivity alerts triggering automated Slack/Email webhooks.

---

## I) Starter Implementation Blueprint

**Suggested Repository Structure:**
```text
agentic-trading/
├── agents/             # Modular agent logic
│   ├── _base.py        # Abstract agent class with standardized LLM parsing
│   ├── market.py
│   ├── strategy.py
│   └── orchestrator.py
├── api_clients/        # Abstracted third-party interfaces
│   ├── broker_client.py 
│   ├── news_client.py
│   └── financial_data.py
├── core/               # Mathematical hard definitions
│   ├── risk_gatekeeper.py # Explicit raw python code (No LLM here)
│   ├── portfolio_state.py
│   └── validators.py
├── db/                 # Repositories for SQLite/Postgres schemas
│   └── audit_logs.py
├── config/             # Environment constraints (.env structures)
├── tests/              # PyTest test-suites covering gates and boundaries
└── main.py             # Launch sequence initiating the event bus
```

**Message Bus / Pub-Sub Topics:**
Implementations should leverage an event-driven queue like Redis, RabbitMQ, or Python/Go Async channels:
`stream.market_tick` -> `stream.news_tick` -> `event.agents_ready` -> `event.signal_proposed` -> `event.risk_approved` -> `event.broker_executed` -> `event.audit_logged`.

**Example JSON Payload Contracts:**

*(1) Signal Proposed Payload:*
```json
{
  "event_id": "sid_938101",
  "ticker": "MSFT",
  "suggested_action": "BUY",
  "suggested_horizon": "swing",
  "strategy": "mean_reversion",
  "confidence": 0.74,
  "rationale_llm": "Historical support established despite negative immediate headlines which read as primarily speculative."
}
```

*(2) RiskReport Payload:*
```json
{
  "signal_id": "sid_938101",
  "status": "APPROVED",
  "computed_position_size": 2840.50,
  "computed_shares": 7,
  "metrics": {
    "account_exposure_percent": 1.2,
    "volatility_atr": 14.50,
    "hard_stop_loss": 381.00
  },
  "rejection_reason": null
}
```

*(3) OrderRequest Payload:*
```json
{
  "order_uuid": "ord_8820f4ae",
  "ticker": "MSFT",
  "action": "BUY_TO_OPEN",
  "type": "LIMIT",
  "limit_price": 405.78,
  "quantity": 7,
  "time_in_force": "GTC"
}
```
