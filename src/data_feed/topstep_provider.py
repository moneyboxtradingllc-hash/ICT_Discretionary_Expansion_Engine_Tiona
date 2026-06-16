"""
DEPLOY-2A/2B — Topstep (ProjectX) market-data provider.

Supplies 1m candles for the scan loop from the ProjectX Gateway market-data
endpoints (Contract/search + History/retrieveBars), satisfying the
BaseDataProvider contract used by the rest of the pipeline.

DOCTRINE (hard guarantees):
  * NEVER imports Alpaca; NEVER reads ALPACA_API_KEY / ALPACA_SECRET_KEY.
  * Reads ONLY Topstep/ProjectX credentials (PROJECTX_TOPSTEPX_* preferred,
    TOPSTEP_* fallback).
  * The configured Topstep instrument (e.g. MNQU) is resolved to a ProjectX
    contract id and used as-is — it is NEVER translated to QQQ.
  * On any unavailability (missing creds, auth failure, no contract, no bars)
    raises a clear Topstep-specific DataFeedError — NEVER falls back to Alpaca.

Never silently degrades.
"""
import os
from datetime import datetime, timedelta, timezone

from data_feed.provider_interface import BaseDataProvider, DataFeedError


def _env(*names):
    for n in names:
        v = (os.getenv(n) or "").strip()
        if v:
            return v
    return ""


def _iso(ts):
    """Normalize a ProjectX bar timestamp to an ISO-8601 string."""
    if isinstance(ts, (int, float)):
        # epoch ms or s
        secs = ts / 1000.0 if ts > 1e12 else float(ts)
        return datetime.fromtimestamp(secs, tz=timezone.utc).isoformat()
    return str(ts)


class TopstepBarsProvider(BaseDataProvider):
    def __init__(self):
        # Topstep/ProjectX credentials ONLY. No Alpaca env is ever consulted.
        api_key = _env("PROJECTX_TOPSTEPX_API_KEY", "TOPSTEP_API_KEY")
        username = _env("PROJECTX_TOPSTEPX_USERNAME", "TOPSTEP_USERNAME")
        base_url = _env("PROJECTX_TOPSTEPX_BASE_URL", "TOPSTEP_BASE_URL")
        if not (api_key and username):
            raise DataFeedError(
                "Topstep data feed unavailable: set PROJECTX_TOPSTEPX_USERNAME and "
                "PROJECTX_TOPSTEPX_API_KEY (Topstep/ProjectX market data). "
                "This path does NOT use Alpaca and will not fall back to it.")

        from broker.topstep_adapter import TopstepConfig, TopstepClient, DEFAULT_BASE_URL
        cfg = TopstepConfig(
            api_key=api_key, username=username, account_id="",
            env=(os.getenv("TOPSTEP_ENV", "practice") or "practice").lower(),
            base_url=(base_url or DEFAULT_BASE_URL).rstrip("/"))
        self._client = TopstepClient(cfg)
        auth = self._client.authenticate()
        if not auth.get("ok"):
            raise DataFeedError(
                f"Topstep data feed auth failed: {auth.get('error')} "
                "(no Alpaca fallback).")
        self._contract_cache = {}

    # ── contract resolution ───────────────────────────────────────────────────
    def _resolve_contract(self, symbol: str):
        if symbol in self._contract_cache:
            return self._contract_cache[symbol]
        try:
            contracts = self._client.search_contract(symbol)
        except Exception as exc:  # noqa: BLE001
            raise DataFeedError(f"Topstep contract lookup failed for {symbol!r}: {exc}")
        cid = None
        for c in contracts:
            name = str(c.get("name") or c.get("symbol") or c.get("contractId") or "")
            if symbol.upper() in name.upper():
                cid = c.get("id") or c.get("contractId")
                break
        if cid is None and contracts:
            cid = contracts[0].get("id") or contracts[0].get("contractId")
        if not cid:
            raise DataFeedError(
                f"Topstep: no contract found for {symbol!r} "
                "(expected a Topstep instrument such as MNQU; never translated to QQQ).")
        self._contract_cache[symbol] = cid
        return cid

    # ── BaseDataProvider contract ─────────────────────────────────────────────
    def fetch_1m_candles(self, symbol: str, lookback_bars: int = 300) -> list:
        if not symbol:
            raise DataFeedError(
                "Topstep data feed requires an explicit instrument (e.g. MNQU); "
                "there is no QQQ default on the Topstep path.")
        contract_id = self._resolve_contract(symbol)

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=5)
        try:
            raw = self._client.retrieve_bars(
                contract_id, unit=2, unit_number=1,
                limit=max(int(lookback_bars), 300),
                start=start.isoformat(), end=end.isoformat())
        except Exception as exc:  # noqa: BLE001
            raise DataFeedError(
                f"Topstep bars fetch failed for {symbol} ({contract_id}): {exc}")
        if not raw:
            raise DataFeedError(
                f"Topstep returned no bars for {symbol} ({contract_id}). "
                "Market may be closed or the account lacks market-data entitlement.")

        candles = []
        for b in raw:
            ts = b.get("t") if "t" in b else (b.get("timestamp") or b.get("time"))
            o = b.get("o", b.get("open"))
            h = b.get("h", b.get("high"))
            l = b.get("l", b.get("low"))
            c = b.get("c", b.get("close"))
            v = b.get("v", b.get("volume", 0))
            if ts is None or o is None or h is None or l is None or c is None:
                continue
            candles.append({
                "timestamp": _iso(ts),
                "open": float(o), "high": float(h),
                "low": float(l), "close": float(c),
                "volume": float(v or 0),
            })
        if not candles:
            raise DataFeedError(
                f"Topstep bars for {symbol} could not be parsed into candles.")
        candles.sort(key=lambda x: x["timestamp"])
        return candles[-lookback_bars:] if len(candles) > lookback_bars else candles
