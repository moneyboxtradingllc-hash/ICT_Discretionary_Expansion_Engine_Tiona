"""CAUSAL-OCCURRENCE-IDENTITY-1 — what market event is this, as opposed to
which observation of it are we holding.

THE DEFECT THIS ANSWERS. `occurrence_id` was minted from the SCAN timestamp:

    occurrence_id(contract, LIQUIDITY_SWEEP, "15m", snapshot["timestamp"], d)

A 15m raid stays true for as long as its authoring bucket is the newest settled
one -- measured on the 2026-08-25 tape, up to fifteen consecutive 1m scans. Each
of those scans minted a different id, so ONE market event entered the durable
ledger as fifteen facts, and `ActivePath` counted a single counter-raid as
though the market had done it again and again.

The docstring on `occurrence_id` said "scan time is deliberately absent: it
would make identity an artefact of when we looked". The caller passed the scan
time anyway. This module is the correction, and it is deliberately a SEPARATE
NAMESPACE rather than a repair in place:

    occurrence_id       WHICH PERSISTED WITNESS ROW is this?   (unchanged, v1)
    causal_event_key    WHICH MARKET EVENT is this?            (v2)

Historical `occurrence_id` values keep meaning exactly what they meant. Nothing
here reinterprets them, and no stored ledger is upgraded by the existence of
this file.

TWO EVENT CATEGORIES, TWO HONEST SOURCES OF IDENTITY:

    CATEGORY A   derived from a SETTLED BAR
                 LIQUIDITY_SWEEP, STRUCTURE_BREAK
                 identity = the canonical bucket that authored the claim

    CATEGORY B   derived from a STATE TRANSITION in the protected-swing tracker
                 PROTECTED_SWING_REGISTERED / REPLACED / VIOLATED
                 identity = the tracker's own formation provenance
                 *** REFUSED IN 1A -- see CATEGORY_B_BLOCKED. The tracker does
                 not yet own a stable birth time, so no key is minted. ***

Category B may NOT borrow Category A's answer. A registration is not caused by
the bar that happened to be settled when the tracker changed its mind; it is
caused by the swing's formation, and `registered_at` is the tracker's own record
of that. Conversely Category A may not borrow a `registered_at` it does not
have. Forcing one rule onto both would have made one of the two lie.

WHY CATEGORY B IS REFUSED RATHER THAN APPROXIMATED. `swing_id` is
`tf:side:price` and is emphatically NOT unique within a session -- a level can
be taken out and re-form at the identical price. Driven through the real
`ProtectedSwingTracker`, that is not hypothetical:

    13:10  REGISTERED  1m:swing_low:29145.5   registered_at 13:10
    13:20  VIOLATED    29145.5
    13:30  REGISTERED  1m:swing_low:29145.5   registered_at 13:30

Two genuinely different lives of one price, and `(swing_id, registered_at)`
separates them correctly. But the same measurement on a wider tape showed the
INVERSE failure: one continuous, never-violated life carrying many
`registered_at` values, because the tracker re-stamps on reaffirmation. An
identity that splits one event is the same disease as one that merges two, so
Category B mints nothing until the tracker owns a birthday.

FAIL-CLOSED. Every builder returns None when the provenance it needs is absent.
An event whose causal identity cannot be established is not given a manufactured
one -- unprovable identity is not an occurrence, and inventing a key here would
put a fabricated market fact beyond reach in an append-only store.
"""
from __future__ import annotations

from market_data.object_identity import canonical_instant

#: Explicit, never inferred. `V1` is what production runs today; the presence of
#: v2 code is not permission to use it. Selection is owned by the caller, and
#: which caller may select it in production is the subject of the NEXT unit
#: (CAUSAL-IDENTITY-VERSION-GATE-1), deliberately not this one.
CAUSAL_IDENTITY_V1 = 1
CAUSAL_IDENTITY_V2 = 2
DEFAULT_CAUSAL_IDENTITY_VERSION = CAUSAL_IDENTITY_V1
SUPPORTED_CAUSAL_IDENTITY_VERSIONS = (CAUSAL_IDENTITY_V1, CAUSAL_IDENTITY_V2)

