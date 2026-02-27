# SOC 2 Compliance — Retirement Portfolio Advisor

## Control Summary

| Control | Status | Implementation |
|---------|--------|---------------|
| TLS / Encryption in transit | ✅ Active | ALB HTTPS + ACM wildcard `*.opssightai.com` + TLS 1.3 |
| Authentication | ✅ Implemented | JWT access (15 min) + refresh tokens (7 day) |
| MFA | ✅ Implemented | TOTP RFC 6238 — Google Authenticator / Authy |
| Rate limiting | ✅ Implemented | Per-IP sliding window via slowapi |
| Security headers | ✅ Implemented | HSTS, CSP, X-Frame-Options, Referrer-Policy, etc. |
| Audit logging | ✅ Implemented | Structured JSON → stdout → CloudWatch Logs |
| CORS | ✅ Hardened | Locked to `https://agentictradepulse.opssightai.com` |
| Secrets management | ✅ Implemented | Kubernetes secrets — never in source control |
| Token revocation | ✅ Implemented | JTI revocation list; logout invalidates immediately |
| Encryption at rest | ⚠️ Partial | SQLite plain; upgrade path: encrypted RDS (see §9) |
| Secrets rotation | ⚠️ Manual | K8s secret update + pod restart |
| VPC / network isolation | ⚠️ Basic | EKS default VPC; private subnets recommended |
| Log retention | ⚠️ Setup needed | CloudWatch log group + retention policy (see §6) |

---

## 1. TLS / Encryption in Transit

### Active Configuration

| Setting | Value |
|---------|-------|
| Certificate | ACM wildcard `*.opssightai.com` |
| Covers | `agentictradepulse.opssightai.com` + all future subdomains |
| HTTP redirect | Port 80 → 443 (enforced at ALB) |
| TLS policy | `ELBSecurityPolicy-TLS13-1-2-2021-06` |
| Minimum TLS version | TLS 1.2 |
| Preferred TLS version | TLS 1.3 |
| Invalid header fields | Dropped at ALB |

### Certificate Management

The wildcard cert `*.opssightai.com` is stored in ACM with SANs:
- `opssightai.com`
- `*.opssightai.com`

The CI/CD pipeline **auto-resolves** the cert ARN from ACM on every deploy — no manual ARN configuration needed.

Auto-resolve lookup order in `deploy.yml`:
1. Exact match: primary domain == `*.opssightai.com` + Status `ISSUED`
2. SAN scan: any `ISSUED` cert whose SubjectAlternativeNames includes `*.opssightai.com`
3. Fallback: any `ISSUED` cert containing `opssightai.com` in DomainName

Override by setting `ACM_CERT_ARN` in GitHub Secrets (bypasses auto-resolve).

### Cert Renewal

ACM **auto-renews** certificates 60 days before expiry as long as the DNS validation CNAME record remains in place. Never remove that CNAME record.

Verify renewal eligibility:
```bash
aws acm describe-certificate \
  --certificate-arn arn:aws:acm:us-east-1:713220200108:certificate/7a263fe4-a8d5-47cc-a361-8b0a85a4c29e \
  --region us-east-1 \
  --query "Certificate.{Status:Status,RenewalEligibility:RenewalEligibility}" \
  --output table
```

### If a Cert Fails Validation (`VALIDATION_TIMED_OUT`)

The DNS CNAME was not added within the 72-hour window. Fix:
```bash
# 1. Delete the failed cert
aws acm delete-certificate --certificate-arn <failed-arn> --region us-east-1

# 2. Request a new wildcard cert
aws acm request-certificate \
  --domain-name opssightai.com \
  --subject-alternative-names "*.opssightai.com" \
  --validation-method DNS \
  --region us-east-1

# 3. Get the validation CNAME immediately
aws acm describe-certificate \
  --certificate-arn arn:aws:acm:us-east-1:713220200108:certificate/7a263fe4-a8d5-47cc-a361-8b0a85a4c29e \
  --region us-east-1 \
  --query "Certificate.DomainValidationOptions[0].ResourceRecord" \
  --output table

# 4. Add the CNAME to Route 53 (replace NAME and VALUE from step 3)
ZONE_ID=$(aws route53 list-hosted-zones \
  --query "HostedZones[?Name=='opssightai.com.'].Id" \
  --output text | cut -d'/' -f3)

aws route53 change-resource-record-sets \
  --hosted-zone-id $ZONE_ID \
  --change-batch "{
    \"Changes\": [{
      \"Action\": \"CREATE\",
      \"ResourceRecordSet\": {
        \"Name\": \"<NAME>\",
        \"Type\": \"CNAME\",
        \"TTL\": 300,
        \"ResourceRecords\": [{\"Value\": \"<VALUE>\"}]
      }
    }]
  }"

# 5. Wait for ISSUED (2–5 min on Route 53)
aws acm describe-certificate --certificate-arn arn:aws:acm:us-east-1:713220200108:certificate/7a263fe4-a8d5-47cc-a361-8b0a85a4c29e \
  --region us-east-1 --query "Certificate.Status" --output text
```

