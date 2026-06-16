import os
from dotenv import load_dotenv
from data_feed.provider_interface import BaseDataProvider, DataFeedError

load_dotenv()


def get_provider(name: str = None) -> BaseDataProvider:
    """Resolve the market-data provider. Selection precedence:
    explicit `name` arg → DATA_PROVIDER env → default 'alpaca'.

    DEPLOY-2A/2B: 'topstep' routes to the ProjectX market-data provider and
    NEVER touches Alpaca. An unknown provider raises (no silent Alpaca fallback)."""
    name = (name or os.getenv("DATA_PROVIDER", "alpaca")).lower().strip()
    if name == "alpaca":
        from data_feed.alpaca_provider import AlpacaProvider
        return AlpacaProvider()
    if name == "topstep":
        from data_feed.topstep_provider import TopstepBarsProvider
        return TopstepBarsProvider()
    raise DataFeedError(f"Unknown DATA_PROVIDER: {name!r}. Supported: alpaca, topstep")