#: The v2 key namespace. Present in every key so a v1 and a v2 identity can
#: never be mistaken for one another by a reader, a log, or a store.
V2_PREFIX = "v2"

LIQUIDITY_SWEEP = "LIQUIDITY_SWEEP"
STRUCTURE_BREAK = "STRUCTURE_BREAK"
PROTECTED_SWING_REGISTERED = "PROTECTED_SWING_REGISTERED"
PROTECTED_SWING_REPLACED = "PROTECTED_SWING_REPLACED"
PROTECTED_SWING_VIOLATED = "PROTECTED_SWING_VIOLATED"

#: Settled-bar-derived. Identity comes from the authoring bucket. CERTIFIED.
CATEGORY_A = (LIQUIDITY_SWEEP, STRUCTURE_BREAK)
#: Tracker-transition-derived. Identity comes from formation provenance.
#: NOT CERTIFIED -- see `CATEGORY_B_BLOCKED` below.
CATEGORY_B = (PROTECTED_SWING_REGISTERED, PROTECTED_SWING_REPLACED,
              PROTECTED_SWING_VIOLATED)

#: WHY CATEGORY B STILL MINTS NO v2 IDENTITY, and why the honest answer remains
#: a refusal rather than a provisional key.
#:
#: THE ORIGINAL BLOCKER IS GONE. `(swing_id, registered_at)` always SEPARATED
#: two lives of one price -- driven through the real `ProtectedSwingTracker`, a
#: level that registers, is violated and re-forms at the IDENTICAL price
#: produces two distinct pairs. What it could not do was UNIFY one life:
#: `protected_swings._update` replaced the whole record, `registered_at`
#: included, every time an already-live level was reaffirmed by a fresh raid
#: rejection, even though nothing had died. Measured then:
#:
#:     1m:swing_low:29301   one unbroken life 13:43 -> 14:02, never violated,
#:                          under FIVE registered_at values
#:     2026-08-25            4 of 12 lives re-stamped (33%)
#:     2026-08-24           24 of 33 lives re-stamped (72%), worst 18 stamps
#:
#: PROTECTED-SWING-CAUSAL-TIME-1 fixed that: one continuous life now keeps one
#: immutable birthday, and a re-measurement of both tapes finds zero re-stamps.
#: The provenance these occurrences carry is therefore now TRUE.
#:
#: WHAT REMAINS IS SCOPE, NOT CORRECTNESS. Wiring that provenance into a key --
#: and into the ledger and Active Path dedup that would then consume it -- is
#: CAUSAL-OCCURRENCE-IDENTITY-1B, deliberately its own unit so the identity law
#: is certified separately from the tracker repair that made it possible. Until
#: 1B lands, refusing is still the correct behaviour: a half-wired Category B
#: would put keys into an append-only store under a law nothing has certified.
CATEGORY_B_BLOCKED = (
    "category B has no certified causal identity in this build. The tracker "
    "defect that blocked it (registered_at re-stamped on a living swing) was "
    "repaired by PROTECTED-SWING-CAUSAL-TIME-1, so the provenance is now true; "
    "minting the key from it is CAUSAL-OCCURRENCE-IDENTITY-1B.")


class UnsupportedCausalIdentityVersion(ValueError):
    """A version this build does not implement. Never defaulted around."""


