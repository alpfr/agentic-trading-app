# SOC 2 Compliance & Security Overview

This document describes how the Agentic Trading App aligns with the five AICPA Trust Service Criteria for SOC 2.

---

## 1. Security — Protection Against Unauthorized Access

### Authentication
- All API endpoints protected by `X-API-Key` header validation
- `require_api_key()` FastAPI dependency applied globally
- SSE endpoint accepts `?api_key=` query param (required for browser `EventSource`)
- Key stored in Kubernetes Secret — not in environment files or source code

### Input Validation
- All user-supplied ticker symbols validated against `^[A-Z]{1,5}$` regex
- `sanitize_ticker()` applied before any DB write or external API call
- Pydantic schema validation on all request bodies

### Rate Limiting
- `/api/trigger` enforces 10-second per-ticker cooldown (in-process token bucket)
- Yahoo Finance calls cached to avoid external API abuse

### Secret Management
- All credentials (OpenAI, Alpaca, App API key, DB URL) stored exclusively in Kubernetes Secrets
- Secrets injected as pod environment variables via `secretKeyRef`
- No secrets in `k8s-deploy.yaml`, no secrets in source control
- AWS Account ID never committed — substituted at deploy time via `envsubst`
- GitHub Actions secrets encrypted with repo public key (NaCl sealed box)

### Network Security
- Backend exposed only as `ClusterIP` — not directly reachable from internet
- All internet traffic routed through AWS ALB
- ECR image scanning enabled on push (detects CVEs in OS and dependencies)
- CORS origins configurable via `CORS_ALLOWED_ORIGINS` environment variable

### Container Security
- Minimal base images (python:3.11-slim, node:20-alpine)
- No root process in containers
- Read-only filesystem where possible
- Resource limits enforced (CPU: 250m–1000m, Memory: 512Mi–1Gi backend)

---

## 2. Availability — System Uptime and Resilience

### Kubernetes HA
- 2 replicas for both backend and frontend deployments
- Rolling update strategy: `maxSurge=1, maxUnavailable=0` — zero downtime deploys
- EKS managed node group autoscales 1–4 nodes based on demand

### Health Probes
- `livenessProbe`: GET `/health` every 20s — restarts unhealthy pods automatically
- `readinessProbe`: GET `/health` every 10s — removes pods from load balancer before restart
- Both probes configured on backend and frontend

### Load Balancing
- AWS ALB routes traffic only to healthy pods
- Multi-AZ node group distributes workload across availability zones

### Data Persistence
- SQLite (dev): ephemeral — lost on pod restart
- PostgreSQL via `DATABASE_URL` (production): persistent, survives pod restarts
- Audit logs are append-only — no accidental data loss from application code

---

## 3. Processing Integrity — Accurate and Complete Processing

### Deterministic Risk Engine
- All risk calculations use pure Python math — no LLM, no randomness
- 8 hard gates evaluated in sequence before any order reaches the broker
- `RiskRejected` events written to audit log with specific failure reason
- LLM signal (HOLD / BUY / SELL) cannot bypass any gate

### Idempotency
- Each order assigned a UUID `client_order_id` before broker submission
- Duplicate submissions (e.g., from retries) rejected by Alpaca based on `client_order_id`

### Reconciliation
- `SyncWorker` periodically compares broker positions vs internal DB positions
- Broker is always the source of truth
- Drift > 5% of portfolio triggers kill switch

### Fail-Safes
- VIX fetch failure → defaults to 99.0 (blocks new longs — fail-safe, not fail-open)
- Earnings date fetch failure → defaults to 999 days (no blackout triggered)
- LLM malformed output → defaults to HOLD signal

---

## 4. Confidentiality — Protection of Sensitive Information

### Data Classification
| Data | Classification | Storage |
|---|---|---|
| API keys | Secret | Kubernetes Secrets only |
| Trade history | Internal | SQLite/PostgreSQL (encrypted at rest in RDS) |
| Audit logs | Internal | DB — append-only |
| Market data | Public | Cached in DB for performance |

### Logging Policy
- No API keys, no secrets logged anywhere in application code
- No PII collected or stored
- Audit logs contain only: timestamp, agent, action, ticker, reason

### Transmission Security
- HTTPS recommended for production (configure ALB SSL termination + ACM certificate)
- Internal cluster traffic (pod-to-pod) stays within VPC — never traverses internet

---

## 5. Privacy — Personal Information Handling

This application does not collect, store, or process personal information (PII) in its default configuration. No user accounts, no personal data beyond what Alpaca stores in its own platform.

---

## Recommended Production Hardening

| Item | Current State | Recommended |
|---|---|---|
| TLS/HTTPS | HTTP (ALB) | Add ACM cert + HTTPS listener to ALB |
| WAF | None | Add AWS WAF to ALB for IP allowlist / rate limiting |
| Database encryption | SQLite (unencrypted) | RDS PostgreSQL with encryption at rest |
| Secrets rotation | Manual | AWS Secrets Manager with automatic rotation |
| Network policies | None | Add Kubernetes NetworkPolicy to restrict pod-to-pod traffic |
| Multi-replica rate limit | In-process (per pod) | Replace with Redis TTL key for cross-replica enforcement |
| Image signing | None | Add cosign image signing in CI/CD pipeline |
| Audit log integrity | DB rows | Export to append-only S3 bucket with object lock |
