import os
from dotenv import load_dotenv
from data_feed.provider_interface import BaseDataProvider, DataFeedError

load_dotenv()


RETIRED_PROVIDERS = {"alpaca"}


def get_provider(name: str = None) -> BaseDataProvider:
    """Resolve the market-data provider: explicit `name` → DATA_PROVIDER env.

    There is deliberately NO default. Alpaca was retired on 2026-08-05, and an
    unset DATA_PROVIDER used to resolve to it silently — which would have the
    bot analysing equities while Topstep executes MNQ futures. Absent
    configuration is now a refusal, not a guess.
    """
    name = (name or os.getenv("DATA_PROVIDER", "")).lower().strip()
    if not name:
        raise DataFeedError(
            "DATA_PROVIDER is not set and there is no default. "
            "Set DATA_PROVIDER=topstepx — the retired Alpaca path is not a fallback.")
    if name in RETIRED_PROVIDERS:
        raise DataFeedError(
            f"{name!r} was RETIRED (TopstepX-only doctrine, 2026-08-05). "
            f"The engine trades MNQ on TopstepX; it does not read equity feeds.")
    # TOPSTEPX-DATA-PROVIDER — native MNQ candles built from the TopstepX market
    # hub. Deliberately NOT reachable by sniffing the symbol for "MNQ": the
    # provider is chosen explicitly or not at all. A failure here raises, and
    # the caller gets no candles — an MNQ strategy silently analysing Alpaca
    # equities while Topstep executes futures is the one outcome worth crashing
    # to avoid.
    if name in ("topstepx", "topstep"):
        from data_feed.topstepx_provider import TopstepXDataProvider
        return TopstepXDataProvider()
    raise DataFeedError(
        f"Unknown DATA_PROVIDER: {name!r}. Supported: topstepx")