def resolve_version(version) -> int:
    """Accept only a version this build actually implements.

    Silently coercing an unknown version to v1 would let a caller believe it had
    v2 identity while getting v1 dedup -- the exact mixed-epistemology failure
    the version split exists to prevent.
    """
    if version is None:
        return DEFAULT_CAUSAL_IDENTITY_VERSION
    try:
        v = int(version)
    except (TypeError, ValueError):
        raise UnsupportedCausalIdentityVersion(
            f"causal identity version {version!r} is not a version")
    if v not in SUPPORTED_CAUSAL_IDENTITY_VERSIONS:
        raise UnsupportedCausalIdentityVersion(
            f"causal identity version {v} is not supported by this build "
            f"(supported: {list(SUPPORTED_CAUSAL_IDENTITY_VERSIONS)})")
    return v


def _instant(value) -> "str | None":
    """One instant, one string. `strict=False` so a non-canonical stamp stays
    VISIBLE in the key rather than deleting the event -- but two spellings of
    the same parseable instant still collapse to one identity."""
    raw = str(value or "").strip()
    if not raw:
        return None
    return canonical_instant(raw, strict=False)


def _level(value) -> str:
    """A stable spelling for a price in a key. 29145.5 and 29145.50 are one
    level; `repr` would have made them two."""
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return "none" if value is None else str(value)


def causal_event_key(occurrence) -> "str | None":
    """The identity of the MARKET EVENT an occurrence witnesses, or None.

    Returns None -- never a guess -- when the provenance required for this event
    class is absent. The caller decides what to do about that; this module will
    not manufacture a fact.
    """
    if not isinstance(occurrence, dict):
        return None
    et = occurrence.get("event_type")
    contract = str(occurrence.get("contract") or "").strip()
    tf = str(occurrence.get("source_tf") or "").strip()
    if not (et and contract and tf):
        return None

    if et in CATEGORY_A:
        # THE AUTHORING BUCKET, never the scan. `source_bar_time` is published
        # by `snapshot_builder.settled_source_provenance` from the same settled
        # series the detectors were handed, so it is the bar that actually
        # produced the claim rather than a bar chosen to look plausible.
        bar = _instant(occurrence.get("source_bar_time"))
        if not bar:
            return None
        if et == LIQUIDITY_SWEEP:
            direction = occurrence.get("sweep_direction")
            level = occurrence.get("swept_level")
        else:
            direction = occurrence.get("direction")
            level = occurrence.get("broken_level")
        if not direction:
            return None
        return f"{V2_PREFIX}|{et}|{contract}|{tf}|{bar}|{direction}@{_level(level)}"

    if et in CATEGORY_B:
        # REFUSED, DELIBERATELY. The provenance a Category B key needs is
        # CARRIED on these occurrences -- the emitter now publishes `swing_id`,
        # `registered_at` and both ends of a replacement -- but it is not yet
        # TRUE provenance, because the tracker re-stamps a living swing. See
        # `CATEGORY_B_BLOCKED`. A refusal is recoverable; a fragmenting identity
        # written into an append-only store is not.
        return None

    return None


def refusal_reason(occurrence) -> "str | None":
    """WHY this occurrence has no v2 identity, or None when it has one.

    A refusal that cannot say why is indistinguishable from a bug. Category B's
    reason is a KNOWN, MEASURED, NAMED blocker; a Category A reason means real
    provenance was missing from the snapshot, which is a different problem with
    a different owner.
    """
    if not isinstance(occurrence, dict):
        return "not a mapping"
    if causal_event_key(occurrence) is not None:
        return None
    if occurrence.get("event_type") in CATEGORY_B:
        return CATEGORY_B_BLOCKED
    return "required causal provenance is absent from this occurrence"


def identity_of(occurrence, version) -> "str | None":
    """THE dedup authority for a version. Exactly one, never both.

    There is deliberately no "try v2, fall back to v1". A fallback would mean a
    v2 session silently deduped some events by market identity and others by
    observation identity, which is not one epistemology with a gap in it -- it
    is two, interleaved, with no way for a reader to tell which answered.
    """
    v = resolve_version(version)
    if not isinstance(occurrence, dict):
        return None
    if v == CAUSAL_IDENTITY_V1:
        return occurrence.get("occurrence_id") or None
    return causal_event_key(occurrence)
