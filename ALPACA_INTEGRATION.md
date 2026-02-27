# Alpaca Trader Integration Guide

The Agentic Trading Application natively supports both "Paper Trading" (simulated) and "Live Trading" via the **Alpaca Markets** brokerage API. The architecture dictates that the `ExecutionAgent` routes all finalized `RiskApproved` signals directly to the `AlpacaPaperBroker` client.

This guide explains how to unlock the execution layer and connect it to a real Alpaca account.

---

## 1. Obtain Alpaca API Keys

1. Create a free account at [Alpaca Markets](https://app.alpaca.markets/signup).
2. Log in to your dashboard and verify your desired environment (ensure you are on the **Paper Trading** dashboard first if you want to test without real money).
3. On the right-hand side of the dashboard, click on **"View API Keys"**.
4. Generate a new key pair:
   - **Key ID**
   - **Secret Key**

*Note: Alpaca generates completely different keys for Live accounts vs. Paper accounts. Ensure you are using the correct pair.*

---

## 2. Configure the Backend `.env`

In the `backend/` directory of your project, locate or create the `.env` file (you can copy `.env.example`).

Add the following exact environment variables:

```env
# Existing OpenAI Key for the Strategy Agent
OPENAI_API_KEY="sk-..."

# New Alpaca Keys for the Execution Agent
ALPACA_API_KEY="PK..."
ALPACA_API_SECRET="..."
```

---

## 3. Enable the Python Broker Initialization

By default, the backend explicitly skips strict Alpaca authentication in `app.py` so that developers can test the application locally without requiring a brokerage account.

To enable the actual Alpaca routing:

1. Open `backend/app.py`.
2. Locate the Execution Agent routing section inside `run_agent_loop`:

```python
    # 3. Execution Agent Routes to Alpaca Paper
    executor = ExecutionAgent(broker=BROKER_CLIENT, is_live_mode=False)
```

1. Ensure the broker actually initializes its connection by passing the credentials from the environment. Currently, it fakes the authentication using `("mock", "mock", "PAPER")`.

*If your underlying `BROKER_CLIENT.authenticate` method is designed to pull from `os.getenv` automatically when no arguments are passed, then simply remove the mock strings or construct the native client properly according to your `trading_interface/broker/alpaca_paper.py` schema.*

---

## 4. Toggle the Frontend (Optional)

The Frontend UI features a "PAPER TRADING ONLY" badge by default.

To reflect the connected state in the dashboard visually:

1. Open `frontend/src/App.jsx`.
2. Locate the `isLiveMode` state toggle at the top of the file:

   ```javascript
   const [isLiveMode, setIsLiveMode] = useState(false);
   ```

3. Set this to `true` (or wire it to an actual endpoint that returns `true` when Alpaca API keys are successfully detected by the backend).
4. The sidebar will turn red and display "**LIVE TRADING MODE**" with a Shield Alert icon.

---

## Security Warning

**Never commit your `.env` file or your `ALPACA_API_SECRET` to GitHub!**

The `.gitignore` inside the `backend/` directory is already configured to ignore `.env`, but if you deploy to AWS EKS or another cloud provider, ensure you inject these Alpaca keys securely via Kubernetes Secrets and map them strictly as Environment Variables within the container.
