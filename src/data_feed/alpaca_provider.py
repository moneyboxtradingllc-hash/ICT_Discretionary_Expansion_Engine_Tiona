import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from data_feed.provider_interface import BaseDataProvider, DataFeedError

load_dotenv()


class AlpacaProvider(BaseDataProvider):
    """
    Reads historical 1m bars from Alpaca's stock data API (read-only).
    Uses the IEX feed — compatible with free Alpaca accounts.
    Does not import or use TradingClient; no order endpoints are touched.
    """

    def __init__(self):
        api_key    = os.getenv("ALPACA_API_KEY",    "").strip()
        secret_key = os.getenv("ALPACA_SECRET_KEY", "").strip()
        if not api_key or not secret_key:
            raise DataFeedError(
                "ALPACA_API_KEY and ALPACA_SECRET_KEY must be set in .env"
            )
        try:
            from alpaca.data.historical import StockHistoricalDataClient
        except ImportError as exc:
            raise DataFeedError(f"alpaca-py not installed: {exc}")

        self._client = StockHistoricalDataClient(
            api_key=api_key,
            secret_key=secret_key,
        )

    def fetch_1m_candles(self, symbol: str, lookback_bars: int = 300) -> list:
        from alpaca.data.requests  import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from alpaca.data.enums     import DataFeed

        end   = datetime.now(timezone.utc)
        # 5 calendar days back — reliably captures the last trading session
        # regardless of time of day, weekends, or holidays.
        # The final slice (candles[-lookback_bars:]) returns only what was requested.
        start = end - timedelta(days=5)

        try:
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Minute,
                start=start,
                end=end,
                feed=DataFeed.IEX,
            )
            bars = self._client.get_stock_bars(request)
        except Exception as exc:
            raise DataFeedError(f"Alpaca API error for {symbol}: {exc}")

        # alpaca-py (Pydantic v2) wraps results in BarSet.data — not dict-subscriptable
        bar_list = bars.data.get(symbol, []) if bars and hasattr(bars, "data") else []
        if not bar_list:
            raise DataFeedError(
                f"No data returned for {symbol}. "
                "Market may be closed or symbol unavailable on the IEX feed."
            )

        candles = [
            {
                "timestamp": bar.timestamp.isoformat(),
                "open":      float(bar.open),
                "high":      float(bar.high),
                "low":       float(bar.low),
                "close":     float(bar.close),
                "volume":    float(bar.volume),
            }
            for bar in bar_list
        ]

        # Keep only the most recent lookback_bars to match the requested window
        return candles[-lookback_bars:] if len(candles) > lookback_bars else candles

    # REPLAY-1 (2026-07-09) — explicit historical window for the candle archive.
    # Identical candle normalization to fetch_1m_candles; no tail slice (the
    # caller asked for the whole window). Read-only, same IEX feed, no order
    # endpoints touched.
    def fetch_1m_candles_range(self, symbol: str, start, end) -> list:
        from alpaca.data.requests  import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from alpaca.data.enums     import DataFeed

        try:
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Minute,
                start=start,
                end=end,
                feed=DataFeed.IEX,
            )
            bars = self._client.get_stock_bars(request)
        except Exception as exc:
            raise DataFeedError(f"Alpaca API error for {symbol}: {exc}")

        bar_list = bars.data.get(symbol, []) if bars and hasattr(bars, "data") else []
        return [
            {
                "timestamp": bar.timestamp.isoformat(),
                "open":      float(bar.open),
                "high":      float(bar.high),
                "low":       float(bar.low),
                "close":     float(bar.close),
                "volume":    float(bar.volume),
            }
            for bar in bar_list
        ]
