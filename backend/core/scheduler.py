"""
Retirement Portfolio Scheduler
================================
Replaces intraday 20-minute scan scheduler.
- Daily scan: runs once per trading day at market open + 30 min (09:30 ET)
- Weekly rebalance check: every Monday
- No EOD close logic
"""
import asyncio
import logging
from datetime import datetime, time as dt_time
from typing import Callable, Awaitable
from zoneinfo import ZoneInfo

from core.watchlist import get_config

logger = logging.getLogger("RetirementScheduler")

ET = ZoneInfo("America/New_York")

MARKET_OPEN  = dt_time(9, 30)
SCAN_TIME    = dt_time(10, 0)   # 30 min after open — let pre-market settle
MARKET_CLOSE = dt_time(16, 0)


def _is_trading_day(now: datetime) -> bool:
    """Mon–Fri, not a weekend."""
    return now.weekday() < 5


def _is_scan_window(now: datetime) -> bool:
    """True during 10:00–10:15 ET — daily scan window."""
    t = now.time()
    return dt_time(10, 0) <= t <= dt_time(10, 15)


def _is_rebalance_day(now: datetime) -> bool:
    """True on Monday (weekday 0)."""
    return now.weekday() == 0


class RetirementScheduler:
    """
    Fires daily agent scans and weekly rebalance checks.
    """

    def __init__(
        self,
        run_agent_fn:            Callable[[str], Awaitable[None]],
        run_rebalance_fn:        Callable[[], Awaitable[None]],
        get_config_fn:           Callable  = get_config,
    ):
        self._run_agent    = run_agent_fn
        self._run_rebalance = run_rebalance_fn
        self._get_config   = get_config_fn
        self._running      = True
        self._last_scan_date   = None   # Track date so we scan once per day
        self._last_rebalance_date = None

    async def run(self):
        logger.info("Retirement scheduler started — waiting 90s before first scan")
        await asyncio.sleep(90)
        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.error(f"Scheduler tick error: {e}")
            await asyncio.sleep(60)   # Check every 60 seconds

    async def _tick(self):
        now = datetime.now(ET)

        if not _is_trading_day(now):
            return

        today = now.date()

        # ── Daily scan: once per day during 10:00–10:15 ET ──────────────
        if _is_scan_window(now) and self._last_scan_date != today:
            self._last_scan_date = today
            cfg = self._get_config()
            logger.info(f"Daily scan triggered for {len(cfg.watchlist)} tickers")

            for i, ticker in enumerate(cfg.watchlist):
                await asyncio.sleep(i * 3)   # Stagger 3s between tickers
                asyncio.create_task(self._safe_run_agent(ticker))

        # ── Weekly rebalance: Monday, first run of the week ───────────────
        if _is_rebalance_day(now) and _is_scan_window(now) and self._last_rebalance_date != today:
            self._last_rebalance_date = today
            logger.info("Weekly rebalance check triggered")
            asyncio.create_task(self._safe_run_rebalance())

    async def _safe_run_agent(self, ticker: str):
        try:
            await self._run_agent(ticker)
        except Exception as e:
            logger.error(f"Agent run failed [{ticker}]: {e}")

    async def _safe_run_rebalance(self):
        try:
            await self._run_rebalance()
        except Exception as e:
            logger.error(f"Rebalance check failed: {e}")
