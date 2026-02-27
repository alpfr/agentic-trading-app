# CLI Connection Guide — EKS Cluster

| | |
|---|---|
| Cluster | `agentic-trading-cluster` |
| Region | `us-east-1` |
| Namespace | `agentic-trading-platform` |
| Live URL | `https://agentictradepulse.opssightai.com` |

---

## Prerequisites — install once

```bash
# AWS CLI
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip
unzip awscliv2.zip && sudo ./aws/install
aws --version

# kubectl
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl && sudo mv kubectl /usr/local/bin/
kubectl version --client

# eksctl (optional — useful for cluster management)
EKSCTL_VERSION=$(curl -sL https://api.github.com/repos/eksctl-io/eksctl/releases/latest | grep '"tag_name"' | cut -d'"' -f4)
curl -sL "https://github.com/eksctl-io/eksctl/releases/download/${EKSCTL_VERSION}/eksctl_Linux_amd64.tar.gz" | tar xz -C /tmp
sudo mv /tmp/eksctl /usr/local/bin/
eksctl version
```

---

## Step 1 — Configure AWS credentials

```bash
aws configure
# AWS Access Key ID:     <your key>
# AWS Secret Access Key: <your secret>
# Default region:        us-east-1
# Default output format: json
```

Verify:
```bash
aws sts get-caller-identity
```

---

## Step 2 — Connect to the cluster

```bash
aws eks update-kubeconfig \
  --name agentic-trading-cluster \
  --region us-east-1
```

Writes credentials into `~/.kube/config`. Run once, or again after credential rotation.

---

## Step 3 — Verify connection

```bash
kubectl get nodes
kubectl get all -n agentic-trading-platform
```

---

## Day-to-day commands

### Pods & Logs

```bash
# List pods
kubectl get pods -n agentic-trading-platform

# Stream live backend logs
kubectl logs -f deployment/agentic-trading-backend \
  -n agentic-trading-platform

# Stream security audit events only
kubectl logs -f deployment/agentic-trading-backend \
  -n agentic-trading-platform | grep '"log_type":"security_audit"'

# Shell into a running pod
kubectl exec -it \
  $(kubectl get pod -n agentic-trading-platform \
    -l app=agentic-trading-backend \
    -o jsonpath='{.items[0].metadata.name}') \
  -n agentic-trading-platform -- bash
```

### Deployments

```bash
# Restart backend (picks up new secrets / config)
kubectl rollout restart deployment/agentic-trading-backend \
  -n agentic-trading-platform

# Watch rollout progress
kubectl rollout status deployment/agentic-trading-backend \
  -n agentic-trading-platform

# Scale replicas
kubectl scale deployment/agentic-trading-backend \
  --replicas=1 -n agentic-trading-platform
```

### Secrets

```bash
# List secret keys (not values)
kubectl get secret trading-app-secrets \
  -n agentic-trading-platform -o jsonpath='{.data}' | \
  python3 -c "import json,sys; [print(k) for k in json.load(sys.stdin)]"

# Update / rotate secrets
kubectl create secret generic trading-app-secrets \
  -n agentic-trading-platform \
  --from-literal=jwt-secret="$(openssl rand -hex 64)" \
  --from-literal=app-api-key="$(openssl rand -hex 32)" \
  --dry-run=client -o yaml | kubectl apply -f -

# Always restart after updating secrets
kubectl rollout restart deployment/agentic-trading-backend \
  -n agentic-trading-platform
```

### TLS Certificate

```bash
# Check cert status and SANs
aws acm list-certificates --region us-east-1 \
  --query "CertificateSummaryList[?contains(DomainName,'opssightai')]" \
  --output table

# Full cert details (SANs, status, renewal eligibility)
aws acm describe-certificate \
  --certificate-arn <cert-arn> \
  --region us-east-1 \
  --query "Certificate.{Status:Status,SANs:SubjectAlternativeNames,Renewal:RenewalEligibility}" \
  --output table

# Get validation CNAME (if PENDING_VALIDATION)
aws acm describe-certificate \
  --certificate-arn <cert-arn> \
  --region us-east-1 \
  --query "Certificate.DomainValidationOptions[0].ResourceRecord" \
  --output table
```

### DNS

```bash
# Get ALB hostname (for CNAME / Alias record)
kubectl get ingress agentic-trading-ingress \
  -n agentic-trading-platform \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'

# Check which cert the ALB listener is using
LISTENER_ARN=$(aws elbv2 describe-listeners --region us-east-1 \
  --query "Listeners[?Port==\`443\`].ListenerArn" --output text)

aws elbv2 describe-listener-certificates \
  --listener-arn $LISTENER_ARN --region us-east-1 --output table
```

### App URL

```
https://agentictradepulse.opssightai.com
```

---

## Troubleshooting

| Symptom | Command |
|---------|---------|
| Pod crashlooping | `kubectl describe pod <pod-name> -n agentic-trading-platform` |
| 503 on all routes | `kubectl get endpoints -n agentic-trading-platform` |
| Recent cluster events | `kubectl get events -n agentic-trading-platform --sort-by='.lastTimestamp'` |
| Resource usage | `kubectl top pods -n agentic-trading-platform` |
| Wrong cert on ALB | Check listener certs (see TLS section above); redeploy to force cert swap |
| Delete cluster (cost saving) | `eksctl delete cluster --name agentic-trading-cluster --region us-east-1` |

---

## IAM Requirements

The AWS user needs:
- `AmazonEKSClusterPolicy`
- `AmazonEKSWorkerNodePolicy`
- `AmazonEC2ContainerRegistryReadOnly`
- `AmazonACMReadOnly` (for cert auto-resolve in CI/CD)

The same IAM user used by GitHub Actions already has full access — use those credentials locally.
