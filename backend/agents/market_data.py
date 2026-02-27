import logging
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

from core.portfolio_state import MarketContext

logger = logging.getLogger("MarketDataAgent")

# Module-level singleton cache — survives across requests within a process.
# (For multi-replica K8s, move this to Redis with a 60s TTL.)
_CONTEXT_CACHE: dict = {}


class MarketDataAgent:
    """
    Sub-agent responsible for fetching deterministic ticker data from public APIs.
    Uses Yahoo Finance (yfinance) for the prototype.

    The cache is stored at module level so it is shared across all instances
    within a process — fixing the bug where a per-instance cache was thrown away
    every time a new MarketDataAgent() was constructed inside run_agent_loop().
    """

    CACHE_TTL_SECONDS = 60

    async def fetch_market_context(self, ticker: str) -> MarketContext:
        now = datetime.utcnow()
        cached = _CONTEXT_CACHE.get(ticker)
        if cached:
            cached_time, cached_data = cached
            if (now - cached_time).total_seconds() < self.CACHE_TTL_SECONDS:
                logger.info(f"Cache hit for {ticker}")
                return cached_data

        logger.info(f"Fetching live yfinance data for {ticker}...")
        try:
            df = yf.download(ticker, period="3mo", interval="1d", progress=False)
            if df.empty:
                raise ValueError(f"yfinance returned empty dataset for {ticker}")

            # Handle MultiIndex columns (yfinance v0.2+)
            if isinstance(df.columns, pd.MultiIndex):
                close_col = ("Close", ticker)
                high_col  = ("High", ticker)
                low_col   = ("Low", ticker)
                vol_col   = ("Volume", ticker)
            else:
                close_col = "Close"
                high_col  = "High"
                low_col   = "Low"
                vol_col   = "Volume"

            current_price     = float(df[close_col].iloc[-1])
            avg_daily_volume  = int(df[vol_col].tail(20).mean())

            # 14-day ATR
            df["prev_close"] = df[close_col].shift(1)
            tr1 = df[high_col] - df[low_col]
            tr2 = (df[high_col] - df["prev_close"]).abs()
            tr3 = (df[low_col]  - df["prev_close"]).abs()
            df["TR"] = pd.DataFrame({"tr1": tr1, "tr2": tr2, "tr3": tr3}).max(axis=1)
            atr_14 = float(df["TR"].rolling(window=14).mean().iloc[-1])
            if pd.isna(atr_14):
                atr_14 = current_price * 0.02

            # SMAs
            sma_20 = float(df[close_col].rolling(window=20).mean().iloc[-1])
            sma_50 = float(df[close_col].rolling(window=50).mean().iloc[-1])
            if pd.isna(sma_20): sma_20 = current_price
            if pd.isna(sma_50): sma_50 = current_price

            # VIX — SAFE FALLBACK: if VIX fetch fails we default HIGH (99)
            # so the macro regime check blocks new longs rather than silently passing.
            try:
                vix_df = yf.download("^VIX", period="5d", progress=False)
                if isinstance(vix_df.columns, pd.MultiIndex):
                    vix_level = float(vix_df[("Close", "^VIX")].iloc[-1])
                else:
                    vix_level = float(vix_df["Close"].iloc[-1])
                if pd.isna(vix_level):
                    raise ValueError("VIX is NaN")
            except Exception as vix_err:
                logger.warning(
                    f"VIX fetch failed ({vix_err}). Defaulting to 99.0 to block new longs "
                    "until real data is available — fail-safe behaviour."
                )
                vix_level = 99.0  # FIX: was 15.0 (silently disabled macro gate)

            # Earnings calendar — real data via yfinance .calendar property
            days_to_earnings = self._get_days_to_earnings(ticker)

            context = MarketContext(
                ticker=ticker,
                current_price=round(current_price, 2),
                atr_14=round(atr_14, 2),
                avg_daily_volume=avg_daily_volume,
                days_to_earnings=days_to_earnings,
                vix_level=round(vix_level, 2),
                sma_20=round(sma_20, 2),
                sma_50=round(sma_50, 2),
            )

            _CONTEXT_CACHE[ticker] = (now, context)
            return context

        except Exception as e:
            logger.error(f"Failed to fetch market data for {ticker}: {e}")
            # Deliberately bad numbers so the RiskManager rejects the signal safely.
            return MarketContext(
                ticker=ticker,
                current_price=10.0,
                atr_14=1.0,
                avg_daily_volume=0,    # Trips ADV liquidity gate
                days_to_earnings=0,    # Trips earnings blackout gate
                vix_level=99.0,        # Trips macro VIX gate
                sma_20=10.0,
                sma_50=10.0,
            )

    def _get_days_to_earnings(self, ticker: str) -> int:
        """
        Fetches the next earnings date from yfinance's .calendar property.
        Returns days remaining; returns a large safe number (999) if unavailable
        so the blackout rule does NOT incorrectly block non-earnings trades.

        NOTE: yfinance earnings data can lag. For production, replace with
        a dedicated earnings calendar API (e.g. Polygon.io /v3/reference/tickers
        or Alpha Vantage EARNINGS_CALENDAR).
        """
        try:
            stock = yf.Ticker(ticker)
            cal = stock.calendar           # Returns dict or DataFrame
            if cal is None:
                return 999

            # yfinance can return a dict or a DataFrame depending on version
            if isinstance(cal, dict):
                earnings_date = cal.get("Earnings Date")
                if earnings_date is None:
                    return 999
                # May be a list of dates
                if isinstance(earnings_date, (list, tuple)):
                    earnings_date = earnings_date[0]
            elif hasattr(cal, "iloc"):
                # DataFrame format — first column is the date
                earnings_date = cal.iloc[0, 0] if not cal.empty else None
                if earnings_date is None:
                    return 999
            else:
                return 999

            # Normalise to datetime
            if hasattr(earnings_date, "date"):
                earnings_date = earnings_date.date()
            today = datetime.utcnow().date()
            delta = (earnings_date - today).days
            return max(delta, 0)

        except Exception as e:
            logger.warning(
                f"Could not fetch earnings date for {ticker}: {e}. "
                "Returning 999 (no blackout applied). Consider a dedicated earnings API."
            )
            return 999

    async def generate_technical_summary_string(
        self, ticker: str, market_context: MarketContext
    ) -> str:
        cross_status = ""
        if market_context.sma_20 > market_context.sma_50:
            cross_status = "A bullish cross is actively fully confirmed (20SMA > 50SMA)."
        elif market_context.sma_20 < market_context.sma_50:
            cross_status = "A bearish cross is actively fully confirmed (20SMA < 50SMA)."
        return (
            f"Current Price is ${market_context.current_price}. "
            f"{market_context.avg_daily_volume} ADV. "
            f"ATR is ${market_context.atr_14}. "
            f"VIX is sitting at {market_context.vix_level}. "
            f"Earnings in {market_context.days_to_earnings} days. "
            f"{cross_status}"
        )

    async def fetch_news_and_sentiment(self, ticker: str) -> str:
        logger.info(f"Fetching news for {ticker}...")
        try:
            stock = yf.Ticker(ticker)
            news_items = stock.news
            if not news_items:
                return "No recent news available."

            headlines = []
            for item in news_items[:5]:
                title   = item.get("content", {}).get("title", "") if "content" in item else item.get("title", "")
                summary = item.get("content", {}).get("summary", "") if "content" in item else item.get("summary", "")
                if title:
                    clean = summary[:150].replace("\n", " ") + "..." if summary else ""
                    headlines.append(f"- {title}: {clean}")

            return "Recent News Headlines:\n" + "\n".join(headlines) if headlines else "No parseable news available."
        except Exception as e:
            logger.error(f"Failed to fetch news for {ticker}: {e}")
            return "Error retrieving news data."

    async def fetch_fundamentals(self, ticker: str) -> str:
        logger.info(f"Fetching fundamentals for {ticker}...")
        try:
            stock = yf.Ticker(ticker)
            info  = stock.info

            pe   = info.get("trailingPE", "N/A")
            f_pe = info.get("forwardPE", "N/A")
            pb   = info.get("priceToBook", "N/A")

            if pe == "N/A" and f_pe == "N/A" and pb == "N/A":
                return "MISSING: Critical fundamental valuation data unavailable. Asset may be a SPAC, recent IPO, or highly illiquid."

            dy = info.get("dividendYield", "N/A")
            if dy not in ("N/A", None) and isinstance(dy, float):
                dy = f"{dy * 100:.2f}%" if dy < 1.0 else f"{dy:.2f}%"

            pm = info.get("profitMargins", "N/A")
            if pm not in ("N/A", None) and isinstance(pm, float):
                pm = f"{pm * 100:.2f}%"

            return f"Trailing P/E: {pe} | Forward P/E: {f_pe} | P/B: {pb} | Div Yield: {dy} | Profit Margins: {pm}"
        except Exception as e:
            logger.error(f"Failed to fetch fundamentals for {ticker}: {e}")
            return "MISSING: Fundamentals data temporarily unavailable."
