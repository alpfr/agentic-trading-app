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
