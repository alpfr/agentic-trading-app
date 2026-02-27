# SOC 2 Compliance — Retirement Portfolio Advisor

## Control Summary

| Control | Status | Implementation |
|---------|--------|---------------|
| TLS / Encryption in transit | ✅ Ready | ALB HTTPS + ACM + TLS 1.3 minimum |
| Authentication | ✅ Implemented | JWT (15 min) + refresh tokens (7 day) |
| MFA | ✅ Implemented | TOTP RFC 6238 (Google Authenticator) |
| Rate limiting | ✅ Implemented | Per-IP sliding window via slowapi |
| Security headers | ✅ Implemented | HSTS, CSP, X-Frame-Options, etc. |
| Audit logging | ✅ Implemented | Structured JSON → stdout → CloudWatch |
| CORS | ✅ Hardened | Env-driven, no localhost default in prod |
| Secrets management | ✅ Implemented | K8s secrets, never in source code |
| Token revocation | ✅ Implemented | JTI revocation list; logout invalidates |
| Encryption at rest | ⚠️ Partial | SQLite plain; upgrade path: encrypted RDS |
| Secrets rotation | ⚠️ Manual | K8s secret update + pod restart |
| VPC / network isolation | ⚠️ Basic | EKS default VPC; no private subnets yet |
| Log retention | ⚠️ Setup needed | CloudWatch log group + retention policy |

---

## 1. TLS / Encryption in Transit

### Current Setup
ALB is configured with:
- `listen-ports: '[{"HTTP":80},{"HTTPS":443}]'`
- `ssl-redirect: '443'` — all HTTP traffic redirected to HTTPS
- `ssl-policy: ELBSecurityPolicy-TLS13-1-2-2021-06` — TLS 1.2 minimum, TLS 1.3 preferred

### Certificate & Domain

The certificate for `opssightai.com` already exists in ACM.
The CI/CD pipeline **automatically resolves** the cert ARN from ACM by domain name —
no manual ARN copying needed.

To verify the cert is found:
```bash
aws acm list-certificates --region us-east-1 \
  --query "CertificateSummaryList[?contains(DomainName,'opssightai.com')]" \
  --output table
```

#### DNS — point the subdomain to the ALB
After first deployment, create a CNAME in your DNS provider:

```
agentictradepulse.opssightai.com  CNAME  <ALB-hostname>
```

Get the ALB hostname:
```bash
kubectl get ingress agentic-trading-ingress \
  -n agentic-trading-platform \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
```

If your DNS is on Route 53, use an **Alias record** instead of CNAME:
```bash
# Get your hosted zone ID
aws route53 list-hosted-zones \
  --query "HostedZones[?Name=='opssightai.com.'].Id" --output text

# Then create an Alias A record pointing to the ALB in the Route 53 console
```

---

## 2. Authentication

### Architecture
Replaced the static single API key model with a full JWT session system.

```
POST /api/auth/login
  { username, password }
  → Password validated (bcrypt)
  → If MFA enabled: returns { mfa_required: true, session_token }
  → If MFA disabled: returns { access_token, refresh_token }

POST /api/auth/mfa/verify
  { session_token, totp_code }
  → TOTP code verified (RFC 6238, ±30s window)
  → Returns { access_token, refresh_token }

GET/POST <any protected endpoint>
  Authorization: Bearer <access_token>
  → JWT decoded, expiry verified, JTI checked against revocation list
  → Rejected with 401 if expired, revoked, or invalid
```

### Token Configuration
| Parameter | Value | Override env var |
|-----------|-------|-----------------|
| Access token TTL | 15 minutes | `JWT_ACCESS_TTL_MINUTES` |
| Refresh token TTL | 7 days | `JWT_REFRESH_TTL_DAYS` |
| Algorithm | HS256 | — |
| Signing key | 64-byte random hex | `JWT_SECRET` |

### Backward Compatibility
The `X-API-Key` header is still accepted for:
- SSE stream (`/api/stream?api_key=...`) — EventSource API cannot set headers
- Service-to-service calls using the legacy key

### Initial Admin Setup
```bash
# 1. Generate a bcrypt password hash
python3 -c "from passlib.hash import bcrypt; print(bcrypt.hash('your-strong-password'))"

# 2. Add to K8s secret
kubectl create secret generic trading-app-secrets \
  --namespace=agentic-trading-platform \
  --from-literal=admin-username="admin" \
  --from-literal=admin-password-hash="<bcrypt-hash>" \
  --dry-run=client -o yaml | kubectl apply -f -
```

