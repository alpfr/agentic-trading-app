# Deployment Guide

## Standard Deployment (GitHub Actions)

Every push to `master` triggers the 4-job pipeline automatically.

```
Push → Lint → Build/Push ECR → Provision EKS → Deploy (~8 min total)
```

To deploy manually: push any commit to `master`.

---

## Live URL

```
https://agentictradepulse.opssightai.com
```

Get the raw ALB hostname (needed for DNS):
```bash
kubectl get ingress agentic-trading-ingress \
  -n agentic-trading-platform \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
```

---

## Domain & DNS

| Record | Type | Points To |
|--------|------|-----------|
| `agentictradepulse.opssightai.com` | CNAME (or Alias) | ALB hostname from above |

**Route 53 users** — use an Alias A record instead of CNAME (free + faster):
```bash
# Get hosted zone ID
ZONE_ID=$(aws route53 list-hosted-zones \
  --query "HostedZones[?Name=='opssightai.com.'].Id" \
  --output text | cut -d'/' -f3)
echo $ZONE_ID
# Then create the alias record in the Route 53 console pointing to the ALB
```

---

## TLS Certificate

The ACM wildcard certificate `*.opssightai.com` covers all subdomains including
`agentictradepulse.opssightai.com`. The CI/CD pipeline auto-resolves the cert ARN
from ACM — no manual ARN copying needed.

### Certificate Validation (first-time only)

If the cert status is `PENDING_VALIDATION`, add the DNS CNAME validation record:

```bash
# Get the validation record
aws acm describe-certificate \
  --certificate-arn arn:aws:acm:us-east-1:713220200108:certificate/7a263fe4-a8d5-47cc-a361-8b0a85a4c29e \
  --region us-east-1 \
  --query "Certificate.DomainValidationOptions[0].ResourceRecord" \
  --output table

# Add it automatically via Route 53
ZONE_ID=$(aws route53 list-hosted-zones \
  --query "HostedZones[?Name=='opssightai.com.'].Id" \
  --output text | cut -d'/' -f3)

NAME=$(aws acm describe-certificate --certificate-arn arn:aws:acm:us-east-1:713220200108:certificate/7a263fe4-a8d5-47cc-a361-8b0a85a4c29e \
  --region us-east-1 \
  --query "Certificate.DomainValidationOptions[0].ResourceRecord.Name" \
  --output text)

VALUE=$(aws acm describe-certificate --certificate-arn arn:aws:acm:us-east-1:713220200108:certificate/7a263fe4-a8d5-47cc-a361-8b0a85a4c29e \
  --region us-east-1 \
  --query "Certificate.DomainValidationOptions[0].ResourceRecord.Value" \
  --output text)

aws route53 change-resource-record-sets \
  --hosted-zone-id $ZONE_ID \
  --change-batch "{
    \"Changes\": [{
      \"Action\": \"CREATE\",
      \"ResourceRecordSet\": {
        \"Name\": \"$NAME\",
        \"Type\": \"CNAME\",
        \"TTL\": 300,
        \"ResourceRecords\": [{\"Value\": \"$VALUE\"}]
      }
    }]
  }"
```

Validation takes 2–5 minutes on Route 53. Check status:
```bash
aws acm describe-certificate --certificate-arn arn:aws:acm:us-east-1:713220200108:certificate/7a263fe4-a8d5-47cc-a361-8b0a85a4c29e \
  --region us-east-1 \
  --query "Certificate.Status" --output text
```

### If a cert expires or times out (VALIDATION_TIMED_OUT)

Delete the failed cert and request a new one:
```bash
# Delete failed cert
aws acm delete-certificate --certificate-arn <failed-arn> --region us-east-1

# Request new wildcard cert
aws acm request-certificate \
  --domain-name opssightai.com \
  --subject-alternative-names "*.opssightai.com" \
  --validation-method DNS \
  --region us-east-1
```
Then add the DNS validation CNAME immediately (see above). The 72-hour validation
window starts from the moment you request — don't wait.

---

## Required GitHub Secrets

Set in **Settings → Secrets → Actions**:

