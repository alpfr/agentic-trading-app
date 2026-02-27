"""
Market Movers Agent
===================
Two-tier approach:
  1. PRIMARY: yf.screen() with Yahoo Finance predefined screeners (day_gainers,
     day_losers, most_actives) — correct modern API with built-in cookie/crumb auth.
  2. FALLBACK: Download 2-day daily OHLCV for a curated 40-ticker watchlist,
     compute % change, and sort into gainers/losers/actives.

The fallback fires automatically if the screener returns empty or throws.
"""

import asyncio
import logging
from datetime import datetime

import pandas as pd
import yfinance as yf

logger = logging.getLogger("MoversAgent")

# Cached result to avoid hammering Yahoo Finance on every request
_movers_cache: dict = {}
_CACHE_TTL_SECONDS = 120   # 2 minutes

# Broad liquid universe used for the fallback calculation
_WATCHLIST = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "LLY", "JPM",
    "V",    "UNH",  "XOM",  "MA",    "JNJ",  "WMT",  "PG",   "HD",   "MRK", "ORCL",
    "AMD",  "NFLX", "COST", "ABBV",  "CRM",  "BAC",  "KO",   "PEP",  "ACN", "MCD",
    "PLTR", "COIN", "MSTR", "SMCI",  "ARM",  "HOOD", "RKLB", "IONQ", "CRWD","SNOW",
]


async def get_movers() -> dict:
    """Returns gainers, losers, actives. Cached for 2 minutes."""
    now = datetime.utcnow()
    if _movers_cache:
        age = (now - _movers_cache["_ts"]).total_seconds()
        if age < _CACHE_TTL_SECONDS:
            logger.info(f"Movers cache hit ({age:.0f}s old)")
            return {k: v for k, v in _movers_cache.items() if not k.startswith("_")}

    # Run blocking yfinance calls in a thread pool
    result = await asyncio.get_event_loop().run_in_executor(None, _fetch_movers_sync)

    _movers_cache.clear()
    _movers_cache.update(result)
    _movers_cache["_ts"] = now
    return result


def _fetch_movers_sync() -> dict:
    """Synchronous inner function — runs in thread pool via run_in_executor."""

    # ── PRIMARY: Yahoo Finance predefined screeners ───────────────────────────
    try:
        logger.info("Fetching movers via yf.screen() screener API...")
        gainers = _screen("day_gainers")
        losers  = _screen("day_losers")
        actives = _screen("most_actives")

        if gainers and losers and actives:
            logger.info(f"Screener OK: {len(gainers)} gainers, {len(losers)} losers, {len(actives)} actives")
            return {"gainers": gainers, "losers": losers, "actives": actives}

        logger.warning("Screener returned empty results — falling back to watchlist.")
    except Exception as e:
        logger.warning(f"Screener API failed ({e}) — falling back to watchlist.")

    # ── FALLBACK: Compute movers from curated watchlist ───────────────────────
    return _compute_from_watchlist()


def _screen(query_name: str) -> list:
    """Calls yf.screen() and normalises results to our standard format."""
    result = yf.screen(query_name, count=10)
    if not result:
        return []

    quotes = result.get("quotes", [])
    out = []
    for q in quotes:
        symbol     = q.get("symbol", "")
        name       = q.get("shortName") or q.get("longName") or symbol
        price      = q.get("regularMarketPrice") or q.get("ask") or 0.0
        change_pct = q.get("regularMarketChangePercent", 0.0)
        volume     = q.get("regularMarketVolume", 0)

        if symbol and price > 0:
            out.append({
                "ticker":     symbol,
                "name":       name[:35],
                "price":      round(float(price), 2),
                "change_pct": round(float(change_pct), 2),
                "volume":     int(volume),
            })
    return out


def _compute_from_watchlist() -> dict:
    """
    Downloads 2 trading days of daily close for all watchlist tickers,
    computes percentage change, then returns top/bottom 10 + most active.
    """
    logger.info(f"Computing movers from {len(_WATCHLIST)}-ticker watchlist...")
    try:
        df = yf.download(
            _WATCHLIST,
            period="5d",          # 5 days handles weekends/holidays
            interval="1d",
            progress=False,
            auto_adjust=True,
            threads=True,
        )

        if df.empty:
            logger.error("Watchlist download returned empty DataFrame")
            return _empty_movers()

        # Handle MultiIndex columns (yfinance v0.2+)
        if isinstance(df.columns, pd.MultiIndex):
            close  = df["Close"]
            volume = df["Volume"] if "Volume" in df else None
        else:
            close  = df[["Close"]]
            volume = df[["Volume"]] if "Volume" in df.columns else None

        # Drop columns that are all NaN (failed tickers)
        close = close.dropna(axis=1, how="all")

        if len(close) < 2:
            logger.error("Not enough trading days in watchlist data")
            return _empty_movers()

        # Most recent two valid rows
        prev  = close.iloc[-2]
        today = close.iloc[-1]
        change_pct = ((today - prev) / prev * 100).round(2)
        change_pct = change_pct.dropna()

        # Sort
        gainers_s = change_pct.sort_values(ascending=False).head(10)
        losers_s  = change_pct.sort_values(ascending=True).head(10)

        # Most active by volume (if available)
        if volume is not None:
            volume = volume.dropna(axis=1, how="all")
            vol_today = volume.iloc[-1].dropna().sort_values(ascending=False).head(10)
            active_tickers = vol_today.index.tolist()
        else:
            active_tickers = change_pct.abs().sort_values(ascending=False).head(10).index.tolist()

        def build_list(series) -> list:
            out = []
            for ticker, pct in series.items():
                price = float(today.get(ticker, 0))
                out.append({
                    "ticker":     str(ticker),
                    "name":       str(ticker),   # No name in download; Ticker.info is too slow for batch
                    "price":      round(price, 2),
                    "change_pct": round(float(pct), 2),
                    "volume":     int(volume[ticker].iloc[-1]) if volume is not None and ticker in volume.columns else 0,
                })
            return out

        actives_list = []
        for ticker in active_tickers:
            price  = float(today.get(ticker, 0))
            pct    = float(change_pct.get(ticker, 0.0))
            vol    = int(volume[ticker].iloc[-1]) if volume is not None and ticker in volume.columns else 0
            actives_list.append({
                "ticker":     str(ticker),
                "name":       str(ticker),
                "price":      round(price, 2),
                "change_pct": round(pct, 2),
                "volume":     vol,
            })

        result = {
            "gainers": build_list(gainers_s),
            "losers":  build_list(losers_s),
            "actives": actives_list,
        }
        logger.info(f"Watchlist fallback OK: {len(result['gainers'])} gainers, "
                    f"{len(result['losers'])} losers, {len(result['actives'])} actives")
        return result

    except Exception as e:
        logger.error(f"Watchlist fallback failed: {e}")
        return _empty_movers()


def _empty_movers() -> dict:
    return {"gainers": [], "losers": [], "actives": []}
