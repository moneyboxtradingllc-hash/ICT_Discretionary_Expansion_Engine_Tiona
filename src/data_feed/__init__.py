import os
from dotenv import load_dotenv
from data_feed.provider_interface import BaseDataProvider, DataFeedError

load_dotenv()


def get_provider() -> BaseDataProvider:
    name = os.getenv("DATA_PROVIDER", "alpaca").lower().strip()
    if name == "alpaca":
        from data_feed.alpaca_provider import AlpacaProvider
        return AlpacaProvider()
    raise DataFeedError(f"Unknown DATA_PROVIDER: {name!r}. Supported: alpaca")
