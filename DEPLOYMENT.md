# Deployment Guide (AWS EKS)

This application is containerized utilizing Docker and architected to deploy to AWS Elastic Kubernetes Service (EKS) via an automated bash workflow.

## Overview

The deployment configures two main microservices:

1. **Frontend Service**: An Nginx alpine server statically serving compiled Vite/React assets.
2. **Backend Service**: An internal cluster-ip FastAPI Uvicorn ASGI server.

Both services are stitched together on the public internet via an **AWS Application Load Balancer (ALB)** acting as the Ingress Controller based on URL path routing constraints.

---

## 1. Containerization Configuration

### Backend Dockerfile

The backend uses a standard `python:3.11-slim` image. It copies the `requirements.txt`, installs necessary dependencies natively, and invokes `uvicorn app:app --host 0.0.0.0 --port 8000`.

### Frontend Dockerfile

The frontend leverages a Docker **multi-stage build**:

1. It spins up a `node:20-alpine` environment and invokes `npm run build`. Note that during compilation, we intentionally set `VITE_API_URL=""`. Because typical SPA deployments running within Kubernetes rely on identical origins to bypass CORS (where `/` hits the React Router, and `/api/*` proxies cleanly to the backend through the ALB), the Vite application simply queries itself relative to the user's browser domain.
2. The artifacts from `dist/` are passed onto a naked `nginx:alpine` instance, dropping the heavy NodeJS footprint and optimizing the final Docker image. The Nginx fallback logic (`try_files $uri $uri/ /index.html;`) ensures direct URLs don't hit hard 404s.

---

## 2. Infrastructure Setup (`k8s-deploy.yaml`)

The single declarative file provisions matching resources for both microservices:

- **Deployments:** Specifies the Amazon ECR container URLs alongside standard standard `spec.replicas`.
- **ClusterIP Services:** Opens native Kubernetes DNS routing locally mapping standard ports 80 and 8000 safely within VPC bounds.
- **Ingress:** Annotates the deployment requiring the AWS ALB (`kubernetes.io/ingress.class: alb`). Configures exact path routing forwarding everything prefixed with `/api` explicitly to `agentic-trading-backend:8000` while allowing the wildcard `/` to fall downstream to `agentic-trading-frontend:80`.

---

## 3. Deployment Script Mechanics (`deploy.sh`)

The deployment process is entirely automated through the bash script located at `./deploy.sh`.

This script:

1. Calls `aws ecr create-repository` to bootstrap the registry locations natively if they don't already exist.
2. Logs into the authenticated AWS configuration natively.
3. Steps sequentially into the `backend/` and `frontend/` directories to process the `docker buildx build` sequence.
4. Executes `docker push` utilizing the exact targeted ECR URL.
5. Issues a `kubectl apply -f k8s-deploy.yaml` against the active EKS server configuration.

### Deployment Instructions

To trigger an entire build and update routine:

```bash
chmod +x deploy.sh
./deploy.sh
```

Upon successful submission to the Kubernetes Cluster, AWS will take roughly 30 to 120 seconds to establish the underlying ALB and network forwarding groups.

To determine the final active URL where you can view the application:

```bash
kubectl get ingress agentic-trading-ingress
```

The public DNS record will formulate under the `ADDRESS` bracket!
