# Deployment Guide

## Local Development

### Backend
```bash
cd backend
cp .env.example .env    # Fill in your values
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

### Frontend
```bash
cd frontend
cp .env.example .env    # Set VITE_API_BASE_URL and VITE_API_KEY
npm install
npm run dev             # Runs on http://localhost:5173
```

---

## Docker (Local Compose)

```bash
# Backend
docker build -t trading-backend ./backend
docker run -p 8000:8000 \
  -e APP_API_KEY=your-secret \
  -e OPENAI_API_KEY=sk-... \
  trading-backend

# Frontend
docker build -t trading-frontend ./frontend
docker run -p 80:80 trading-frontend
```

---

## AWS EKS Production Deployment

### Prerequisites
- EKS cluster running
- AWS Load Balancer Controller installed
- ECR repositories created for both images
- RDS PostgreSQL instance (recommended over SQLite)

### Step 1 — Create Kubernetes Secrets

```bash
kubectl create secret generic trading-app-secrets \
  --from-literal=openai-api-key="sk-..." \
  --from-literal=alpaca-api-key="PK..." \
  --from-literal=alpaca-secret-key="..." \
  --from-literal=app-api-key="$(openssl rand -hex 32)" \
  --from-literal=database-url="postgresql://user:pass@rds-host:5432/trading"
```

> Never put secrets in `k8s-deploy.yaml` or commit them to source control.

### Step 2 — Build & Push to ECR

```bash
export AWS_ACCOUNT_ID=<your-account-id>
export AWS_REGION=us-east-1
export ECR_BASE=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

# Authenticate
aws ecr get-login-password --region $AWS_REGION | \
  docker login --username AWS --password-stdin $ECR_BASE

# Backend
docker build -t $ECR_BASE/agentic-trading-backend:latest ./backend
docker push $ECR_BASE/agentic-trading-backend:latest

# Frontend
docker build -t $ECR_BASE/agentic-trading-frontend:latest ./frontend
docker push $ECR_BASE/agentic-trading-frontend:latest
```

### Step 3 — Deploy with envsubst

```bash
export AWS_ACCOUNT_ID=<your-account-id>
export AWS_REGION=us-east-1
envsubst < k8s-deploy.yaml | kubectl apply -f -
```

### Step 4 — Verify

```bash
kubectl get pods
kubectl get ingress agentic-trading-ingress
# Get the ALB DNS name from the ingress — this is your app URL
```

### Step 5 — Health Check

```bash
ALB_URL=$(kubectl get ingress agentic-trading-ingress -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
curl http://$ALB_URL/health
# Expected: {"status":"ok","timestamp":"..."}
```

---

## Scaling

The backend is stateless (all state in PostgreSQL). Scale horizontally:

```bash
kubectl scale deployment agentic-trading-backend --replicas=3
```

> The in-memory `_trigger_last_called` rate-limit dict is per-process.
> For multi-replica rate limiting, move it to Redis with a TTL key.

---

## Database

### SQLite (default — dev only)
Data lives in `./trading_app.db` inside the container. Lost on pod restart. Never use in production.

### PostgreSQL (production)
Set `DATABASE_URL` secret to your RDS connection string. Tables are auto-created on startup via `Base.metadata.create_all()`.

---

## Secrets Rotation

To rotate the `APP_API_KEY`:
```bash
kubectl create secret generic trading-app-secrets \
  --from-literal=app-api-key="$(openssl rand -hex 32)" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl rollout restart deployment/agentic-trading-backend
```

Update `VITE_API_KEY` in your frontend build and redeploy frontend.
