import logging
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

from core.portfolio_state import MarketContext

logger = logging.getLogger("MarketDataAgent")

class MarketDataAgent:
    """
    Sub-agent responsible for fetching actual deterministic ticker data from public APIs.
    We use Yahoo Finance (yfinance) for the prototype to avoid expensive API keys.
    """
    
    def __init__(self):
        # We cache requests locally for 1 minute to avoid yfinance rate limits during rapid polling.
        self._cache = {}

    async def fetch_market_context(self, ticker: str) -> MarketContext:
         # Check simple memory cache
         now = datetime.utcnow()
         if ticker in self._cache:
             cached_time, cached_data = self._cache[ticker]
             if (now - cached_time).total_seconds() < 60:
                 logger.info(f"Using cached MarketContext for {ticker}")
                 return cached_data

         logger.info(f"Fetching live yfinance data for {ticker}...")
         try:
             # Fast API fetch for today's data + history for ATR and MA
             # Needs at least 50 days of history for 50SMA and 14 day ATR
             df = yf.download(ticker, period="3mo", interval="1d", progress=False)

             if df.empty:
                 raise ValueError(f"yfinance returned empty dataset for {ticker}")

             # Standardize column access (yfinance returns MultiIndex sometimes)
             if isinstance(df.columns, pd.MultiIndex):
                 close_col = ('Close', ticker)
                 high_col = ('High', ticker)
                 low_col = ('Low', ticker)
                 vol_col = ('Volume', ticker)
             else:
                 close_col = 'Close'
                 high_col = 'High'
                 low_col = 'Low'
                 vol_col = 'Volume'

             current_price = float(df[close_col].iloc[-1])
             avg_daily_volume = int(df[vol_col].tail(20).mean()) # 20d average volume
             
             # Calculate 14-day ATR (Average True Range)
             # True Range = Max(High-Low, abs(High-PrevClose), abs(Low-PrevClose))
             df['prev_close'] = df[close_col].shift(1)
             tr1 = df[high_col] - df[low_col]
             tr2 = (df[high_col] - df['prev_close']).abs()
             tr3 = (df[low_col] - df['prev_close']).abs()
             df['TR'] = pd.DataFrame({'tr1': tr1, 'tr2': tr2, 'tr3': tr3}).max(axis=1)
             atr_14 = float(df['TR'].rolling(window=14).mean().iloc[-1])
             
             # Calculate 20-day and 50-day Simple Moving Averages
             sma_20 = float(df[close_col].rolling(window=20).mean().iloc[-1])
             sma_50 = float(df[close_col].rolling(window=50).mean().iloc[-1])
             if pd.isna(sma_20): sma_20 = current_price
             if pd.isna(sma_50): sma_50 = current_price

             # Edge case fix if ATR resolves to NaN
             if pd.isna(atr_14):
                 atr_14 = current_price * 0.02 # fallback to 2% daily volatility if math fails

             # Mock a VIX pull (we'll just pull ^VIX directly)
             try:
                 vix_df = yf.download("^VIX", period="5d", progress=False)
                 if isinstance(vix_df.columns, pd.MultiIndex):
                     vix_level = float(vix_df[('Close', '^VIX')].iloc[-1])
                 else:
                     vix_level = float(vix_df['Close'].iloc[-1])
             except Exception:
                 vix_level = 15.0 # Safe default fallback
                 
             context = MarketContext(
                 ticker=ticker,
                 current_price=round(current_price, 2),
                 atr_14=round(atr_14, 2),
                 avg_daily_volume=avg_daily_volume,
                 days_to_earnings=14, # Mocked: requires a different API to get actual EPS dates accurately
                 vix_level=round(vix_level, 2),
                 sma_20=round(sma_20, 2),
                 sma_50=round(sma_50, 2)
             )
             
             self._cache[ticker] = (now, context)
             return context

         except Exception as e:
             logger.error(f"Failed to fetch market data for {ticker}: {e}")
             # Emulate a safe generic fallback so the system doesn't crash completely,
             # but populate it with terrible numbers so Risk Manager rejects it safely.
             return MarketContext(
                 ticker=ticker, current_price=10.0, atr_14=1.0, 
                 avg_daily_volume=0,  # This trips the ADV Liquidity reject rules
                 days_to_earnings=0,  # Trips earnings reject rule
                 vix_level=99.0,      # Trips VIX macro rule
                 sma_20=10.0,
                 sma_50=10.0
             )

    async def generate_technical_summary_string(self, ticker: str, market_context: MarketContext) -> str:
         """Converts raw data into an English summary for the StrategyAgent LLM to consume."""
         cross_status = ""
         if market_context.sma_20 > market_context.sma_50:
             cross_status = "A bullish cross is actively fully confirmed (20SMA > 50SMA)."
         elif market_context.sma_20 < market_context.sma_50:
             cross_status = "A bearish cross is actively fully confirmed (20SMA < 50SMA)."
         return f"Current Price is ${market_context.current_price}. {market_context.avg_daily_volume} ADV. ATR is ${market_context.atr_14}. VIX is sitting at {market_context.vix_level}. {cross_status}"

    async def fetch_news_and_sentiment(self, ticker: str) -> str:
         """Fetches the latest headline news for the ticker to drive LLM sentiment analysis."""
         logger.info(f"Fetching news for {ticker}...")
         try:
             stock = yf.Ticker(ticker)
             news_items = stock.news
             if not news_items:
                 return "No recent news available."
             
             headlines = []
             for item in news_items[:5]:
                 # Yahoo finance news structure varies slightly
                 title = item.get("content", {}).get("title", "") if "content" in item else item.get("title", "")
                 summary = item.get("content", {}).get("summary", "") if "content" in item else item.get("summary", "")
                 
                 if title:
                     clean_summary = summary[:150].replace('\n', ' ') + "..." if summary else ""
                     headlines.append(f"- {title}: {clean_summary}")
                     
             if not headlines:
                 return "No parseable news available."
                 
             return "Recent News Headlines:\n" + "\n".join(headlines)
         except Exception as e:
             logger.error(f"Failed to fetch news for {ticker}: {e}")
             return "Error retrieving news data."

    async def fetch_fundamentals(self, ticker: str) -> str:
         """Fetches key valuation multiples and margins."""
         logger.info(f"Fetching fundamentals for {ticker}...")
         try:
             stock = yf.Ticker(ticker)
             info = stock.info
             
             pe = info.get("trailingPE", "N/A")
             f_pe = info.get("forwardPE", "N/A")
             pb = info.get("priceToBook", "N/A")
             
             dy = info.get("dividendYield", "N/A")
             if dy != "N/A" and dy is not None:
                 # Yahoo Finance dividendYield is usually out of 1.0 (e.g. 0.0038 for 0.38%)
                 # but occasionally format changes. If it is high, we don't multiply.
                 if dy < 1.0:
                     dy = f"{dy*100:.2f}%"
                 else:
                     dy = f"{dy:.2f}%"
                 
             pm = info.get("profitMargins", "N/A")
             if pm != "N/A" and pm is not None:
                 pm = f"{pm*100:.2f}%"
                 
             return f"Trailing P/E: {pe} | Forward P/E: {f_pe} | P/B: {pb} | Div Yield: {dy} | Profit Margins: {pm}"
         except Exception as e:
             logger.error(f"Failed to fetch fundamentals for {ticker}: {e}")
             return "Fundamentals data temporarily unavailable."