---

## 3. Multi-Factor Authentication (MFA)

### Protocol
TOTP (Time-based One-Time Password) per RFC 6238.
Compatible with: Google Authenticator, Authy, 1Password, Bitwarden, and any RFC 6238 client.

### Enabling MFA

**Step 1: Generate the TOTP secret**
```bash
# Login first, then:
curl -H "Authorization: Bearer <access_token>" \
  https://agentictradepulse.opssightai.com/api/auth/mfa/setup

# Response:
# {
#   "totp_secret": "JBSWY3DPEHPK3PXP",
#   "provisioning_uri": "otpauth://totp/RetirementAdvisor:admin?secret=...",
#   ...
# }
```

**Step 2: Store the secret in K8s**
```bash
kubectl create secret generic trading-app-secrets \
  --namespace=agentic-trading-platform \
  --from-literal=admin-totp-secret="JBSWY3DPEHPK3PXP" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl rollout restart deployment/agentic-trading-backend \
  -n agentic-trading-platform
```

**Step 3: Scan the QR code**
Encode `provisioning_uri` as a QR code and scan with your authenticator app.
```bash
# Install qrencode and generate QR in terminal:
qrencode -t ANSIUTF8 "otpauth://totp/..."
```

**Step 4: MFA is now active**
Every login requires the 6-digit TOTP code after password verification.
The session token for the MFA step expires in 5 minutes.

### MFA Flow Diagram
```
Login → password OK → session_token (5 min TTL)
             ↓
        /api/auth/mfa/verify
             ↓
        TOTP code valid?
         Yes → access_token + refresh_token
         No  → 401 + audit log "MFA_FAILED"
```

---

## 4. Rate Limiting

All endpoints are protected by per-IP sliding window rate limits.

| Tier | Endpoints | Limit |
|------|-----------|-------|
| Auth | `/api/auth/*` | 5 req/min |
| Read | GET endpoints | 60 req/min |
| Write | POST/PUT/DELETE | 10 req/min |
| Global | All | 120 req/min |

On limit breach: `429 Too Many Requests` with `Retry-After: 60` header.
Every breach is logged to the security audit log with IP and path.

---

## 5. Security Response Headers

Every HTTP response from the backend includes:

| Header | Value | Protection |
|--------|-------|-----------|
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` | Forces HTTPS for 1 year |
| `X-Content-Type-Options` | `nosniff` | Prevents MIME sniffing |
| `X-Frame-Options` | `DENY` | Prevents clickjacking |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Limits referrer leakage |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` | Disables unused browser APIs |
| `Content-Security-Policy` | See below | XSS mitigation |

**CSP policy:**
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
Every security event is emitted as a single-line JSON object to stdout:
```json
{
  "timestamp": "2026-02-27T18:00:00.000Z",
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
| `LOGIN_SUCCESS` | Password + MFA verified |
| `LOGIN_FAILED` | Wrong username or password |
| `MFA_CHALLENGE_ISSUED` | Password OK, TOTP prompt sent |
| `MFA_SUCCESS` | TOTP code verified |
| `MFA_FAILED` | Wrong or expired TOTP code |
| `TOKEN_ISSUED` | New access or refresh token created |
| `TOKEN_REFRESHED` | Refresh token exchanged for new access token |
| `TOKEN_REVOKED` | Token explicitly revoked (logout or rotation) |
| `TOKEN_INVALID` | Expired, malformed, or tampered token |
| `API_KEY_ACCEPTED` | Legacy API key auth succeeded |
| `API_KEY_REJECTED` | Invalid API key presented |
| `LOGOUT` | Explicit logout |
| `RATE_LIMIT_BREACH` | IP exceeded rate limit |

### Shipping to CloudWatch
```bash
# Create a log group with 90-day retention
aws logs create-log-group \
  --log-group-name /retirement-advisor/security-audit \
  --region us-east-1

aws logs put-retention-policy \
  --log-group-name /retirement-advisor/security-audit \
  --retention-in-days 90

