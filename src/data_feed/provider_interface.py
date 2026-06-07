from abc import ABC, abstractmethod


class DataFeedError(Exception):
    """Raised when a data provider cannot fulfil a request."""


class BaseDataProvider(ABC):
    """
    Contract all data providers must satisfy.

    Providers return 1m candles only.  Higher timeframes are built by
    timeframe_builder so every provider produces consistent aggregations.

    Each candle dict must contain:
        timestamp : str  — ISO 8601, timezone-aware preferred
        open      : float
        high      : float
        low       : float
        close     : float
        volume    : float
    """

    @abstractmethod
    def fetch_1m_candles(self, symbol: str, lookback_bars: int) -> list:
        """
        Return up to lookback_bars completed 1-minute candles for symbol,
        sorted oldest-first.  Raise DataFeedError on any unrecoverable failure.
        """