| Secret | Description | Generate with |
|--------|-------------|---------------|
| `AWS_ACCESS_KEY_ID` | IAM user with EKS + ECR permissions | IAM console |
| `AWS_SECRET_ACCESS_KEY` | IAM user secret | IAM console |
| `OPENAI_API_KEY` | GPT-4o-mini | OpenAI dashboard |
| `ALPACA_API_KEY` | Alpaca paper account | Alpaca dashboard |
| `ALPACA_SECRET_KEY` | Alpaca paper account | Alpaca dashboard |
| `APP_API_KEY` | Legacy API key + SSE auth | `openssl rand -hex 32` |
| `JWT_SECRET` | JWT signing key | `openssl rand -hex 64` |
| `ADMIN_USERNAME` | Admin login username | Choose one |
| `ADMIN_PASSWORD_HASH` | Bcrypt hash of admin password | `python3 -c "from passlib.hash import bcrypt; print(bcrypt.hash('pw'))"` |
| `ADMIN_TOTP_SECRET` | MFA secret (after enrollment) | `GET /api/auth/mfa/setup` |
| `CORS_ALLOWED_ORIGINS` | Allowed CORS origins | `https://agentictradepulse.opssightai.com` |
| `DATABASE_URL` | DB connection string | `sqlite:////app/data/trading.db` |
| `ACM_CERT_ARN` | *(Optional)* Pin cert ARN manually | `aws acm list-certificates` |

> `ACM_CERT_ARN` is optional — the pipeline auto-resolves the wildcard cert.
> Only set it if you want to pin a specific cert and bypass auto-resolution.

---

## AWS Infrastructure

| Resource | Name | Notes |
|----------|------|-------|
| EKS cluster | `agentic-trading-cluster` | us-east-1, t3.medium |
| Node group | `trading-nodes` | 1–3 nodes, auto-scaling |
| ECR repo (backend) | `agentic-trading-backend` | |
| ECR repo (frontend) | `agentic-trading-frontend` | |
| ACM certificate | `*.opssightai.com` | Wildcard — covers all subdomains |
| ALB | `agentic-trading-alb` | Provisioned by AWS LB controller |
| IAM role | `aws-load-balancer-controller` | IRSA for ALB controller |
| K8s namespace | `agentic-trading-platform` | |
| K8s secret | `trading-app-secrets` | All env vars |

---

## Kubernetes Resources

```
Namespace: agentic-trading-platform
├── Deployment: agentic-trading-backend    (2 replicas, 256–512Mi RAM)
├── Deployment: agentic-trading-frontend   (2 replicas, 128–256Mi RAM)
├── Service: agentic-trading-backend       (ClusterIP :8000)
├── Service: agentic-trading-frontend      (ClusterIP :80)
├── Ingress: agentic-trading-ingress       (ALB, HTTPS, host: agentictradepulse.opssightai.com)
└── Secret: trading-app-secrets
```

---

## Update Watchlist at Runtime

No redeploy needed:
```bash
curl -X PUT https://agentictradepulse.opssightai.com/api/watchlist \
  -H "X-API-Key: <APP_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"watchlist": ["VTI","SCHD","QQQ","JNJ","PG","MSFT","NVDA","AAPL"]}'
```

---

## Rotate Secrets

```bash
kubectl create secret generic trading-app-secrets \
  --namespace=agentic-trading-platform \
  --from-literal=jwt-secret="$(openssl rand -hex 64)" \
  --from-literal=app-api-key="$(openssl rand -hex 32)" \
  --from-literal=openai-api-key="<NEW>" \
  --from-literal=alpaca-api-key="<NEW>" \
  --from-literal=alpaca-secret-key="<NEW>" \
  --from-literal=admin-username="admin" \
  --from-literal=admin-password-hash="<NEW-BCRYPT>" \
  --from-literal=admin-totp-secret="<NEW>" \
  --from-literal=cors-allowed-origins="https://agentictradepulse.opssightai.com" \
  --from-literal=database-url="<NEW>" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl rollout restart deployment/agentic-trading-backend \
  -n agentic-trading-platform
```

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `ERR_CERT_COMMON_NAME_INVALID` | Wrong cert attached to ALB | Check cert SANs include `*.opssightai.com`; redeploy |
| `VALIDATION_TIMED_OUT` on cert | DNS CNAME not added within 72h | Delete cert, request new, add CNAME immediately |
| Rollout stuck | Pod crashing | `kubectl logs -n agentic-trading-platform deploy/agentic-trading-backend` |
| 503 on all routes | ALB not provisioned yet | Wait 3–5 min; check `kubectl get ingress -n agentic-trading-platform` |
| No data on page | API key mismatch | Verify `APP_API_KEY` matches in K8s secret and frontend |
| Blank watchlist | DB reset after pod restart | SQLite is ephemeral — trigger Scan All to repopulate |
| AI returning all HOLDs | Missing `OPENAI_API_KEY` | Check K8s secret; mock client activates as fallback |
| 401 on all endpoints | `JWT_SECRET` not set | Add `jwt-secret` to K8s secret and restart pod |