# Add fluent-bit or CloudWatch agent to EKS to ship pod stdout
# Recommended: EKS add-on "amazon-cloudwatch-observability"
```

---

## 7. CORS

CORS is driven entirely by the `CORS_ALLOWED_ORIGINS` environment variable.
There is **no localhost fallback** in production deployments.

```bash
# Set in K8s secret:
kubectl create secret generic trading-app-secrets \
  --from-literal=cors-allowed-origins="https://agentictradepulse.opssightai.com" \
  ...
```

If `CORS_ALLOWED_ORIGINS` is empty, no cross-origin requests are allowed.

---

## 8. Secrets Management

All secrets are stored in Kubernetes Secrets, injected as environment variables at pod startup. They are never committed to source control.

### Required Secrets

| Secret key | Description | Generation |
|------------|-------------|-----------|
| `jwt-secret` | JWT signing key | `openssl rand -hex 64` |
| `admin-username` | Admin account name | Choose your username |
| `admin-password-hash` | Bcrypt hash of password | `python3 -c "from passlib.hash import bcrypt; print(bcrypt.hash('pw'))"` |
| `admin-totp-secret` | TOTP secret | Generate via `/api/auth/mfa/setup` |
| `app-api-key` | Legacy API key (SSE) | `openssl rand -hex 32` |
| `openai-api-key` | GPT-4o-mini | Anthropic/OpenAI dashboard |
| `alpaca-api-key` | Alpaca paper | Alpaca dashboard |
| `alpaca-secret-key` | Alpaca paper | Alpaca dashboard |
| `cors-allowed-origins` | Allowed CORS origins | Your domain |
| `database-url` | DB connection string | SQLite path or PostgreSQL DSN |

### Rotation Procedure
```bash
# 1. Update K8s secret (dry-run creates, not replaces — use apply)
kubectl create secret generic trading-app-secrets \
  --namespace=agentic-trading-platform \
  --from-literal=jwt-secret="$(openssl rand -hex 64)" \
  --from-literal=admin-password-hash="$(python3 -c 'from passlib.hash import bcrypt; print(bcrypt.hash("newpassword"))')" \
  # ... other secrets unchanged ...
  --dry-run=client -o yaml | kubectl apply -f -

# 2. Restart pod to pick up new secrets
kubectl rollout restart deployment/agentic-trading-backend \
  -n agentic-trading-platform

# 3. All previously issued JWTs are now invalid (new JWT_SECRET)
#    Users must log in again
```

---

## 9. Recommended Production Hardening (Remaining Gaps)

### Encryption at Rest
```bash
# Migrate from SQLite to encrypted PostgreSQL RDS:
aws rds create-db-instance \
  --db-instance-identifier retirement-advisor-db \
  --db-instance-class db.t3.micro \
  --engine postgres \
  --storage-encrypted \          # AES-256 encryption at rest
  --master-username admin \
  --master-user-password "<strong-password>" \
  --backup-retention-period 7 \
  --region us-east-1
```

### AWS WAF
```bash
# Create a WAF Web ACL with AWS Managed Rules
aws wafv2 create-web-acl \
  --name retirement-advisor-waf \
  --scope REGIONAL \
  --default-action Allow={} \
  --rules file://waf-rules.json \
  --visibility-config ...

# Attach ARN to k8s-deploy.yaml:
# alb.ingress.kubernetes.io/wafv2-acl-arn: "<waf-acl-arn>"
```

### VPC Private Subnets
Move EKS nodes to private subnets with NAT gateway — only the ALB should be public-facing.

### AWS Secrets Manager (Automated Rotation)
Replace K8s secrets with AWS Secrets Manager references using the EKS Secrets Store CSI driver for automatic rotation without pod restarts.

### CloudWatch Alarms
```bash
# Alert on 5+ failed logins in 5 minutes
aws cloudwatch put-metric-alarm \
  --alarm-name "BruteForceAttempt" \
  --metric-name "LOGIN_FAILED" \
  --namespace "RetirementAdvisor/Security" \
  --period 300 --threshold 5 --comparison-operator GreaterThanThreshold \
  --alarm-actions "<SNS_TOPIC_ARN>"
```

### Redis for Token Revocation
Replace the in-process `_REVOKED_TOKENS` set (lost on pod restart) with a Redis ElastiCache instance so revoked tokens remain invalid across pod restarts and multiple replicas.
