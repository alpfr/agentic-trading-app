# SOC 2 Compliance & Security Overview

The Agentic Trading Application is designed with enterprise-grade security and compliance in mind, aligning with the five **Trust Service Criteria** outlined by the AICPA for SOC 2 Type I and Type II compliance: Security, Availability, Processing Integrity, Confidentiality, and Privacy.

## 1. Security (Protection against unauthorized access)

### Infrastructure Security

- **Containerization**: Both frontend and backend environments run in isolated, immutable Docker containers strictly sourced from minimal alpine/slim base images to reduce attack surfaces.
- **Vulnerability Scanning**: Docker images pushed to AWS Elastic Container Registry (ECR) can be configured with "Scan on Push" to instantly detect CVEs (Common Vulnerabilities and Exposures) within the OS or Python/Node dependencies.
- **Network Isolation**: Inside the AWS EKS environment, the `agentic-trading-backend` is scoped as a `ClusterIP` Service. This means the Python server cannot be directly accessed from the internet. It only accepts traffic routed securely through the AWS Application Load Balancer (ALB).

### Secret Management

- **API Keys**: Keys for OpenAI (`OPENAI_API_KEY`) and Broker networks (Alpaca) are strictly prohibited from being hardcoded. They are injected as environment variables natively mapped from Kubernetes Secrets during container orchestration.

## 2. Availability (System uptime and resilience)

- **Kubernetes Orchestration**: The application utilizes AWS EKS to manage lifecycles. If the backend or frontend pods crash due to memory or runtime errors, the EKS control plane will automatically revive them to maintain the baseline `replicas` configuration.
- **Load Balancing**: The AWS ALB Ingress Controller actively monitors the health of the Kubernetes nodes and intelligently routes internet traffic away from failing partitions.
- **Horizontal Scaling**: The architecture natively supports Kubernetes Horizontal Pod Autoscalers (HPA). As network or computational traffic increases (e.g., during heavy market hours), identical replicas of the ASGI Uvicorn workers or Nginx frontends can rapidly spin up.

## 3. Processing Integrity (System achieves its purpose accurately)

In an AI-driven quantitative application, protecting against non-deterministic outputs is critical.

- **Deterministic Risk Gatekeeper**: The system strictly separates the "Brain" (Strategy LLM) from the "Hands" (Execution Agent). The LLM cannot perform a trade directly. Every generated signal must pass through the mathematically static `RiskManager` which explicitly calculates maximum drawdowns, volume thresholds, and capital allocations before authorizing broker-level execution.
- **Immutable Audit Logging**: Every major orchestration step—Market Data Syncing, LLM Processing, Risk Evaluations, and Order Fills—is recorded in a strict append-only Audit Journal visible in the `/api/logs` UI. This allows compliance officers to trace exactly *why* a trade was placed and *who/what* authorized it.
- **Schema Enforcement**: The Strategy Agent relies on strict `Pydantic` schemas. If the OpenAI LLM hallucinates an invalid JSON structure, it is caught at the API boundary, resulting in an automatic fallback to "HOLD" and avoiding catastrophic downstream state corruptions.

## 4. Confidentiality (Protection of sensitive data)

- **Database at Rest**: Currently, market cache datasets are held in a local `SQLite` volume. For full SOC 2 production certification, this volume maps to AWS RDS Postgres featuring KMS (Key Management Service) AES-256 encryption-at-rest.
- **Data in Transit**: The AWS Application Load Balancer natively terminates TLS/SSL (HTTPS) from the physical client. By configuring AWS Certificate Manager (ACM) alongside the active ALB Ingress, all external API traffic is robustly encrypted.

## 5. Privacy (Protection of Personal Information - PII)

- **Absolute Zero PII**: The current prototype explicitly does not collect mapping identifiers, email addresses, credit cards, or internal user identities. Access is centralized for the quantitative operator.
- **Financial Segregation**: Broker connectivity utilizes strict API Key mapping without transmitting standard consumer passwords across the frontend layer.
