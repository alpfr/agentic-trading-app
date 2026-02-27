# Changelog

All notable changes to the Agentic Trading App are documented here.

---

## [2.0.0] — 2026-02-27

### Added — Day Trading Watchlist
- **Watchlist**: AAOI, BWIN, DELL, FIGS, SSL configured as default day trading watchlist
- **`core/watchlist.py`**: `TradingConfig` dataclass — style, risk profile, ATR multiplier, position caps, scan interval, EOD time
- **`core/scheduler.py`**: `MarketScheduler` — runs agent loop every 20 min per ticker, Mon–Fri 09:35–15:40 ET, EOD sweep at 15:45 ET
- **`core/day_trading.py`**: `apply_day_trading_config()` patches `DeterministicRiskManager` at startup; `close_all_positions()` for EOD sweep
- **`GET /api/watchlist`**: Returns current watchlist + full trading config
- **`PUT /api/watchlist`**: Update watchlist tickers at runtime
- **`POST /api/watchlist/scan`**: Immediately scan all watchlist tickers in background
- **`POST /api/watchlist/close-all`**: Manual EOD close trigger
- **⭐ Watchlist tab** in frontend: live price cards with price, % change, volume, ATR, SMA20/50, open position badge, Run Agent + Quote buttons
- **Scan All Now** and **Close All** header buttons
- **Trading Config panel** showing all active risk parameters

### Added — GitHub Actions CI/CD
- **`deploy.yml`**: Full pipeline — lint → ECR build/push → EKS cluster provision → rolling deploy
- **`get-app-url.yml`**: Manual workflow that prints live ALB URL and pod status
- **`destroy.yml`**: Manual teardown (requires typing `DESTROY` to confirm)

### Added — Market Movers
- **`agents/movers.py`**: Two-tier movers strategy
  - Primary: `yf.screen()` with Yahoo Finance predefined screeners (handles cookie/crumb auth)
  - Fallback: 40-ticker watchlist download with % change computation
  - 2-minute in-memory cache
  - Volume field added to each mover result
- Frontend mover cards now show volume (M/K formatted)
- Polling interval: 30s → 60s (aligned with 2-min server cache)

### Added — Infrastructure
- **EKS cluster**: `agentic-trading-cluster`, us-east-1, t3.medium nodes
- **Namespace**: `agentic-trading-platform`
- **ALB ingress**: internet-facing, routes `/api/*` → backend, `/*` → frontend
- **K8s Secrets**: All 5 credentials stored as Kubernetes Secrets
- **Resource limits**: CPU (250m–1000m), Memory (512Mi–1Gi) on backend
- **Health probes**: liveness + readiness on both deployments

### Fixed — Security (17 issues resolved)
- Removed hardcoded AWS Account ID from `k8s-deploy.yaml` → `envsubst` placeholders
- Moved all API keys from plaintext env to Kubernetes Secrets
- Implemented `trading_interface/security/__init__.py` (was empty — auth not enforced)
- Parameterized CORS via `CORS_ALLOWED_ORIGINS` env var
- Added `sanitize_ticker()` regex validation on all user inputs

### Fixed — Architecture
- `ExecutionAgent.execute_approved_risk()` now actually called in `run_agent_loop()`
- `_build_portfolio_state()` calls real `BROKER_CLIENT.get_account()` and `.get_positions()`
- `MarketDataAgent` instantiated at module level (fixes broken per-request cache)
- Replaced `GLOBAL_POSITIONS/LOGS/INSIGHTS` in-memory lists with SQLAlchemy models

### Fixed — Trading Logic
- Real earnings dates via `yfinance .calendar` (removed hardcoded `days_to_earnings=14`)
- VIX fetch failure defaults to `99.0` (fail-safe) instead of `15.0` (silent gate bypass)
- `SELL_TO_CLOSE` validates existing long position before sizing
- `SyncWorker` drift uses per-share price (`market_value / quantity`) not total

### Fixed — Performance
- Replaced `requests.get()` with `httpx.AsyncClient` in movers endpoint
- SSE stream (`/api/stream`) replaces 4× concurrent 2-second polling loop
- `account_value` added to SSE payload (wires to frontend equity display)
- ESLint: fixed unused variable warnings in `App.jsx`

---

## [1.0.0] — Initial Release

- FastAPI backend with agent pipeline
- React frontend with basic dashboard
- Alpaca paper broker integration
- DeterministicRiskManager with 8 hard gates
- Basic Kubernetes deployment
