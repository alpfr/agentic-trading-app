import json
import logging
import uuid
from typing import Dict, Any

from pydantic import ValidationError
from trading_interface.events.schemas import SignalCreated
from agents.prompts import RETIREMENT_ADVISOR_SYSTEM_PROMPT, USER_CONTEXT_PROMPT_TEMPLATE

logger = logging.getLogger("StrategyAgent")

class AbstractLLMClient:
    """Mock/Wrapper for OpenAI or Anthropic SDKs."""
    async def generate_json(self, system_prompt: str, user_prompt: str) -> str:
        # In a real system, this calls `client.chat.completions.create` 
        # passing `response_format={"type": "json_object"}`.
        pass

class MockSwingLLMClient(AbstractLLMClient):
    """Simulates retirement advisor LLM responses (used when no OpenAI key is set)."""
    async def generate_json(self, system_prompt: str, user_prompt: str) -> str:
        import asyncio; await asyncio.sleep(0.5)

        if "MISSING" in user_prompt or "Insufficient" in user_prompt:
            return json.dumps({
                "suggested_action": "HOLD",
                "suggested_horizon": "long_term",
                "strategy_alias": "retirement_conservative",
                "confidence": 0.10,
                "rationale": "Critical fundamental data is missing. A long-term retirement position should never be initiated without complete fundamental data. The primary risk is making a capital allocation decision with incomplete information."
            })
        elif "ETF" in user_prompt.upper() or "VTI" in user_prompt or "SCHD" in user_prompt:
            return json.dumps({
                "suggested_action": "BUY",
                "suggested_horizon": "long_term",
                "strategy_alias": "retirement_etf_dca",
                "confidence": 0.78,
                "rationale": "Broad-market ETF with low expense ratio provides core diversification appropriate for retirement horizon. The primary risk is short-term market volatility, which is acceptable given the 5-10 year time horizon."
            })
        return json.dumps({
            "suggested_action": "HOLD",
            "suggested_horizon": "long_term",
            "strategy_alias": "retirement_monitor",
            "confidence": 0.50,
            "rationale": "Insufficient data alignment to initiate a high-conviction long-term position. Monitor for improving fundamental signals before committing capital. The primary risk is opportunity cost if the business accelerates unexpectedly."
        })

class OpenAILLMClient(AbstractLLMClient):
    """Real implementation calling OpenAI API."""
    def __init__(self, api_key: str):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=api_key)
        
    async def generate_json(self, system_prompt: str, user_prompt: str) -> str:
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini", # Cost effective for the prototype demo
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.2
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"OpenAI API Error: {e}")
            raise e

class StrategyAgent:
    """
    Consumes multi-source inputs and outputs exactly constrained Pydantic validation schemas.
    """
    def __init__(self, llm_client: AbstractLLMClient):
        self.llm = llm_client

    async def evaluate_context(self, ticker: str, technicals: str, sentiment: str, fundamentals: str) -> SignalCreated:
        """
        Takes raw string synopses from the Sub-Agents (Market, News, Funds)
        and queries the Strategy LLM for a signal.
        """
        logger.info(f"Synthesizing Context for {ticker}...")
        
        from core.watchlist import get_ticker_category
        category = get_ticker_category(ticker)
        user_prompt = USER_CONTEXT_PROMPT_TEMPLATE.format(
            ticker=ticker,
            category=category,
            technical_data=technicals,
            sentiment_data=sentiment,
            fundamental_data=fundamentals,
        )

        try:
            # Native JSON enforcement at the API level
            raw_response = await self.llm.generate_json(
                system_prompt=RETIREMENT_ADVISOR_SYSTEM_PROMPT,
                user_prompt=user_prompt
            )
            
            # Pydantic Enforcement Layer
            # We parse the LLM's raw dump and let Pydantic handle schema errors natively.
            parsed_dict = json.loads(raw_response)
            
            # Reconstruct the Pydantic schema required by the Risk Manager.
            # Only exact matching schemas make it past this function.
            signal = SignalCreated(
                event_id=uuid.uuid4(),
                ticker=ticker,
                suggested_action=parsed_dict.get("suggested_action", "HOLD"),
                suggested_horizon=parsed_dict.get("suggested_horizon", "swing"),
                strategy_alias=parsed_dict.get("strategy_alias", "swing_default"),
                confidence=float(parsed_dict.get("confidence", 0.0)),
                rationale=parsed_dict.get("rationale", "No rationale generated.")
            )

            logger.info(f"Generated {signal.suggested_action} Signal for {signal.ticker} with Confidence {signal.confidence}")
            return signal

        except json.JSONDecodeError as j:
            logger.error(f"FATAL: LLM failed to output parseable JSON. {j}")
            return self._emergency_hold_fallback(ticker, "JSON Structuring Failure")

        except ValidationError as v:
            logger.error(f"FATAL: LLM hallucinated incorrect data types bypassing Pydantic rules. {v}")
            return self._emergency_hold_fallback(ticker, "Schema Hallucination Failure")

    def _emergency_hold_fallback(self, ticker: str, reason: str) -> SignalCreated:
        """Adversarial resilience: If the LLM breaks, standard deterministic math takes over."""
        return SignalCreated(
            event_id=uuid.uuid4(),
            ticker=ticker,
            suggested_action="HOLD",
            suggested_horizon="long_term",
            strategy_alias="emergency_safety",
            confidence=0.0,
            rationale=reason
        )
