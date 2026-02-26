import asyncio
import logging
import uuid
from datetime import datetime

from trading_interface.events.schemas import SignalCreated
from core.portfolio_state import PortfolioState, PositionState, MarketContext
from core.risk_gatekeeper import DeterministicRiskManager, RiskApproved, RiskRejected

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

def run_risk_tests():
    manager = DeterministicRiskManager()
    
    # --- Safe Mock Context ---
    safe_portfolio = PortfolioState(
        buying_power=50_000.0,
        total_equity=100_000.0,
        high_water_mark=100_000.0,
        daily_start_equity=100_000.0,
        positions=[],
        is_trading_halted=False
    )
    
    # 1. TEST PASS: Safe Apple Trade
    safe_signal = SignalCreated(
        event_id=uuid.uuid4(),
        ticker="AAPL",
        suggested_action="BUY",
        suggested_horizon="swing",
        strategy_alias="momentum",
        confidence=0.85,
        rationale="MA Crossover identified."
    )
    
    safe_market = MarketContext(
        ticker="AAPL",
        current_price=180.00,
        atr_14=4.00,        # Risk calculation will use this
        avg_daily_volume=60_000_000,
        days_to_earnings=21,
        vix_level=18.5
    )
    
    print("\n--- TEST 1: PERFECT SWING SIGNAL ---")
    res1 = manager.evaluate_signal(safe_signal, safe_portfolio, safe_market)
    print(f"Result Type: {type(res1).__name__}")
    if isinstance(res1, RiskApproved):
        print(f"  Action: {res1.action} {res1.approved_quantity} shares of {res1.ticker} @ Limit ${res1.approved_limit_price}")
        print(f"  Calculated Stop Loss trigger: ${res1.risk_metrics.hard_stop_loss}")
        print(f"  Account Sizing Implemented: {res1.risk_metrics.account_exposure_pct}%")

    # 2. TEST FAIL: Earnings Volatility Crush Risk
    risky_market = MarketContext(
        ticker="AAPL",
        current_price=180.00,
        atr_14=4.00,
        avg_daily_volume=60_000_000,
        days_to_earnings=1, # Earning reported tomorrow!
        vix_level=18.5
    )
    print("\n--- TEST 2: EARNINGS IN 1 DAY ---")
    res2 = manager.evaluate_signal(safe_signal, safe_portfolio, risky_market)
    print(f"Result Type: {type(res2).__name__}")
    if isinstance(res2, RiskRejected):
        print(f"  Rejected By: {res2.failing_metric}")
        print(f"  Reason: {res2.reason}")

    # 3. TEST FAIL: Illiquid Penny Stock Hallucination
    # If the LLM generates a ticker it hallucinated from Reddit:
    trash_signal = SignalCreated(
        event_id=uuid.uuid4(), ticker="GME",
        suggested_action="BUY", suggested_horizon="swing",
        strategy_alias="reddit_scraper", confidence=0.99,
        rationale="Rocket emojis detected."
    )
    illiquid_market = MarketContext(
        ticker="GME",
        current_price=25.00, atr_14=2.00,
        avg_daily_volume=300_000, # Sub 5M Notional!
        days_to_earnings=45, vix_level=18.5
    )
    print("\n--- TEST 3: ILLIQUIDITY SAFEGUARD ---")
    res3 = manager.evaluate_signal(trash_signal, safe_portfolio, illiquid_market)
    print(f"Result Type: {type(res3).__name__}")
    if isinstance(res3, RiskRejected):
        print(f"  Rejected By: {res3.failing_metric}")

    # 4. TEST FAIL: Account Bleeding Circuit Breaker
    bleeding_portfolio = PortfolioState(
        buying_power=50_000.0,
        total_equity=89_000.0,      # Dropped from 100k
        high_water_mark=100_000.0,  # 11% drawdown
        daily_start_equity=100_000.0,
        positions=[],
        is_trading_halted=False
    )
    print("\n--- TEST 4: KILL SWITCH ACTIVATION (>10% Drawdown) ---")
    res4 = manager.evaluate_signal(safe_signal, bleeding_portfolio, safe_market)
    print(f"Result Type: {type(res4).__name__}")
    if isinstance(res4, RiskRejected):
        print(f"  Rejected By: {res4.failing_metric}")
        print(f"  Reason: {res4.reason}")

if __name__ == "__main__":
    run_risk_tests()
