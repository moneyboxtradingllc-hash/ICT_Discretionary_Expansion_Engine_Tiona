"""Instrument identity law: MNQ on TopstepX, and nothing else.

DECON-3 (2026-08-05). The engine was built on an Alpaca/QQQ equities path. Its
evidence stores are partitioned by symbol — `data/performance/<SYMBOL>/`,
`data/htf_memory/<SYMBOL>.json` — so partitioning is what keeps QQQ statistics
out of an MNQ decision.

That safeguard is defeated by a default. Several call sites resolved the symbol
as `symbol or "QQQ"` or `os.getenv("SCAN_SYMBOL", "QQQ")`, so an unnamed session
would load the QQQ baseline, key the QQQ thesis, and tell Luna it was reading
QQQ. This module replaces every such default with a refusal.

Identity is required, never inferred. A record that does not say which
instrument it came from is excluded — "unlabelled" is not "compatible", and
guessing is precisely how equity evidence would reach a futures decision.
"""
from __future__ import annotations

PRODUCTION_INSTRUMENT = "MNQ"
PRODUCTION_CONTRACT = "CON.F.US.MNQ.U26"
PRODUCTION_VENUE = "TOPSTEPX"

# Retired for good. Listed so a refusal can name what it refused rather than
# reporting a generic mismatch.
RETIRED_INSTRUMENTS = frozenset({"QQQ", "SPY", "IWM", "DIA", "AAPL", "TSLA"})
RETIRED_VENUES = frozenset({"ALPACA"})

RETIRED_HISTORICAL = "RETIRED_HISTORICAL"


class InstrumentIdentityError(RuntimeError):
    """The instrument could not be proven to be the production instrument."""


def normalize(symbol) -> str:
    return str(symbol or "").strip().upper()


def assert_production_instrument(symbol, *, where: str = "production") -> str:
    """Resolve a symbol, or refuse. There is deliberately no default."""
    s = normalize(symbol)
    if not s:
        raise InstrumentIdentityError(
            f"{where}: no instrument. The production instrument is "
            f"{PRODUCTION_INSTRUMENT}; it is never assumed from an empty value.")
    if s in RETIRED_INSTRUMENTS:
        raise InstrumentIdentityError(
            f"{where}: {s} is RETIRED (TopstepX/MNQ doctrine, 2026-08-05). "
            f"It is not silently converted to {PRODUCTION_INSTRUMENT}.")
    if s != PRODUCTION_INSTRUMENT:
        raise InstrumentIdentityError(
            f"{where}: {s} is not the production instrument "
            f"{PRODUCTION_INSTRUMENT}.")
    return s


def assert_production_contract(contract_id, *, where: str = "production") -> str:
    c = str(contract_id or "").strip()
    if c != PRODUCTION_CONTRACT:
        raise InstrumentIdentityError(
            f"{where}: contract {c or '<missing>'} is not the active production "
            f"contract {PRODUCTION_CONTRACT}.")
    return c


# ── evidence eligibility ──────────────────────────────────────────────────────
def record_instrument(record: dict) -> str:
    """The instrument a stored record claims. Empty when it claims none."""
    r = record or {}
    for key in ("instrument", "symbol", "contract_family"):
        v = normalize(r.get(key))
        if v:
            return v
    # The vector-memory schema stores the symbol inside `market_context`, not at
    # the top level. Missing this nest would exclude every legitimate MNQ record
    # as "unlabelled" — a guard that blocks everything protects nothing.
    for nest in ("market_context", "metadata", "provenance"):
        block = r.get(nest)
        if isinstance(block, dict):
            for key in ("instrument", "symbol", "contract_family"):
                v = normalize(block.get(key))
                if v:
                    return v
    return ""


def retrieval_eligible(record: dict) -> tuple:
    """(eligible, reason). Absence of identity is exclusion, not compatibility."""
    r = record or {}
    if str(r.get("status") or "").upper() == RETIRED_HISTORICAL:
        return False, "retired_historical_record"
    if r.get("production_eligible") is False or r.get("retrieval_eligible") is False:
        return False, "record_marked_ineligible"
    inst = record_instrument(r)
    if not inst:
        return False, "missing_instrument_identity"
    if inst in RETIRED_INSTRUMENTS:
        return False, f"retired_instrument:{inst.lower()}"
    if inst != PRODUCTION_INSTRUMENT:
        return False, f"foreign_instrument:{inst.lower()}"
    venue = normalize(r.get("venue"))
    if venue and venue in RETIRED_VENUES:
        return False, f"retired_venue:{venue.lower()}"
    return True, "mnq_topstepx"


def filter_records(records: list) -> tuple:
    """Split stored records into (eligible, rejected-with-reason)."""
    keep, drop = [], []
    for rec in records or []:
        ok, why = retrieval_eligible(rec)
        (keep if ok else drop).append(rec if ok else {"reason": why,
                                                      "instrument": record_instrument(rec)})
    return keep, drop