---

## 2. Authentication

### Architecture
Replaced the static single API key model with a full JWT session system.

```
POST /api/auth/login  { username, password }
  → Password validated (bcrypt)
  → MFA enabled: returns { mfa_required: true, session_token }
  → MFA disabled: returns { access_token, refresh_token }

POST /api/auth/mfa/verify  { session_token, totp_code }
  → TOTP code verified (RFC 6238, ±30s window)
  → Returns { access_token, refresh_token }

GET/POST <protected endpoint>
  Authorization: Bearer <access_token>
  → JWT decoded, expiry checked, JTI checked vs revocation list
  → 401 if expired, revoked, or invalid signature
```

### Token Configuration

| Parameter | Value | Override |
|-----------|-------|---------|
| Access token TTL | 15 minutes | `JWT_ACCESS_TTL_MINUTES` env var |
| Refresh token TTL | 7 days | `JWT_REFRESH_TTL_DAYS` env var |
| Algorithm | HS256 | — |
| Signing key | 64-byte random hex | `JWT_SECRET` K8s secret |

### Backward Compatibility
`X-API-Key` header still accepted for:
- SSE stream (`/api/stream?api_key=...`) — EventSource API cannot set headers
- Service-to-service calls using the legacy key

### Initial Admin Setup
```bash
# 1. Generate bcrypt password hash
python3 -c "from passlib.hash import bcrypt; print(bcrypt.hash('your-strong-password'))"

# 2. Set in K8s secret
kubectl create secret generic trading-app-secrets \
  --namespace=agentic-trading-platform \
  --from-literal=admin-username="admin" \
  --from-literal=admin-password-hash="<bcrypt-hash>" \
  --from-literal=jwt-secret="$(openssl rand -hex 64)" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl rollout restart deployment/agentic-trading-backend \
  -n agentic-trading-platform
```

---

## 3. Multi-Factor Authentication (MFA)

### Protocol
TOTP (Time-based One-Time Password) per RFC 6238.
Compatible with: Google Authenticator, Authy, 1Password, Bitwarden.

### Enrolling MFA

```bash
# Step 1: Login and call setup endpoint
curl -H "Authorization: Bearer <access_token>" \
  https://agentictradepulse.opssightai.com/api/auth/mfa/setup

# Response includes:
# {
#   "totp_secret": "JBSWY3DPEHPK3PXP",
#   "provisioning_uri": "otpauth://totp/RetirementAdvisor:admin?secret=..."
# }

# Step 2: Store the secret in K8s
kubectl create secret generic trading-app-secrets \
  --namespace=agentic-trading-platform \
  --from-literal=admin-totp-secret="JBSWY3DPEHPK3PXP" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl rollout restart deployment/agentic-trading-backend \
  -n agentic-trading-platform

# Step 3: Scan the provisioning_uri as QR code
# qrencode -t ANSIUTF8 "otpauth://totp/..."
```

---

## 4. Rate Limiting

Per-IP sliding window enforced on all endpoints:

| Tier | Endpoints | Limit |
|------|-----------|-------|
| Auth | `/api/auth/*` | 5 req/min |
| Read | GET endpoints | 60 req/min |
| Write | POST / PUT / DELETE | 10 req/min |
| Global | All | 120 req/min |

On breach: `429 Too Many Requests` + `Retry-After: 60` header.
Every breach logged to security audit log with IP and path.

---

## 5. Security Response Headers

Every HTTP response includes:

| Header | Value | Protection |
|--------|-------|-----------|
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` | Forces HTTPS for 1 year |
| `X-Content-Type-Options` | `nosniff` | Prevents MIME sniffing |
| `X-Frame-Options` | `DENY` | Prevents clickjacking |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Limits referrer leakage |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` | Disables browser APIs |
| `Content-Security-Policy` | See below | XSS mitigation |

```
default-src 'self';
connect-src 'self';
script-src 'self' 'unsafe-inline';
style-src 'self' 'unsafe-inline' https://fonts.googleapis.com;
font-src 'self' https://fonts.gstatic.com;
img-src 'self' data:;
frame-ancestors 'none';
```

---

## 6. Audit Logging

### Format
JSON-Lines to stdout → Kubernetes → CloudWatch Logs:

```json
{
  "timestamp": "2026-02-27T20:00:00.000Z",
  "service": "retirement-advisor",
  "log_type": "security_audit",
  "event": "LOGIN_SUCCESS",
  "success": true,
  "username": "admin",
  "ip": "203.0.113.42",
  "user_agent": "Mozilla/5.0 ...",
  "detail": "MFA verified"
}
```

