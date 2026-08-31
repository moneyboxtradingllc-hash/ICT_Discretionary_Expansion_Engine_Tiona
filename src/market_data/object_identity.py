"""MARKET-OBJECT IDENTITY — one contract for every object Terra can name.

STEP 3F (2026-08-13).

3E gave CANDLE_REFERENCE a proper identity and then stopped there. The derived
facts threaded into the displacement assessment were still being built ad hoc:

    MAGNITUDE_WITNESS:1m:<observed_at>:<anchor>
    FOLLOW_THROUGH_RUN:1m:<observed_at>:<direction>:<run_length>

Two defects in five tokens. Neither carries an INSTRUMENT, so an MNQ and an MES
witness at the same minute collide. And the follow-through id embeds `direction`
and `run_length` -- the ANSWER the calculation produced -- so repairing history
until a run reads 2 instead of 3 mints a second fact object beside the first
instead of revising one.

    IDENTITY names the slot. STATE is what currently fills it.

THE FOUR RULES
--------------
1. CONTRACT SCOPE IS REQUIRED, NEVER DEFAULTED. A low-level id builder that
   falls back to the production contract will happily stamp
   `CON.F.US.MNQ.U26` onto MES bars whose caller forgot to say so. Absent
   provenance is a failure, not an invitation to guess.

2. THE CONTRACT, NOT THE ROOT SYMBOL. `MNQ` does not name an expiry, so the
   September and December buckets at the same instant would collide. When the
   caller knows the contract, a generic alias may not stand in for it.

3. TIME MUST BE UNAMBIGUOUS. An instant with no offset is not an instant.
   `timeframe_builder._floor_timestamp` uses `dt.replace(...)` and preserves
   whatever tzinfo it was handed -- it does NOT normalise to UTC and does not
   guarantee naive-means-UTC. That assumption was a comment, not a contract, so
   it is not relied on here.

4. SCHEMA CORRUPTION MAY NOT MINT A MARKET OBJECT. A malformed timestamp is
   preserved for diagnostics elsewhere; it may never become
   `FVG:CON.F.US.MNQ.U26:1m:garbage`.

DETERMINISTIC IS NOT IMMUTABLE
------------------------------
A derived fact does not "recompute to the same value forever". The correct law:

    same canonical evidence revision + same deterministic rule
        = same derived fact value

The Aug-12 audit proved it -- an ATR-derived ratio moved when the ATR window
moved. History repair does not make a fact nondeterministic; it means the
EVIDENCE changed, and no knowledge resting on superseded history stays
authoritative. That is exactly why identity must name the slot: a repaired FVG
whose source candle is corrected must revise one object, not spawn a twin.
"""
from __future__ import annotations

from datetime import datetime, timezone

#: Root symbols that are NOT precise enough to scope a market object on their
#: own, because they name no expiry. Listed so a refusal can say what it refused.
_AMBIGUOUS_ROOTS = frozenset({"MNQ", "MES", "MYM", "M2K", "NQ", "ES", "YM", "RTY"})


class MarketObjectIdentityError(ValueError):
    """Identity could not be constructed. A schema/provenance defect, never a
    market fact, and never something to paper over with a default."""


def canonical_instant(timestamp, *, strict: bool = True) -> str:
    """ONE INSTANT, ONE STRING.

        2026-08-12T16:00:00Z        ┐
        2026-08-12T16:00:00+00:00   ├─ the same instant, one identity
        2026-08-12T12:00:00-04:00   ┘

    `strict=True` (identity construction) REFUSES a naive or unparseable value.
    `strict=False` (diagnostics, display) returns the raw string so a defect
    stays visible in a report -- but such a value can never reach an id.
    """
    raw = str(timestamp or "")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        if strict:
            raise MarketObjectIdentityError(
                f"timestamp {raw!r} is not parseable; a schema defect may not "
                f"mint a canonical market object identity")
        return raw
    if dt.tzinfo is None:
        if strict:
            raise MarketObjectIdentityError(
                f"timestamp {raw!r} has no UTC offset. `timeframe_builder` "
                f"preserves whatever tzinfo it is given rather than normalising, "
                f"so naive-means-UTC is not a proven producer contract and an "
                f"ambiguous instant cannot author exact identity")
        return raw
    return dt.astimezone(timezone.utc).isoformat()


