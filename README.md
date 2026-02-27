# Agentic Trading App Dashboard

A real-time, interactive dashboard that leverages agentic AI (`gpt-4o-mini`) guided by deterministic math, fetched market data from Yahoo Finance, and robust architectural constraints.

## Current Milestone (Phase 1)

The application has been successfully built to demonstrate the core Agentic Trading framework:

1. **Dynamic Portfolio Simulation**: Starts at a mocked $105,240.50. Accurately updates paper position PnL based on live stock pricing from `yfinance`.
2. **True LLM Integation**: Connects to `gpt-4o-mini` using the OpenAI library under strict JSON response constraints. No more hardcoded strategies!
3. **Real-time Market Data Gathering**: The `MarketDataAgent` fetches moving averages, volatility indicators, and dividend yields for ANY stock ticker requested.
4. **Sentiment & Fundamentals Injection**: The execution loop dynamically pulls recent real-world news articles and PE ratios and feeds them into the OpenAI instance's context prompt.
5. **Real-Time Data Persistence (SQLite)**: Persistently logs ticker price lookups and context hashes locally within an SQLite database.
6. **Market Movers Screen**: Fully automatic, live updating interface showcasing Top 10 Gainers, Losers, and Trending tickers.
7. **AI Insights Dashboard**: A clean frontend view displaying the raw technical, fundamental, and narrative data fed into the LLM, along with its specific reasoning and confidence score.
8. **Missing Data Fallbacks**: Robust handling for when Yahoo Finance misses critical valuation metrics (e.g. on SPACs or missing data periods), correctly directing the Risk Manager LLM to strictlyHOLD due to missing fundamentals.
9. **IPv6 Docker Mitigation**: The frontend explicit fetches against `http://127.0.0.1` rather than `localhost` to elegantly bypass local Docker DNS interception conflicts.

## Setup Instructions

### Backend (FastAPI / Python)

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt # Fastapi, uvicorn, pydantic, openai, yfinance, sqlalchemy, psycopg2-binary
```

Create a `.env` file from `.env.example` and add:

```
OPENAI_API_KEY="sk-..."
```

Start the server:

```bash
uvicorn app:app --reload --port 8002
```

### Frontend (React / Vite)

```bash
cd frontend
npm install
npm run dev
```

Navigate to `http://localhost:5173`.

## Deployment (AWS EKS)

This project includes Dockerfiles for containerizing both the frontend and backend, as well as a Kubernetes manifest (`k8s-deploy.yaml`) to deploy the microservices to an AWS Elastic Kubernetes Service (EKS) cluster using an Application Load Balancer (ALB).

### Containerization

- **Backend**: Built using a `python:3.11-slim` base image, which installs `requirements.txt` and runs `uvicorn` on port `8000`.
- **Frontend**: A multi-stage build using `node:20-alpine` to compile the React SPA and `nginx:alpine` to serve the static assets on port `80`, dynamically resolving the backend API using `VITE_API_URL` during runtime.

### Deploying to EKS

Ensure your local `kubectl` is authenticated with your EKS cluster and `aws-cli` is authenticated with AWS ECR.

Run the provided deployment script to completely build, push, and deploy all services:

```bash
chmod +x deploy.sh
./deploy.sh
```

This script will:

1. Create necessary AWS ECR repositories if they do not exist.
2. Build Linux/amd64 compatible Docker images.
3. Push the images to your AWS ECR registry.
4. Apply `k8s-deploy.yaml` to deploy Deployments, Services, and an AWS ALB Ingress.

Once deployed, the AWS Application Load Balancer will automatically provision a public DNS endpoint linking `/api` routes to your Python backend, and `/` routes to the React frontend.
