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

    # REPLAY-1 (2026-07-09) — historical range fetch for the candle archive.
    # NON-abstract on purpose: existing providers keep working unchanged; only
    # providers that can serve arbitrary historical windows override it.
    def fetch_1m_candles_range(self, symbol: str, start, end) -> list:
        """
        Return ALL completed 1-minute candles for symbol in [start, end)
        (timezone-aware datetimes), sorted oldest-first, same candle dict shape
        as fetch_1m_candles. Raise DataFeedError when unsupported or on failure.
        """
        raise DataFeedError(
            f"{type(self).__name__} does not support historical range fetch"
        )
