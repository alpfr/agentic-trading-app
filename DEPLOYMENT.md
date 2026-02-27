# Deployment Guide

## Option 1 — GitHub Actions (Recommended)

Every push to `master` automatically runs the full pipeline:
**Lint → Build → Provision EKS → Deploy**

### First-time setup

**Step 1 — Set GitHub Secrets**

Go to `https://github.com/alpfr/agentic-trading-app/settings/secrets/actions` and add:

| Secret | Description |
|---|---|
| `AWS_ACCESS_KEY_ID` | IAM access key |
| `AWS_SECRET_ACCESS_KEY` | IAM secret key |
| `OPENAI_API_KEY` | GPT-4o-mini key (omit for mock LLM) |
| `ALPACA_API_KEY` | Alpaca paper account key |
| `ALPACA_SECRET_KEY` | Alpaca paper account secret |
| `APP_API_KEY` | Random secret: `openssl rand -hex 32` |
| `DATABASE_URL` | PostgreSQL URL (or leave as `sqlite:///./trading_app.db`) |

**Step 2 — Push to master**

```bash
git push origin master
```

The workflow runs automatically. Cluster creation takes ~20 minutes on first run; subsequent deploys take ~8 minutes.

**Step 3 — Get your URL**

After deploy, run the **Get App URL** workflow:
- Go to `Actions → Get App URL → Run workflow`
- Open the run → check the **Summary** tab for the ALB URL

---

## Option 2 — Local Script

### Prerequisites
```bash
# Install tools (macOS/Linux)
chmod +x install-prerequisites.sh && ./install-prerequisites.sh
# Installs: AWS CLI v2, eksctl, kubectl, helm
```

### Run
```bash
chmod +x deploy.sh && ./deploy.sh
```

The script handles everything — ECR repos, Docker builds, EKS cluster, ALB controller, K8s secrets, and deployment. The live URL is printed at the end.

---

## GitHub Actions Workflows

| Workflow | Trigger | Duration | Purpose |
|---|---|---|---|
| `deploy.yml` | Push to `master` | ~25 min (first) / ~8 min | Full CI/CD pipeline |
| `get-app-url.yml` | Manual | ~30 sec | Print live ALB URL + pod status |
| `destroy.yml` | Manual (type `DESTROY`) | ~15 min | Tear down all AWS resources |

---

## AWS Infrastructure Created

| Resource | Name | Notes |
|---|---|---|
| EKS Cluster | `agentic-trading-cluster` | v1.29, us-east-1 |
| Node Group | `agentic-trading-nodes` | t3.medium, 2 nodes (autoscales 1–4) |
| Namespace | `agentic-trading-platform` | — |
| ECR Repos | `agentic-trading-backend` / `agentic-trading-frontend` | Scan on push |
| ALB | `agentic-trading-alb` | Internet-facing, HTTP |
| IAM Policy | `AWSLoadBalancerControllerIAMPolicy` | For ALB controller |
| K8s Secret | `trading-app-secrets` | 5 keys: OpenAI, Alpaca×2, App, DB |

---

## Kubernetes Resources

```
Namespace: agentic-trading-platform
├── Deployment: agentic-trading-backend   (2 replicas)
│   ├── CPU:    250m–1000m
│   ├── Memory: 512Mi–1Gi
│   ├── Liveness:  GET /health every 20s
│   └── Readiness: GET /health every 10s
├── Deployment: agentic-trading-frontend  (2 replicas)
│   ├── CPU:    100m–250m
│   ├── Memory: 128Mi–256Mi
│   ├── Liveness:  GET / every 15s
│   └── Readiness: GET / every 10s
├── Service: agentic-trading-backend   (ClusterIP :8000)
├── Service: agentic-trading-frontend  (ClusterIP :80)
└── Ingress: agentic-trading-ingress   (ALB, internet-facing)
    ├── /api/*  → backend:8000
    ├── /health → backend:8000
    └── /*       → frontend:80
```

---

## Scaling

The backend is stateless (all state in the database). Scale horizontally any time:

```bash
kubectl scale deployment agentic-trading-backend \
  --replicas=3 -n agentic-trading-platform
```

> Note: The in-memory `_trigger_last_called` rate-limit dict is per-process.
> For multi-replica rate limiting, replace with a Redis TTL key.

---

## Updating the Watchlist

Via API (from any HTTP client):
```bash
curl -X PUT http://<ALB_URL>/api/watchlist \
  -H "X-API-Key: your-app-api-key" \
  -H "Content-Type: application/json" \
  -d '{"tickers": ["AAOI", "BWIN", "DELL", "FIGS", "SSL"]}'
```

Via the frontend: `⭐ Watchlist` tab → the current watchlist and config are shown in the Config Panel.

---

## Secrets Rotation

```bash
# Rotate APP_API_KEY
kubectl create secret generic trading-app-secrets \
  --from-literal=app-api-key="$(openssl rand -hex 32)" \
  --dry-run=client -o yaml \
  -n agentic-trading-platform | kubectl apply -f -

kubectl rollout restart deployment/agentic-trading-backend \
  -n agentic-trading-platform
```

Update `APP_API_KEY` in GitHub Secrets and redeploy frontend to match.

---

## Teardown

To destroy all AWS resources:
1. Go to `Actions → Destroy EKS Cluster → Run workflow`
2. Type `DESTROY` in the confirmation field
3. Click Run

This deletes: ALB → namespace → EKS cluster → node group → VPC resources.
ECR repos and IAM policies are **not** deleted (to preserve images and avoid IAM conflicts on re-deploy).

---

## Troubleshooting

**Pods not starting**
```bash
kubectl describe pod -n agentic-trading-platform
kubectl logs -n agentic-trading-platform deploy/agentic-trading-backend
```

**ALB not provisioning**
```bash
kubectl describe ingress agentic-trading-ingress -n agentic-trading-platform
kubectl logs -n kube-system deploy/aws-load-balancer-controller
```

**Health check failing**
```bash
curl http://<ALB_URL>/health
# Expected: {"status":"ok","timestamp":"..."}
```

**Movers showing empty**
The movers endpoint uses a two-tier strategy: Yahoo Finance screener (primary) with a 40-ticker watchlist fallback. If both fail, check backend logs for Yahoo Finance connectivity issues from the EKS nodes.

**Agent not trading**
- Check `/api/logs` for rejection reasons
- Common: VIX too high (> 35), earnings blackout (within 3 days), buying power insufficient
- Market hours: agent only runs Mon–Fri 09:35–15:40 ET
