## v3.1.0 — SOC 2 Security + Domain + TLS (2026-02-27)

### Security
- JWT authentication replacing static API key (access 15 min, refresh 7 days)
- TOTP MFA per RFC 6238 — Google Authenticator / Authy compatible
- Per-IP rate limiting via slowapi (auth 5/min, read 60/min, write 10/min)
- Security response headers: HSTS, CSP, X-Frame-Options, Referrer-Policy
- Structured JSON security audit log → stdout → CloudWatch Logs
- CORS locked to `https://agentictradepulse.opssightai.com`
- 6 new auth endpoints: `/api/auth/login`, `/mfa/verify`, `/refresh`, `/logout`, `/mfa/setup`, `/me`

### Infrastructure
- Domain: `agentictradepulse.opssightai.com`
- ACM wildcard certificate `*.opssightai.com` (covers all subdomains)
- ALB TLS: HTTP → HTTPS redirect, TLS 1.3, `ELBSecurityPolicy-TLS13-1-2-2021-06`
- CI/CD auto-resolves ACM cert ARN by domain — no manual ARN management
- ACM cert lookup checks primary domain, SANs, and fallback
- Host-based ingress routing locked to `agentictradepulse.opssightai.com`
- `drop_invalid_header_fields` enabled on ALB

### Documentation
- CLI_GUIDE.md: TLS cert commands, ALB listener cert check, updated with domain
- DEPLOYMENT.md: wildcard cert section, DNS setup, cert renewal, full secrets table
- SOC2_COMPLIANCE.md: complete rewrite with cert lifecycle, VALIDATION_TIMED_OUT fix, all controls

---

# Changelog

## v3.0.0 — Retirement Portfolio Advisor (2026-02-27)

**Major pivot: day trading → retirement investment advisory**

### New Features
- **Retirement advisor AI prompt** — evaluates stocks as long-term business investments; category-specific rules for ETFs, dividend stocks, and growth stocks
- **RetirementRiskManager** — 7-gate deterministic risk system tuned for buy-and-hold; 60% confidence gate, 30-day min hold, 10% concentration cap, soft trailing stop alert
- **RetirementConfig** — default watchlist of 8 holdings (VTI, SCHD, QQQ, JNJ, PG, MSFT, NVDA, AAPL) with ETF/Dividend/Growth target allocations
- **Rebalance engine** — weekly category drift analysis (ETF 40% / Dividend 25% / Growth 35%); BUY_MORE / TRIM / ON_TARGET per category
- **Alert system** — price drop alerts (>5% WARNING, >10% CRITICAL), trailing stop breaches, dividend payout ratio warnings, 52-week drawdown opportunities
- **RetirementScheduler** — daily scan at 10:00 ET + weekly Monday rebalance; no EOD auto-close
- **Category-aware LLM prompts** — ticker category injected into every AI evaluation

### Removed
- EOD auto-close at 15:45 ET
- ATR-based intraday stops
- 20-minute scan cadence
- Day trading system prompt
- BWIN (OTC, Alpaca-unsupported)

---

## v2.1.0 — Event Loop Fix (2026-02-27)

- Fixed: yfinance blocking calls in async functions caused pod readiness probe failures
- All `yf.download()` and `yf.Ticker()` calls moved to `run_in_executor` thread pool
- Added 90s startup delay before first scheduler tick

---

## v2.0.0 — Day Trading Watchlist + CI/CD (2026-02-27)

### Bug Fixes (from MVP evaluation)
1. **Live PnL** — position `current_price` now refreshed on every agent scan and every 5-min reconciliation cycle (was frozen at entry)
2. **LLM alignment** — prompt horizon matched to risk manager configuration
3. **Order type** — MARKET+DAY orders for intraday; GTC replaced (was carrying over to next morning)
4. **SyncWorker** — broker reconciliation wired into production app (was MockDB-only)
5. **Risk manager singleton** — `RISK_MANAGER` promoted to module-level; config no longer discarded on each call
6. **BWIN removed** — OTC security unsupported by Alpaca

### Features
- Day trading watchlist with scheduler
- Harness CI/CD → GitHub Actions 4-job pipeline
- Configurable risk parameters (ATR multiplier, position cap)
- EOD auto-close at 15:45 ET

---

## v1.0.0 — Initial MVP (2026-02-26)

- FastAPI backend with agent pipeline (MarketData → Strategy → Risk → Execution)
- React frontend with SSE live stream
- Alpaca paper broker integration
- DeterministicRiskManager (8 gates)
- EKS deployment with ALB ingress
- Audit log + agent insights