### Events Logged

| Event | Trigger |
|-------|---------|
| `LOGIN_SUCCESS` / `LOGIN_FAILED` | Password check result |
| `MFA_CHALLENGE_ISSUED` | Password OK — TOTP prompt sent |
| `MFA_SUCCESS` / `MFA_FAILED` | TOTP code result |
| `TOKEN_ISSUED` / `TOKEN_REFRESHED` / `TOKEN_REVOKED` | Token lifecycle |
| `TOKEN_INVALID` | Expired, malformed, or tampered token |
| `API_KEY_ACCEPTED` / `API_KEY_REJECTED` | Legacy API key auth |
| `LOGOUT` | Explicit logout |
| `RATE_LIMIT_BREACH` | IP exceeded rate limit |

### CloudWatch Setup

```bash
aws logs create-log-group \
  --log-group-name /retirement-advisor/security-audit \
  --region us-east-1

aws logs put-retention-policy \
  --log-group-name /retirement-advisor/security-audit \
  --retention-in-days 90
```

Install the EKS CloudWatch observability add-on to ship pod stdout automatically:
```bash
aws eks create-addon \
  --cluster-name agentic-trading-cluster \
  --addon-name amazon-cloudwatch-observability \
  --region us-east-1
```

---

## 7. CORS

Locked to `https://agentictradepulse.opssightai.com`.
No localhost default in production — `CORS_ALLOWED_ORIGINS` env var must be set explicitly.

```bash
# Update via K8s secret
kubectl create secret generic trading-app-secrets \
  --namespace=agentic-trading-platform \
  --from-literal=cors-allowed-origins="https://agentictradepulse.opssightai.com" \
  --dry-run=client -o yaml | kubectl apply -f -
```

---

## 8. Secrets Management

All secrets stored in Kubernetes Secrets — never in source control or container images.

| Secret key | Description | Generation |
|------------|-------------|-----------|
| `jwt-secret` | JWT signing key | `openssl rand -hex 64` |
| `admin-username` | Admin login | Choose username |
| `admin-password-hash` | Bcrypt password hash | `python3 -c "from passlib.hash import bcrypt; print(bcrypt.hash('pw'))"` |
| `admin-totp-secret` | TOTP MFA secret | `GET /api/auth/mfa/setup` |
| `app-api-key` | Legacy API key (SSE) | `openssl rand -hex 32` |
| `openai-api-key` | GPT-4o-mini | OpenAI dashboard |
| `alpaca-api-key` | Alpaca paper | Alpaca dashboard |
| `alpaca-secret-key` | Alpaca paper | Alpaca dashboard |
| `cors-allowed-origins` | Allowed CORS origins | `https://agentictradepulse.opssightai.com` |
| `database-url` | DB connection | `sqlite:////app/data/trading.db` |

### Rotation

```bash
kubectl create secret generic trading-app-secrets \
  --namespace=agentic-trading-platform \
  --from-literal=jwt-secret="$(openssl rand -hex 64)" \
  --from-literal=app-api-key="$(openssl rand -hex 32)" \
  # ... all other secrets ...
  --dry-run=client -o yaml | kubectl apply -f -

kubectl rollout restart deployment/agentic-trading-backend \
  -n agentic-trading-platform
# Note: all active JWTs are invalidated when jwt-secret rotates — users must log in again
```

---

## 9. Remaining Gaps & Remediation

### Encryption at Rest — upgrade to RDS
```bash
aws rds create-db-instance \
  --db-instance-identifier retirement-advisor-db \
  --db-instance-class db.t3.micro \
  --engine postgres \
  --storage-encrypted \
  --master-username admin \
  --master-user-password "<strong-password>" \
  --backup-retention-period 7 \
  --region us-east-1
```

### AWS WAF
```bash
# Attach WAF ACL to ALB — uncomment in k8s-deploy.yaml:
# alb.ingress.kubernetes.io/wafv2-acl-arn: "<waf-acl-arn>"
```

### Redis for Token Revocation
Replace the in-process `_REVOKED_TOKENS` set with ElastiCache Redis so revoked tokens
persist across pod restarts and multiple replicas.

### VPC Private Subnets
Move EKS nodes to private subnets with NAT gateway — only ALB should be public-facing.

### CloudWatch Alarms
```bash
# Alert on 5+ failed logins in 5 minutes
aws cloudwatch put-metric-alarm \
  --alarm-name "BruteForceAttempt" \
  --namespace "RetirementAdvisor/Security" \
  --metric-name "LOGIN_FAILED" \
  --period 300 --threshold 5 \
  --comparison-operator GreaterThanThreshold \
  --alarm-actions "<SNS_TOPIC_ARN>"
```
