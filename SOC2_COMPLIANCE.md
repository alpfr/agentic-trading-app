# Security & Compliance Notes

## Authentication

- All API endpoints require `X-API-Key` header
- Key stored as Kubernetes secret, injected at runtime
- Frontend receives key via Vite build-time env var (`VITE_API_KEY`)
- SSE endpoint uses query param (`?api_key=...`) — EventSource API limitation

## Secrets Management

| Secret | Storage | Rotation |
|--------|---------|---------|
| OpenAI API key | GitHub Actions (NaCl encrypted) + K8s secret | Rotate in GitHub Settings → Secrets |
| Alpaca credentials | GitHub Actions + K8s secret | Rotate via `kubectl create secret --dry-run apply` |
| APP_API_KEY | GitHub Actions + K8s secret | Generate new random string |

## Data Handling

- No personally identifiable information stored
- All position data is paper trading — no real financial data
- SQLite database is pod-local and ephemeral (resets on pod restart)
- No external logging services in current deployment

## Rate Limiting

- yfinance calls: 10-second stagger between tickers in scheduler
- 60-second market data cache per ticker
- 6-hour fundamental data cache per ticker
- `/api/trigger`: 10-second cooldown per ticker

## AI Safety Constraints

The LLM (GPT-4o-mini) cannot:
- Bypass any of the 7 risk gates — they are pure Python math
- Directly call the broker — all execution goes through `ExecutionAgent`
- Access the database — reads/writes only via `app.py` endpoints
- Hallucinate a trade — JSON schema is strictly validated by Pydantic before risk evaluation

## Recommended Production Hardening

| Item | Current | Recommended |
|------|---------|-------------|
| Database | SQLite (ephemeral) | PostgreSQL RDS with persistent EBS |
| TLS | ALB HTTP | ALB HTTPS with ACM certificate |
| Auth | Single API key | JWT with expiry + refresh |
| Logging | Pod stdout | CloudWatch Logs |
| Monitoring | None | Prometheus + Grafana |
| Secret rotation | Manual | AWS Secrets Manager with auto-rotation |
