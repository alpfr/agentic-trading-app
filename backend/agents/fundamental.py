"""
Fundamental Data Agent
=======================
Fetches retirement-relevant fundamentals for each ticker:
  - P/E ratio (trailing and forward)
  - P/B ratio
  - Dividend yield, payout ratio, 5-year dividend growth
  - Free cash flow
  - Debt/equity ratio
  - Revenue and earnings growth (YoY)
  - 52-week high/low (to assess drawdown entry opportunity)
  - Sector and industry

All calls run in a thread pool (run_in_executor) to avoid blocking the event loop.
Module-level cache: 6 hours TTL (fundamentals don't change minute-to-minute).
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

import yfinance as yf

logger = logging.getLogger("FundamentalAgent")

# 6-hour cache — fundamentals change slowly
_FUND_CACHE: dict = {}
FUND_CACHE_TTL = 21_600


def _fetch_fundamentals_sync(ticker: str) -> dict:
    """Blocking yfinance call — must run in thread pool."""
    try:
        stock = yf.Ticker(ticker)
        info  = stock.info or {}

        # ── Core valuation ───────────────────────────────────────────────────
        pe_trailing = info.get("trailingPE")
        pe_forward  = info.get("forwardPE")
        pb_ratio    = info.get("priceToBook")
        ps_ratio    = info.get("priceToSalesTrailing12Months")

        # ── Dividend metrics ─────────────────────────────────────────────────
        div_yield   = info.get("dividendYield") or 0.0
        payout_ratio = info.get("payoutRatio") or 0.0
        div_rate    = info.get("dividendRate") or 0.0
        ex_div_date = info.get("exDividendDate")   # unix timestamp
        # 5-year average dividend yield (proxy for growth context)
        div_5yr_avg = info.get("fiveYearAvgDividendYield") or 0.0

        # ── Quality metrics ──────────────────────────────────────────────────
        roe         = info.get("returnOnEquity")
        roa         = info.get("returnOnAssets")
        profit_margin = info.get("profitMargins")
        operating_margin = info.get("operatingMargins")
        fcf         = info.get("freeCashflow")         # annual, dollars
        total_debt  = info.get("totalDebt") or 0
        total_cash  = info.get("totalCash") or 0
        de_ratio    = info.get("debtToEquity")         # debt/equity %

        # ── Growth ───────────────────────────────────────────────────────────
        rev_growth   = info.get("revenueGrowth")       # YoY
        earn_growth  = info.get("earningsGrowth")      # YoY
        earn_growth_q = info.get("earningsQuarterlyGrowth")

        # ── Market context ───────────────────────────────────────────────────
        mkt_cap     = info.get("marketCap")
        sector      = info.get("sector", "Unknown")
        industry    = info.get("industry", "Unknown")
        beta        = info.get("beta")
        week52_high = info.get("fiftyTwoWeekHigh")
        week52_low  = info.get("fiftyTwoWeekLow")
        current_price = info.get("currentPrice") or info.get("regularMarketPrice")

        # ── Derived signals ──────────────────────────────────────────────────
        drawdown_from_high = None
        if week52_high and current_price:
            drawdown_from_high = (current_price - week52_high) / week52_high  # negative = below high

        net_cash = total_cash - total_debt if total_cash and total_debt else None

        # ── Format for LLM consumption ───────────────────────────────────────
        lines = []
        if pe_trailing:   lines.append(f"P/E (trailing): {pe_trailing:.1f}")
        if pe_forward:    lines.append(f"P/E (forward):  {pe_forward:.1f}")
        if pb_ratio:      lines.append(f"P/B ratio:      {pb_ratio:.2f}")
        if div_yield:     lines.append(f"Dividend yield: {div_yield*100:.2f}%")
        if payout_ratio:  lines.append(f"Payout ratio:   {payout_ratio*100:.1f}%")
        if div_rate:      lines.append(f"Annual dividend:${div_rate:.2f}/share")
        if div_5yr_avg:   lines.append(f"5yr avg yield:  {div_5yr_avg:.2f}%")
        if roe:           lines.append(f"Return on equity:{roe*100:.1f}%")
        if profit_margin: lines.append(f"Profit margin:  {profit_margin*100:.1f}%")
        if de_ratio:      lines.append(f"Debt/equity:    {de_ratio:.1f}%")
        if rev_growth:    lines.append(f"Revenue growth (YoY): {rev_growth*100:.1f}%")
        if earn_growth:   lines.append(f"Earnings growth (YoY):{earn_growth*100:.1f}%")
        if beta:          lines.append(f"Beta:           {beta:.2f}")
        if week52_high:   lines.append(f"52-week high:   ${week52_high:.2f}")
        if week52_low:    lines.append(f"52-week low:    ${week52_low:.2f}")
        if drawdown_from_high is not None:
            lines.append(f"From 52w high:  {drawdown_from_high*100:.1f}%")
        if sector != "Unknown": lines.append(f"Sector: {sector} / {industry}")
        if mkt_cap:       lines.append(f"Market cap:     ${mkt_cap/1e9:.1f}B")
        if fcf:           lines.append(f"Free cash flow: ${fcf/1e9:.2f}B/yr")
        if net_cash is not None: lines.append(f"Net cash:       ${net_cash/1e9:.2f}B")

        if not lines:
            lines = ["Fundamental data not available for this ticker."]

        return {
            "summary": "\n".join(lines),
            "raw": {
                "pe_trailing":    pe_trailing,
                "pe_forward":     pe_forward,
                "pb_ratio":       pb_ratio,
                "div_yield":      div_yield,
                "payout_ratio":   payout_ratio,
                "div_rate":       div_rate,
                "div_5yr_avg":    div_5yr_avg,
                "roe":            roe,
                "profit_margin":  profit_margin,
                "de_ratio":       de_ratio,
                "rev_growth":     rev_growth,
                "earn_growth":    earn_growth,
                "beta":           beta,
                "sector":         sector,
                "industry":       industry,
                "mkt_cap":        mkt_cap,
                "fcf":            fcf,
                "week52_high":    week52_high,
                "week52_low":     week52_low,
                "drawdown_from_high": drawdown_from_high,
                "current_price":  current_price,
            },
            "fetched_at": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.warning(f"Fundamentals fetch failed for {ticker}: {e}")
        return {
            "summary": "MISSING — fundamental data unavailable. Default to HOLD.",
            "raw": {},
            "fetched_at": datetime.utcnow().isoformat(),
        }


async def fetch_fundamentals(ticker: str) -> dict:
    """
    Async wrapper — runs blocking yfinance in thread pool.
    Returns full dict with 'summary' (for LLM) and 'raw' (for risk gates + UI).
    """
    now = datetime.utcnow()
    cached = _FUND_CACHE.get(ticker)
    if cached:
        age = (now - datetime.fromisoformat(cached["fetched_at"])).total_seconds()
        if age < FUND_CACHE_TTL:
            return cached

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _fetch_fundamentals_sync, ticker)
    _FUND_CACHE[ticker] = result
    return result
