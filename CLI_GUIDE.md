# CLI Connection Guide — EKS Cluster

Cluster: `agentic-trading-cluster` · Region: `us-east-1` · Namespace: `agentic-trading-platform`

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

# eksctl (optional but useful for cluster management)
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

Writes credentials into `~/.kube/config`. Run once (or after credential rotation).

---

## Step 3 — Verify connection

```bash
kubectl get nodes

kubectl get all -n agentic-trading-platform
```

---

## Day-to-day commands

### Pods

```bash
# List pods
kubectl get pods -n agentic-trading-platform

# Stream live backend logs
kubectl logs -f deployment/agentic-trading-backend \
  -n agentic-trading-platform

# Stream only security audit events
kubectl logs -f deployment/agentic-trading-backend \
  -n agentic-trading-platform | grep '"log_type":"security_audit"'

# Shell into a running pod
kubectl exec -it \
  $(kubectl get pod -n agentic-trading-platform -l app=agentic-trading-backend \
    -o jsonpath='{.items[0].metadata.name}') \
  -n agentic-trading-platform -- bash
```

### Deployments

```bash
# Restart backend (picks up new secrets or config changes)
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

# Update / rotate a secret value
kubectl create secret generic trading-app-secrets \
  -n agentic-trading-platform \
  --from-literal=jwt-secret="$(openssl rand -hex 64)" \
  --dry-run=client -o yaml | kubectl apply -f -

# Always restart after updating secrets
kubectl rollout restart deployment/agentic-trading-backend \
  -n agentic-trading-platform
```

### Get the live app URL

```bash
kubectl get ingress agentic-trading-ingress \
  -n agentic-trading-platform \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
```

---

## Troubleshooting

| Symptom | Command |
|---------|---------|
| Pod crashlooping | `kubectl describe pod <pod-name> -n agentic-trading-platform` |
| App returns 503 | `kubectl get endpoints -n agentic-trading-platform` |
| Recent events | `kubectl get events -n agentic-trading-platform --sort-by='.lastTimestamp'` |
| Check resource usage | `kubectl top pods -n agentic-trading-platform` |
| Delete cluster (cost saving) | `eksctl delete cluster --name agentic-trading-cluster --region us-east-1` |

---

## IAM Requirements

The AWS user needs the following to connect and operate the cluster:

- `AmazonEKSClusterPolicy`
- `AmazonEKSWorkerNodePolicy`
- `AmazonEC2ContainerRegistryReadOnly` (to pull images)

The IAM user used by GitHub Actions to deploy already has full access — use the same credentials locally.
