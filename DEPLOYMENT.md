# Deployment Guide

## Standard Deployment (GitHub Actions)

Every push to `master` triggers the 4-job pipeline automatically.

```
Push → Lint → Build/Push ECR → Provision EKS → Deploy (~8 min total)
```

To deploy manually: push any commit to `master`.

---

## Live URL

The app is accessible at:

```
https://agentictradepulse.opssightai.com
```

If you need the raw ALB hostname (e.g. to update DNS):
```bash
kubectl get ingress agentic-trading-ingress \
  -n agentic-trading-platform \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
```

Or run **Actions → Get App URL → Run workflow** in GitHub.

---

## Required GitHub Secrets

Set these in **Settings → Secrets → Actions**:

| Secret | Description |
|--------|-------------|
| `AWS_ACCESS_KEY_ID` | IAM user with EKS + ECR permissions |
| `AWS_SECRET_ACCESS_KEY` | IAM user secret |
| `OPENAI_API_KEY` | GPT-4o-mini |
| `ALPACA_API_KEY` | Alpaca paper account |
| `ALPACA_SECRET_KEY` | Alpaca paper account |
| `APP_API_KEY` | Any strong random string — frontend auth |
| `DATABASE_URL` | `sqlite:////app/data/trading.db` or PostgreSQL DSN |

---

## AWS Infrastructure

| Resource | Name | Notes |
|----------|------|-------|
| EKS cluster | `agentic-trading-cluster` | us-east-1, t3.medium nodes |
| Node group | `trading-nodes` | 1–3 nodes, auto-scaling |
| ECR repo (backend) | `agentic-trading-backend` | |
| ECR repo (frontend) | `agentic-trading-frontend` | |
| ALB | Provisioned by controller | URL changes on re-create |
| IAM role | `aws-load-balancer-controller` | IRSA for ALB controller |
| K8s secret | `trading-app-secrets` | All env vars |
| Namespace | `agentic-trading-platform` | |

---

## Kubernetes Resources

```
Namespace: agentic-trading-platform
├── Deployment: agentic-trading-backend   (2 replicas, 256-512Mi RAM)
├── Deployment: agentic-trading-frontend  (2 replicas, 128-256Mi RAM)
├── Service: agentic-trading-backend      (ClusterIP :8000)
├── Service: agentic-trading-frontend     (ClusterIP :80)
├── Ingress: agentic-trading-ingress       (ALB, HTTP)
└── Secret: trading-app-secrets
```

---

## Update Watchlist at Runtime

No redeploy needed — call the API:

```bash
curl -X PUT https://https://agentictradepulse.opssightai.com/api/watchlist \
  -H "X-API-Key: <APP_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"watchlist": ["VTI","SCHD","QQQ","JNJ","PG","MSFT","NVDA","AAPL","AMZN"]}'
```

---

## Rotate Secrets

```bash
# Update K8s secret
kubectl create secret generic trading-app-secrets \
  --namespace=agentic-trading-platform \
  --from-literal=openai-api-key="<NEW>" \
  --from-literal=alpaca-api-key="<NEW>" \
  --from-literal=alpaca-secret-key="<NEW>" \
  --from-literal=app-api-key="<NEW>" \
  --from-literal=database-url="<NEW>" \
  --dry-run=client -o yaml | kubectl apply -f -

# Restart pods to pick up new secrets
kubectl rollout restart deployment/agentic-trading-backend \
  -n agentic-trading-platform
```

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Rollout stuck | Pod crashing on startup | `kubectl logs -n agentic-trading-platform deploy/agentic-trading-backend` |
| No data on page | API key mismatch | Check `APP_API_KEY` matches in K8s secret and frontend env |
| 503 on all routes | ALB not yet provisioned | Wait 3–5 min after first deploy |
| Blank watchlist | DB reset after pod restart | SQLite is ephemeral — trigger a scan to repopulate |
| AI returning all HOLDs | Missing OPENAI_API_KEY | Check K8s secret; mock client is active as fallback |