def canonical_contract(contract=None, instrument=None, *, where: str = "identity") -> str:
    """The contract an object's identity is scoped by. REQUIRED.

    No production default. A helper that quietly supplies `CON.F.US.MNQ.U26`
    when the caller supplied nothing is not defending the MNQ-only doctrine --
    it is manufacturing provenance, and would relabel foreign data as production
    data at exactly the layer nobody re-checks.
    """
    c = str(contract or "").strip()
    if c:
        return c
    root = str(instrument or "").strip().upper()
    if root in _AMBIGUOUS_ROOTS:
        raise MarketObjectIdentityError(
            f"{where}: {root!r} is a root symbol and names no expiry, so it "
            f"cannot scope a market object (the U26 and Z26 buckets at one "
            f"instant would collide). Supply the canonical contract id.")
    if root:
        return root
    raise MarketObjectIdentityError(
        f"{where}: no instrument or contract. Identity is required, never "
        f"inferred -- production must pass its contract explicitly rather than "
        f"letting this layer assume one.")


def market_object_id(kind: str, *, contract=None, instrument=None,
                     timeframe: str = None, instant=None,
                     discriminators: tuple = ()) -> str:
    """`KIND:contract:tf:instant[:immutable-discriminators]`.

    `discriminators` is for dimensions that are genuinely part of WHICH object
    this is -- never for the answer the object currently reports. Before adding
    one, prove the producer can emit two objects of this kind for the same
    contract, timeframe and instant; if it cannot, the slot is already unique
    and anything further is state.
    """
    parts = [kind, canonical_contract(contract, instrument, where=kind)]
    if timeframe:
        parts.append(str(timeframe))
    if instant is not None:
        parts.append(canonical_instant(instant))
    parts.extend(str(d) for d in discriminators if d not in (None, ""))
    return ":".join(parts)


def row_contract(row: dict, *, where: str = "source row") -> str:
    """The contract ONE bar proves, refusing a self-contradicting row.

    STEP 4B §3. Helpers read `contract or contractId`, which silently prefers
    the first when a malformed row carries BOTH:

        contract   = CON.F.US.MNQ.U26
        contractId = CON.F.US.MNQ.Z26

    Two identity authorities on one row disagreeing is a schema defect, and
    `or` would resolve it by field order -- the same "normalise the
    contradiction away" move the epistemic-layer registry already refuses.
    """
    a = str((row or {}).get("contract") or "").strip()
    b = str((row or {}).get("contractId") or "").strip()
    if a and b and a != b:
        raise MarketObjectIdentityError(
            f"{where}: the row declares contract={a!r} and contractId={b!r}. "
            f"Two identity authorities disagree on one bar; that is a schema "
            f"defect, not a precedence question.")
    return a or b


#: STEP 4B.3 §6/§7 — TIMEFRAME IS PART OF IDENTITY, SO GRID VALIDITY IS PART OF
#: IDENTITY VALIDITY.
#:
#: `_bucket_end` proved only that N minutes can be added to any timestamp. It
#: did not prove the timestamp is a legal bucket start for that timeframe:
#:
#:     15m : 17:10   NOT a bucket start (grid is :00 :15 :30 :45)
#:      3m : 17:10   NOT a bucket start (grid is :00 :03 :06 :09 :12 ...)
#:
#: A plausible end time does not legitimise an invalid market slot, and
#: `FVG:...:15m:17:10` names a bucket the builder could never emit.
#:
#: The rule is `timeframe_builder._floor_timestamp`'s: floor minutes-from-
#: midnight in the timestamp's own zone. It is restated as a PREDICATE here
#: rather than re-derived -- a bucket start is valid exactly when flooring it
#: returns itself.
TF_GRID_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60}


def is_aligned_bucket(timestamp, timeframe: str) -> bool:
    """Is this a bucket start the timeframe builder could actually emit?"""
    minutes = TF_GRID_MINUTES.get(timeframe)
    if not minutes:
        return False
    try:
        dt = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return False
    if dt.second or dt.microsecond:
        return False
    return ((dt.hour * 60 + dt.minute) % minutes) == 0


def assert_aligned_bucket(timestamp, timeframe: str, *, where: str = "identity"):
    if timeframe in TF_GRID_MINUTES and not is_aligned_bucket(timestamp, timeframe):
        raise MarketObjectIdentityError(
            f"{where}: {timestamp!r} is not a valid {timeframe} bucket start "
            f"(grid is every {TF_GRID_MINUTES[timeframe]} minutes from "
            f"midnight); a misaligned slot names a bucket the timeframe builder "
            f"could never emit")
    return timestamp
