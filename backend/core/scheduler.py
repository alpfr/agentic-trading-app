"""
Retirement Portfolio Scheduler
================================
Replaces intraday day-trading scheduler.

Schedule:
  - Daily scan (9:35 AM ET): Run agent loop for each watchlist ticker
  - Weekly rebalance check (Monday 10:00 AM ET): Compute drift, fire alerts
  - Tickers staggered by 30s (yfinance courtesy)

No EOD close — positions are held long-term.
"""

import asyncio
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

logger = logging.getLogger("RetirementScheduler")

ET = ZoneInfo("America/New_York")

# Trigger times (ET)
DAILY_SCAN_TIME   = time(9, 35)    # After open — one scan per day per ticker
WEEKLY_REBAL_TIME = time(10, 0)    # Monday rebalance check
SCAN_WINDOW_END   = time(16, 0)    # Don't fire new scans after close


class MarketScheduler:
    def __init__(self, run_agent_fn, close_all_positions_fn, get_config_fn,
                 rebalance_fn=None):
        self.run_agent    = run_agent_fn
        self.close_all    = close_all_positions_fn   # Not used for retirement
        self.get_config   = get_config_fn
        self.rebalance    = rebalance_fn             # Optional weekly rebalance check
        self._running     = True
        self._last_daily_scan: dict  = {}   # ticker → date of last scan
        self._last_rebal_check: str  = ""   # date string of last rebalance check

    def stop(self):
        self._running = False

    async def run(self):
        logger.info("Retirement scheduler started — waiting 90s for pod to stabilize")
        await asyncio.sleep(90)
        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.error(f"Scheduler tick error: {e}")
            await asyncio.sleep(60)

    async def _tick(self):
        now_et  = datetime.now(ET)
        today   = now_et.date().isoformat()
        now_t   = now_et.time()
        weekday = now_et.weekday()   # 0=Mon, 6=Sun

        # Skip weekends
        if weekday >= 5:
            return

        config = self.get_config()

        # ── Weekly rebalance check (Monday morning) ──────────────────────────
        if (weekday == 0
                and now_t >= WEEKLY_REBAL_TIME
                and self._last_rebal_check != today
                and self.rebalance):
            logger.info("Weekly rebalance check triggered")
            try:
                await self.rebalance()
                self._last_rebal_check = today
            except Exception as e:
                logger.error(f"Rebalance check failed: {e}")

        # ── Daily scan — one per ticker per day ──────────────────────────────
        if not (DAILY_SCAN_TIME <= now_t <= SCAN_WINDOW_END):
            return

        if config.style == "monitor_only":
            return

        for ticker in config.watchlist:
            if self._last_daily_scan.get(ticker) == today:
                continue   # Already scanned today

            logger.info(f"Daily scan: {ticker}")
            try:
                asyncio.create_task(self.run_agent(ticker))
                self._last_daily_scan[ticker] = today
            except Exception as e:
                logger.error(f"Failed to launch agent for {ticker}: {e}")

            await asyncio.sleep(30)   # 30s between tickers — generous for yfinance
