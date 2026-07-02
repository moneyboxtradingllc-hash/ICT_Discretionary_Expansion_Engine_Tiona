import os
from dotenv import load_dotenv
from data_feed.provider_interface import BaseDataProvider, DataFeedError

load_dotenv()


def get_provider(name: str = None) -> BaseDataProvider:
    """Resolve the market-data provider. Selection precedence:
    explicit `name` arg → DATA_PROVIDER env → default 'alpaca'.

    An unknown provider raises (no silent Alpaca fallback)."""
    name = (name or os.getenv("DATA_PROVIDER", "alpaca")).lower().strip()
    if name == "alpaca":
        from data_feed.alpaca_provider import AlpacaProvider
        return AlpacaProvider()
    raise DataFeedError(f"Unknown DATA_PROVIDER: {name!r}. Supported: alpaca")
