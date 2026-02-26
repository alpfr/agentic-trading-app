import asyncio
import logging

from agents.strategy import StrategyAgent, MockSwingLLMClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

async def test_agent_outputs():
    # In production, this client wraps Anthropic's Claude or OpenAI's GPT
    llm = MockSwingLLMClient() 
    strategy = StrategyAgent(llm_client=llm)

    print("\n--- TEST 1: PERFECT CONTEXT (SHOULD BUY) ---")
    perfect_signal = await strategy.evaluate_context(
        ticker="MSFT",
        technicals="Bullish cross recently formed on the 20SMA. RSI at 58 showing room to run.",
        sentiment="Extremely positive narrative surrounding Azure momentum.",
        fundamentals="P/E at 35x, PEG ratio indicates fair growth valuation."
    )
    print(perfect_signal.model_dump_json(indent=2))

    print("\n--- TEST 2: MISSING DATA (SHOULD DEFAULT HOLD) ---")
    missing_data_signal = await strategy.evaluate_context(
        ticker="NVDA",
        technicals="RSI 75. Price > 20SMA",
        sentiment="Mixed macro data.",
        fundamentals="MISSING" # The agent will catch this
    )
    print(missing_data_signal.model_dump_json(indent=2))

if __name__ == "__main__":
    asyncio.run(test_agent_outputs())
