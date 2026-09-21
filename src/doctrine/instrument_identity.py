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

import re

PRODUCTION_INSTRUMENT = "MNQ"
PRODUCTION_VENUE = "TOPSTEPX"

#: CONTRACT-MONTH-AUTHORITY-1 (2026-09-21). TopstepX owns which MNQ month is
#: active; this module owns which FAMILY is ours. Those are different questions
#: and conflating them is what broke the September-to-December roll: the guard
#: below pinned one expiry, so the venue resolved the live contract and the
#: authorization refused to sign it.
#:
#: The safety property this module exists for is unchanged — equity and foreign
#: futures evidence must never reach an MNQ decision. A family check keeps that
#: property exactly: ES, MES, ENQ and QQQ are still refused. What it stops doing
#: is fighting a quarterly roll that the venue, not the repository, decides.
#:
#: The month is NOT widened anywhere else. The session still resolves exactly one
#: active contract from TopstepX, the authorization signs that exact id, and
#: `SessionAuthorization.verify` refuses any later session whose resolved
#: contract differs. Structural validity here is not permission to trade a
#: different month — it is only permission to ASK.
PRODUCTION_CONTRACT_FAMILY = "CON.F.US.MNQ"

#: A TopstepX contract id is `CON.F.US.<ROOT>.<MONTH><YY>`. The month codes are
#: the CME set; MNQ lists quarterly (H, M, U, Z) but the structural check does
#: not second-guess venue listing policy — an unexpected-but-well-formed MNQ
#: month is the venue's business, a malformed id is ours.
_MNQ_CONTRACT_RE = re.compile(r"^CON\.F\.US\.MNQ\.[FGHJKMNQUVXZ][0-9]{2}$")

#: A structurally valid member of the family, used as the low-level default for
#: identity builders that have no contract of their own. It is deliberately NOT
#: "the active month" — nothing reads it to decide what to trade.
PRODUCTION_CONTRACT = "CON.F.US.MNQ.U26"

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
    """Prove a contract id is OUR instrument family, or refuse.

    This answers "is this an MNQ futures contract on TopstepX", never "is this
    the month we should be trading today". TopstepX answers the second question
    at startup and the session authorization signs its answer; see
    CONTRACT-MONTH-AUTHORITY-1 above.
    """
    c = str(contract_id or "").strip()
    if not c:
        raise InstrumentIdentityError(
            f"{where}: no contract. The production family is "
            f"{PRODUCTION_CONTRACT_FAMILY}.*; it is never assumed from an "
            f"empty value.")
    if not _MNQ_CONTRACT_RE.match(c):
        raise InstrumentIdentityError(
            f"{where}: contract {c} is not a {PRODUCTION_CONTRACT_FAMILY}.* "
            f"futures identity. TopstepX resolves the active month; this guard "
            f"refuses foreign families and malformed ids.")
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
