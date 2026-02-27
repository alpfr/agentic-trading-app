"""
Market-Hours Scheduler
======================
Runs the agent loop for every watchlist ticker during regular market hours.

Schedule:
  - Checks every `scan_interval_minutes` (default 20 min) Mon–Fri 09:35–15:40 ET
  - Skips weekends and outside market hours automatically
  - EOD sweep at 15:45 ET: closes all open day-trading positions
  - Each ticker scan is non-blocking (runs in background task queue)

Usage:
  scheduler = MarketScheduler(run_agent_fn, close_all_fn)
  asyncio.create_task(scheduler.run())
"""

import asyncio
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

logger = logging.getLogger("Scheduler")

ET = ZoneInfo("America/New_York")

MARKET_OPEN  = time(9, 35)   # Give 5 min buffer after open for liquidity
MARKET_CLOSE = time(15, 40)  # Stop new scans 20 min before close
EOD_CLOSE    = time(15, 45)  # Auto-close all positions for day trading


class MarketScheduler:
    def __init__(self, run_agent_fn, close_all_positions_fn, get_config_fn):
        self.run_agent    = run_agent_fn
        self.close_all    = close_all_positions_fn
        self.get_config   = get_config_fn
        self._eod_fired   = False   # Only fire EOD close once per day
        self._last_scan   = {}      # ticker → last scan datetime
        self._running     = True

    def stop(self):
        self._running = False

    async def run(self):
        logger.info("Market scheduler started")
        await asyncio.sleep(90)   # Let pod fully stabilize before first scan
        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.error(f"Scheduler tick error: {e}")
            await asyncio.sleep(60)   # Wake up every 60 seconds

    async def _tick(self):
        now_et = datetime.now(ET)
        today  = now_et.date()
        now_t  = now_et.time()

        # Reset EOD flag each morning
        if now_t < MARKET_OPEN:
            self._eod_fired = False

        # Skip weekends
        if now_et.weekday() >= 5:
            return

        config = self.get_config()

        # ── EOD auto-close (day trading only) ────────────────────────────────
        if (config.style == "day_trading"
                and now_t >= EOD_CLOSE
                and now_t <= time(16, 0)
                and not self._eod_fired):
            logger.info("EOD sweep: closing all open day-trading positions")
            try:
                await self.close_all()
                self._eod_fired = True
                logger.info("EOD sweep complete")
            except Exception as e:
                logger.error(f"EOD close failed: {e}")
            return

        # ── Regular market hours only ─────────────────────────────────────────
        if config.regular_hours_only:
            if not (MARKET_OPEN <= now_t <= MARKET_CLOSE):
                return

        # Skip if monitoring only
        if config.style == "monitor_only":
            return

        # ── Scan each watchlist ticker ─────────────────────────────────────────
        interval = config.scan_interval_minutes * 60   # convert to seconds
        for ticker in config.watchlist:
            last = self._last_scan.get(ticker)
            if last is None or (now_et - last).total_seconds() >= interval:
                logger.info(f"Scheduler: triggering agent for {ticker}")
                try:
                    asyncio.create_task(self.run_agent(ticker))
                    self._last_scan[ticker] = now_et
                except Exception as e:
                    logger.error(f"Failed to launch agent for {ticker}: {e}")

                # Stagger tickers by 10 seconds to avoid burst
                await asyncio.sleep(10)
