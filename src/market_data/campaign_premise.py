"""STAGE 3C-1 — SHADOW LIFE INVENTORY AND SURVIVAL CERTIFICATES.

AUTHORITY: NONE. This module publishes deterministic FACTS about protected
swing lives so a later, separately approved contract can choose among them. It
selects nothing, binds nothing and mints no campaign identity. No Brain input,
prompt, guard, stance, Narrative, Lifecycle, CandidateProducer, plan or Draw
reads its output.

WHAT IS MEASURED
----------------
    INVENTORY     every exact life the CURRENT producer associates with a
                  canonical reclaimed sweep (`sweep_occurrence.
                  protected_swing_lifetime_at_sweep`; today 15m/5m only -- a
                  producer capability, not an approved eligibility policy),
                  joined to its own registration row.
    CERTIFICATE   whether the life's level has been CLOSED THROUGH on its own
                  timeframe since its registration bucket, proven from the
                  settled 1m bars of the current window, bucket by bucket.
    ELIGIBILITY   factual NEW-selection checks only (V1-V5, V7). No role
                  filter, no minimum survival, no chosen premise.

THE TRACKER IS NOT THE PROOF
----------------------------
`ProtectedSwingTracker` judges violation on the NEWEST completed own-timeframe
close it happens to see. A scan cadence that skips that close never sees it
(Stage 3C 2B: 3m 29429.75 survived a 29422 close because no scan saw 03:09 as
newest). The certificate applies the SAME law (close strictly beyond the level
on the life's own timeframe) to EVERY required settled bucket after birth.

REQUIRED BUCKETS ONLY
---------------------
T is the canonical instant of the newest settled 1m bar. An n-minute own-
timeframe bucket opening at B is REQUIRED only once its terminal member
B+(n-1) <= T. A trailing bucket that has not settled is outside the proof
interval: it supplies neither failure nor survival and does not invalidate the
fully covered interval before it. The certificate states the terminal instant
it is proven through (`settled_through`), never a forming close.

PRECEDENCE
----------
    1. lineage (contract/session/history revision) change retires retained
       chain evidence; status is rederived from current permitted evidence;
    2. an independently VALID required post-birth close beyond the level is
       FAILED (earliest witness), even beside an unrelated gap or bad row;
    3. otherwise any missing/invalid required evidence is UNKNOWN;
    4. otherwise INTACT through `settled_through`.

SOURCE ORDER IS PROVENANCE
--------------------------
A required bucket is evidence only as the provider supplied it: its members
must form ONE contiguous chronological run of the supplied series (identical
duplicates aside, exactly as `_canonical_settled_bars` treats them). The
observer never re-sorts a bucket into a cleaner-looking one. A disordered or
interleaved bucket is invalid on its own; other buckets keep their own verdict.

RETAINED CHAINS
---------------
FAILED and INTACT retention obey the SAME rule: same lineage, a cutoff that
does not move backwards, and the retained tip bucket present in the current
window with identical member digests. Anything else retires the chain and the
certificate is recomputed from current permitted evidence only. A continued
FAILED chain keeps its earliest witness and still advances its tip.

WATCHED LIVES
-------------
An explicit watch names one exact life of THIS contract and production
session, registered by T, with a coherent registration anchor. A foreign,
malformed or contradicted ref is refused (UNKNOWN, never measured, never
retained); the observer never substitutes another life for it.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

SCHEMA = "campaign_premise_shadow/v1"
AUTHORITY = "none"
ASSOCIATION_SOURCE = "sweep_occurrence.protected_swing_lifetime_at_sweep"

AVAILABLE = "AVAILABLE"
UNAVAILABLE = "UNAVAILABLE"
INTACT = "INTACT"
FAILED = "FAILED"
UNKNOWN = "UNKNOWN"

#: An explicit observation interface for a future owner; never a selector.
MAX_WATCHED_LIVES = 2
#: Published reasons are bounded; a pathological input cannot grow the block.
REASON_CAP = 160
#: Diagnostic lists are bounded for the same reason.
DIAGNOSTIC_CAP = 8

_TF_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15}
_SWEEP = "LIQUIDITY_SWEEP"
_REGISTERED = "PROTECTED_SWING_REGISTERED"
_REPLACED = "PROTECTED_SWING_REPLACED"
_VIOLATED = "PROTECTED_SWING_VIOLATED"


@dataclass(frozen=True)
class LifeRef:
    """One exact protected-swing life. Identity is the full tuple, never price."""

    contract_id: str
    market_session: str
    source_tf: str
    side: str
    swing_id: str
    registered_at: str
    level: float
    basis: str
    registration_occurrence_id: str | None
    registration_bucket_open: str | None

    def identity(self) -> tuple:
        return (self.contract_id, self.market_session, self.source_tf, self.side,
                self.swing_id, self.registered_at, self.level, self.basis)

    def as_dict(self) -> dict:
        return asdict(self)


# ── small canonical helpers ─────────────────────────────────────────────────
def _bounded(text) -> str:
    text = str(text)
    return text if len(text) <= REASON_CAP else text[:REASON_CAP - 3] + "..."


def _instant(value) -> "str | None":
    """Canonical UTC instant, or None for a naive/unparseable value."""
    if value is None or value == "":
        return None
    try:
        from market_data.object_identity import canonical_instant
        return canonical_instant(value, strict=True)
    except Exception:  # noqa: BLE001 -- ambiguous time is not evidence
        return None


def _dt(instant: str) -> datetime:
    return datetime.fromisoformat(instant)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def _floor(moment: datetime, minutes: int) -> datetime:
    """Clock-aligned bucket open in UTC (epoch minutes are day-aligned)."""
    epoch_minutes = int(moment.timestamp() // 60)
    floored = epoch_minutes - (epoch_minutes % minutes)
    return datetime.fromtimestamp(floored * 60, tz=timezone.utc)


def _finite(value) -> "float | None":
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _side_registry(protected_by_timeframe, side) -> dict:
    block = protected_by_timeframe if isinstance(protected_by_timeframe, dict) else {}
    registry = block.get("lows" if side == "low" else "highs")
    return registry if isinstance(registry, dict) else {}


def _available(row: dict, cutoff: str) -> bool:
    """A ledger row is usable at T only if it was observed and sourced by T."""
    event = _instant(row.get("event_time"))
    source = _instant(row.get("source_bar_time") or row.get("event_time"))
    observed = _instant(row.get("observed_at") or row.get("event_time"))
    return bool(event and source and observed
                and event <= cutoff and source <= cutoff and observed <= cutoff)


def _canonical_sweep(row: dict, contract_id: str) -> bool:
    """The canonical (market_object_id) schema; never a v1 scan-time id."""
    if row.get("event_type") != _SWEEP or not isinstance(row.get("source_bars"), list):
        return False
    try:
        from market_data.object_identity import market_object_id
        expected = market_object_id(_SWEEP, contract=contract_id,
                                    timeframe=str(row.get("source_tf")),
                                    instant=row.get("event_time"))
    except Exception:  # noqa: BLE001
        return False
    return row.get("occurrence_id") == expected


def _session_of(value) -> "str | None":
    try:
        from market_state.active_path import production_session_key
        return production_session_key(value)
    except Exception:  # noqa: BLE001
        return None


def _matches_life(row: dict, life: LifeRef) -> bool:
    """Exact identity of a ledger record against a life (never price alone)."""
    level = _finite(row.get("level"))
    return bool(row.get("swing_id") == life.swing_id
                and _instant(row.get("registered_at")) == life.registered_at
                and level is not None and level == life.level)


def _slot_holds(protected_by_timeframe, life: LifeRef) -> bool:
    record = _side_registry(protected_by_timeframe, life.side).get(life.source_tf)
    if not isinstance(record, dict):
        return False
    level = _finite(record.get("level"))
    return bool(record.get("swing_id") == life.swing_id
                and _instant(record.get("registered_at")) == life.registered_at
                and level is not None and level == life.level
                and record.get("basis") == life.basis
                and record.get("timeframe") in (None, life.source_tf))


def _terminal_event(ledger_rows, life: LifeRef, cutoff: str) -> "dict | None":
    """Earliest exact VIOLATED/REPLACED of this life available by T."""
    found = []
    for row in ledger_rows or ():
        if not isinstance(row, dict) or row.get("contract") != life.contract_id:
            continue
        if row.get("source_tf") != life.source_tf or row.get("side") != life.side:
            continue
        if not _available(row, cutoff):
            continue
        kind = row.get("event_type")
        if kind == _VIOLATED and _matches_life(row, life):
            found.append(row)
        elif (kind == _REPLACED and row.get("old_swing_id") == life.swing_id
              and _instant(row.get("old_registered_at")) == life.registered_at):
            found.append(row)
    if not found:
        return None
    first = min(found, key=lambda r: (_instant(r.get("event_time")) or "",
                                      str(r.get("occurrence_id"))))
    return {"type": first.get("event_type"),
            "occurrence_id": first.get("occurrence_id"),
            "event_time": _instant(first.get("event_time"))}


# ── inventory ───────────────────────────────────────────────────────────────
def _association_key(row: dict, contract_id: str, market_session: str):
    """(identity tuple, None) or (None, reason) for one canonical association."""
    life = row.get("protected_swing_lifetime")
    if not isinstance(life, dict):
        return None, "no_association"
    side = {"below_low": "low", "above_high": "high"}.get(row.get("sweep_direction"))
    level = _finite(life.get("level"))
    swept = _finite(row.get("swept_level"))
    registered = _instant(life.get("registered_at"))
    if (life.get("contract") != contract_id or row.get("contract") != contract_id):
        return None, "association_contract_mismatch"
    if life.get("market_session") != market_session:
        return None, "association_other_session"
    if (life.get("source_tf") != row.get("source_tf") or life.get("side") != side
            or side is None):
        return None, "association_shape_mismatch"
    if (level is None or swept is None or level != swept or not life.get("swing_id")
            or registered is None or not life.get("basis")):
        return None, "association_malformed"
    if row.get("reclaimed") is not True:
        return None, "association_not_reclaimed"
    return (contract_id, market_session, row.get("source_tf"), side,
            str(life.get("swing_id")), registered, level, str(life.get("basis"))), None


def life_inventory(*, ledger_rows, protected_by_timeframe, contract_id,
                   market_session, cutoff) -> list:
    """Every exact life the current producer associates, as of cutoff T.

    Rows are recomputed from the supplied ledger rows on every call; nothing is
    retained. Each row is detached from its inputs.
    """
    cutoff = _instant(cutoff)
    if cutoff is None or not contract_id or not market_session:
        return []
    rows = [copy.deepcopy(r) for r in (ledger_rows or ())
            if isinstance(r, dict) and r.get("contract") == contract_id]

    # One canonical id is one fact. Identical copies collapse to the first;
    # different payloads under one id are conflicting evidence, never a pick.
    copies: dict = {}
    for row in rows:
        if _canonical_sweep(row, contract_id):
            copies.setdefault(row.get("occurrence_id"), []).append(row)
    conflicting = {oid for oid, found in copies.items()
                   if len({json.dumps(r, sort_keys=True, default=str) for r in found}) > 1}

    grouped: dict = {}
    excluded: list = []
    conflicted: dict = {}
    for oid, found in copies.items():
        if oid not in conflicting:
            continue
        excluded.append((oid, "canonical_payload_conflict"))
        for row in found:
            observed = _instant((row.get("protected_swing_lifetime") or {})
                                .get("observed_at"))
            if not _available(row, cutoff) or observed is None or observed > cutoff:
                continue
            key, _ = _association_key(row, contract_id, market_session)
            if key is not None:
                conflicted.setdefault(key, set()).add(oid)
                grouped.setdefault(key, [])
    for oid, found in copies.items():
        row = found[0]
        if oid in conflicting:
            continue
        if not isinstance(row.get("protected_swing_lifetime"), dict):
            continue
        observed = _instant((row.get("protected_swing_lifetime") or {}).get("observed_at"))
        if not _available(row, cutoff) or observed is None or observed > cutoff:
            excluded.append((row.get("occurrence_id"), "association_not_available_at_cutoff"))
            continue
        key, reason = _association_key(row, contract_id, market_session)
        if key is None:
            excluded.append((row.get("occurrence_id"), reason))
            continue
        grouped.setdefault(key, []).append(row)

    # V7: the same exact life slot named with conflicting level/basis.
    slot_names: dict = {}
    for key in grouped:
        slot_names.setdefault(key[:6], set()).add(key)

    out = []
    for key in sorted(grouped, key=lambda k: (k[5], k[2], k[3], k[4], k[6], k[7])):
        contract, session, tf, side, swing_id, registered_at, level, basis = key
        sweeps = sorted(grouped[key], key=lambda r: (_instant(r.get("event_time")) or "",
                                                      str(r.get("occurrence_id"))))
        probe = LifeRef(contract, session, tf, side, swing_id, registered_at, level,
                        basis, None, None)
        registrations, replacement_births = [], []
        for row in rows:
            if (row.get("source_tf") != tf or row.get("side") != side
                    or not _available(row, cutoff)
                    or _session_of(row.get("event_time")) != session):
                continue
            if row.get("event_type") == _REGISTERED and _matches_life(row, probe) \
                    and row.get("basis") == basis:
                registrations.append(row)
            elif row.get("event_type") == _REPLACED and _matches_life(row, probe) \
                    and row.get("basis") == basis:
                replacement_births.append(row)
        registration = registrations[0] if len(registrations) == 1 else None
        bucket_open = None
        if registration is not None:
            source = _instant(registration.get("source_bar_time"))
            minutes = _TF_MINUTES.get(tf)
            if source and minutes and _iso(_floor(_dt(source), minutes)) == source:
                bucket_open = source
        life = LifeRef(contract, session, tf, side, swing_id, registered_at, level,
                       basis,
                       registration.get("occurrence_id") if registration else None,
                       bucket_open)
        out.append({
            **life.as_dict(),
            "association_source": ASSOCIATION_SOURCE,
            "sweep_occurrence_ids": [r.get("occurrence_id") for r in sweeps],
            "tracker_slot_present": _slot_holds(protected_by_timeframe, life),
            "terminal_event": _terminal_event(rows, life, cutoff),
            "join": {
                "registration_rows": len(registrations),
                "replacement_birth_rows": len(replacement_births),
                "registration_anchor_aligned": bucket_open is not None,
                "tuple_conflict": len(slot_names.get(key[:6], ())) > 1,
            },
        })
        if key in conflicted:
            out[-1]["join"]["conflicting_sweep_ids"] = sorted(conflicted[key])
    if excluded:
        for row in out:
            row["join"]["excluded_associations_at_cutoff"] = len(excluded)
    return out


def life_ref(row: dict) -> LifeRef:
    """The frozen identity of one inventory row."""
    return LifeRef(**{name: row.get(name) for name in LifeRef.__dataclass_fields__})


# ── certificate ─────────────────────────────────────────────────────────────
def _lineage_id(life: LifeRef, history_revision, contract_id) -> str:
    payload = json.dumps([contract_id, life.market_session, history_revision,
                          list(life.identity())], default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _index_rows(settled_1m, cutoff: str):
    """{instant: [(source position, row)]} for rows at or before T, the rank of
    each instant's FIRST occurrence in the supplied series, and the number of
    unplaceable rows. Ranks are what `_canonical_settled_bars` orders by."""
    index, rank, unplaceable = {}, {}, 0
    for position, row in enumerate(settled_1m or ()):
        stamp = _instant(row.get("timestamp")) if isinstance(row, dict) else None
        if stamp is None:
            unplaceable += 1
            continue
        rank.setdefault(stamp, len(rank))
        if stamp > cutoff:
            continue
        index.setdefault(stamp, []).append((position, row))
    return index, rank, unplaceable


def _bucket(index, rank, *, opening: datetime, minutes: int, contract_id: str) -> dict:
    """Validate ONE own-timeframe bucket independently of every other bucket.

    Members are validated in the order the provider supplied them and must be
    one contiguous chronological run of that series; a bucket is never sorted
    into existence."""
    from market_data.campaign_draw_truth import _bar_digest, _canonical_settled_bars
    expected = [_iso(opening + timedelta(minutes=i)) for i in range(minutes)]
    terminal = expected[-1]
    present = [stamp for stamp in expected if stamp in index]
    following = _iso(opening + timedelta(minutes=minutes))
    expected_set = set(expected)
    extras = [s for s in index if expected[0] <= s < following and s not in expected_set]
    out = {"open": expected[0], "terminal": terminal, "valid": False,
           "present": len(present) + len(extras), "close": None,
           "member_digests": [], "reason": None}
    if extras:
        out["reason"] = "unexpected_member_instant"
        return out
    if not present:
        out["reason"] = "no_members"
        return out
    if len(present) != minutes:
        missing = [s for s in expected if s not in index]
        out["reason"] = ("missing_terminal_member" if terminal in missing
                         else "missing_interior_member")
        return out
    supplied = sorted((pair for stamp in expected for pair in index[stamp]),
                      key=lambda pair: pair[0])
    normalized, reason = _canonical_settled_bars(
        [copy.deepcopy(row) for _, row in supplied], contract_id)
    if reason:
        out["reason"] = _bounded(f"member_invalid:{reason}")
        return out
    ranks = [rank[stamp] for stamp in expected]
    if ranks != list(range(ranks[0], ranks[0] + minutes)):
        out["reason"] = "member_order_interleaved"
        return out
    if [row.get("timestamp") for row in normalized] != expected:
        out["reason"] = "membership_mismatch"
        return out
    out.update({"valid": True, "close": normalized[-1]["close"],
                "member_digests": [_bar_digest(row) for row in normalized]})
    return out


def _closure_explained(index, *, opening: datetime, terminal: datetime) -> bool:
    """A required bucket with NO members is excused only when the venue was
    provably closed across it (existing evidence_continuity classification)."""
    from market_data.evidence_continuity import EXPECTED_MARKET_BREAK, evaluate
    before = [s for s in index if s < _iso(opening)]
    after = [s for s in index if s > _iso(terminal)]
    if not before or not after:
        return False
    report = evaluate([max(before), min(after)], source_tf="1m")
    return report.get("continuity_class") == EXPECTED_MARKET_BREAK


def _witness_agrees(index, rank, witness: dict, *, minutes: int, contract_id: str) -> bool:
    """The retained failure witness is not contradicted by the current window.

    Absent (rolled out) agrees. Fully present must validate with identical
    digests. Partly present is allowed only as the leading edge of the window
    (a suffix of the bucket), whose members must match the retained digests."""
    from market_data.campaign_draw_truth import _bar_digest, _canonical_settled_bars
    opening = _dt(witness["open"])
    expected = [_iso(opening + timedelta(minutes=i)) for i in range(minutes)]
    digests = list(witness.get("member_digests") or [])
    present = [stamp for stamp in expected if stamp in index]
    if not present:
        return True
    if len(present) == minutes:
        check = _bucket(index, rank, opening=opening, minutes=minutes,
                        contract_id=contract_id)
        return check["valid"] and check["member_digests"] == digests
    first = expected.index(present[0])
    if (present != expected[first:] or present[0] != min(index)
            or len(digests) != minutes):
        return False
    supplied = sorted((pair for stamp in present for pair in index[stamp]),
                      key=lambda pair: pair[0])
    normalized, reason = _canonical_settled_bars(
        [copy.deepcopy(row) for _, row in supplied], contract_id)
    return (reason is None
            and [row.get("timestamp") for row in normalized] == present
            and [_bar_digest(row) for row in normalized] == digests[first:])


def _chain_continues(chain, *, lineage_id, index, rank, cutoff, minutes, contract_id):
    """(continues, retained failure witness or None) for one retained chain."""
    if not chain or chain.get("lineage_id") != lineage_id:
        return False, None
    if chain.get("status") not in (INTACT, FAILED) or not chain.get("tip_bucket_open"):
        return False, None
    previous = _instant(chain.get("cutoff") or chain.get("settled_through"))
    if previous is None or cutoff < previous:
        return False, None                      # non-monotonic cutoff
    tip = _bucket(index, rank, opening=_dt(chain["tip_bucket_open"]), minutes=minutes,
                  contract_id=contract_id)
    if not (tip["valid"] and tip["member_digests"] == chain.get("tip_member_digests")):
        return False, None                      # changed or missing tip
    if chain.get("status") == INTACT:
        return True, None
    witness = chain.get("failure_bucket")
    if not isinstance(witness, dict) or not witness.get("open") or not _witness_agrees(
            index, rank, witness, minutes=minutes, contract_id=contract_id):
        return False, None
    return True, copy.deepcopy(witness)


def observe_life(life, *, settled_1m, history_revision, contract_id, cutoff,
                 retained=None) -> dict:
    """The survival certificate of ONE exact life at cutoff T. Never raises."""
    try:
        return _observe(life, settled_1m=settled_1m, history_revision=history_revision,
                        contract_id=contract_id, cutoff=cutoff, retained=retained)
    except Exception as exc:  # noqa: BLE001 -- an observer failure is UNKNOWN
        return {"status": UNKNOWN, "reason": _bounded(f"observer_error:{type(exc).__name__}"),
                "own_tf": getattr(life, "source_tf", None),
                "registration_bucket_open": getattr(life, "registration_bucket_open", None),
                "first_covered": None, "last_covered": None, "settled_through": None,
                "failure_bucket": None, "covered_buckets": 0, "tip_bucket_open": None,
                "tip_member_digests": [], "history_revision": history_revision,
                "lineage_id": None, "cutoff": None}


def _observe(life, *, settled_1m, history_revision, contract_id, cutoff, retained):
    cutoff = _instant(cutoff)
    minutes = _TF_MINUTES.get(getattr(life, "source_tf", None))
    cert = {"status": UNKNOWN, "reason": None, "own_tf": getattr(life, "source_tf", None),
            "registration_bucket_open": getattr(life, "registration_bucket_open", None),
            "first_covered": None, "last_covered": None, "settled_through": None,
            "failure_bucket": None, "covered_buckets": 0, "tip_bucket_open": None,
            "tip_member_digests": [], "history_revision": history_revision,
            "lineage_id": None, "cutoff": None}
    if not isinstance(life, LifeRef):
        cert["reason"] = "life_ref_invalid"
        return cert
    cert["lineage_id"] = _lineage_id(life, history_revision, contract_id)
    if cutoff is None:
        cert["reason"] = "cutoff_unparseable"
        return cert
    if minutes is None:
        cert["reason"] = "unsupported_timeframe"
        return cert
    if life.contract_id != contract_id:
        cert["reason"] = "contract_mismatch"
        return cert
    anchor = _instant(life.registration_bucket_open)
    if anchor is None or _iso(_floor(_dt(anchor), minutes)) != anchor:
        cert["reason"] = "registration_anchor_unavailable"
        return cert

    index, rank, unplaceable = _index_rows(settled_1m, cutoff)
    step = timedelta(minutes=minutes)
    anchor_dt = _dt(anchor)
    cutoff_dt = _dt(cutoff)

    # Retained chain: FAILED and INTACT obey ONE rule -- same lineage, a cutoff
    # that never moves backwards, and the retained tip bucket present now with
    # identical member digests. Anything else retires the chain.
    chain = retained if isinstance(retained, dict) else None
    chain_valid, retained_failure = _chain_continues(
        chain, lineage_id=cert["lineage_id"], index=index, rank=rank, cutoff=cutoff,
        minutes=minutes, contract_id=contract_id)

    # Registration anchor: complete source membership (no close-through test).
    if chain_valid:
        start = _dt(chain["tip_bucket_open"]) + step
        covered = int(chain.get("covered_buckets") or 0)
        first_covered = chain.get("first_covered")
        tip_open = chain["tip_bucket_open"]
        tip_digests = list(chain.get("tip_member_digests") or [])
        coverage_ok = True
        coverage_reason = None
    else:
        anchor_check = _bucket(index, rank, opening=anchor_dt, minutes=minutes,
                               contract_id=contract_id)
        coverage_ok = anchor_check["valid"]
        coverage_reason = (None if coverage_ok else
                           ("registration_anchor_outside_window"
                            if not anchor_check["present"] and (
                                not index or min(index) > anchor)
                            else f"registration_anchor_{anchor_check['reason']}"))
        start = anchor_dt + step
        covered = 0
        first_covered = None
        tip_open = anchor if coverage_ok else None
        tip_digests = list(anchor_check["member_digests"]) if coverage_ok else []

    if unplaceable:
        coverage_ok = False
        coverage_reason = coverage_reason or "unplaceable_settled_rows"

    failure = None
    last_required = None
    opening = start
    # Bounded by the supplied window: buckets before the first row cannot be
    # proven, and are skipped as one coverage gap rather than iterated.
    first_row = _dt(min(index)) if index else None
    if first_row is not None and opening < first_row:
        skipped = (first_row - opening) // step
        if skipped > 0:
            coverage_ok = False
            coverage_reason = coverage_reason or "required_buckets_before_window"
            opening = opening + skipped * step
    while opening + step - timedelta(minutes=1) <= cutoff_dt:
        terminal = opening + step - timedelta(minutes=1)
        last_required = opening
        bucket = _bucket(index, rank, opening=opening, minutes=minutes, contract_id=contract_id)
        if bucket["valid"]:
            close = _finite(bucket["close"])
            beyond = close is not None and (
                close < life.level if life.side == "low" else close > life.level)
            if beyond and failure is None:
                failure = {"open": bucket["open"], "terminal": bucket["terminal"],
                           "close": close, "member_digests": bucket["member_digests"]}
            covered += 1
            first_covered = first_covered or bucket["open"]
            tip_open, tip_digests = bucket["open"], bucket["member_digests"]
        elif not bucket["present"] and _closure_explained(index, opening=opening,
                                                         terminal=terminal):
            pass                       # venue provably closed across this bucket
        else:
            coverage_ok = False
            coverage_reason = coverage_reason or _bounded(
                f"required_bucket_{bucket['reason']}:{bucket['open']}")
        opening = opening + step

    cert["first_covered"] = first_covered
    cert["last_covered"] = (_iso(last_required) if last_required is not None
                            else (chain.get("last_covered") if chain_valid else None))
    if last_required is not None:
        cert["settled_through"] = _iso(last_required + step - timedelta(minutes=1))
    elif chain_valid:
        cert["settled_through"] = chain.get("settled_through")
    else:
        cert["settled_through"] = _iso(anchor_dt + step - timedelta(minutes=1))
    cert["covered_buckets"] = covered
    cert["tip_bucket_open"] = tip_open
    cert["tip_member_digests"] = list(tip_digests)

    cert["cutoff"] = cutoff
    if retained_failure is not None:
        cert.update({"status": FAILED, "reason": "failure_witness_retained",
                     "failure_bucket": retained_failure})
    elif failure is not None:
        cert.update({"status": FAILED, "reason": "valid_close_beyond_level",
                     "failure_bucket": failure})
    elif not coverage_ok:
        cert.update({"status": UNKNOWN, "reason": coverage_reason})
    else:
        cert.update({"status": INTACT, "reason": "all_required_buckets_valid"})
    return cert


def apply_tracker_witness(certificate: dict, terminal_event) -> dict:
    """A tracker VIOLATED of the exact life against an INTACT bar certificate is
    a conflict, never silently reconciled. REPLACED affects eligibility only."""
    cert = copy.deepcopy(certificate)
    if (isinstance(terminal_event, dict) and terminal_event.get("type") == _VIOLATED
            and cert.get("status") == INTACT):
        cert["status"] = UNKNOWN
        cert["reason"] = "tracker_certificate_conflict"
    return cert


# ── eligibility ─────────────────────────────────────────────────────────────
def selection_eligibility(row, certificate, *, protected_by_timeframe, ledger_rows,
                          cutoff) -> dict:
    """Factual NEW-selection eligibility: V1-V5, V7. No V6, no K, no choice.

    V7 is conflicting facts for one identity: conflicting level/basis for the
    same life slot, or different payloads under one canonical sweep id."""
    failures = []
    cutoff = _instant(cutoff)
    try:
        life = life_ref(row)
    except Exception:  # noqa: BLE001
        return {"eligible": False, "failures": ["V1", "V2", "V3", "V4", "V5", "V7"]}
    join = row.get("join") if isinstance(row.get("join"), dict) else {}
    if not row.get("sweep_occurrence_ids"):
        failures.append("V1")
    if (join.get("registration_rows") != 1 or not life.registration_occurrence_id
            or not life.registration_bucket_open):
        failures.append("V2")
    if not _slot_holds(protected_by_timeframe, life):
        failures.append("V3")
    if cutoff is None or _terminal_event(ledger_rows, life, cutoff) is not None:
        failures.append("V4")
    if not isinstance(certificate, dict) or certificate.get("status") != INTACT:
        failures.append("V5")
    if join.get("tuple_conflict") is not False or join.get("conflicting_sweep_ids"):
        failures.append("V7")
    return {"eligible": not failures, "failures": failures}


# ── the per-cycle shadow ────────────────────────────────────────────────────
def _watch_refusal(life: LifeRef, *, contract_id, market_session, cutoff,
                   rows) -> "str | None":
    """Why an explicit watched ref is not a life of THIS context, else None.

    Checked before any measurement or retention. A valid life whose slot has
    gone or that was replaced is still a valid life; only a foreign, malformed
    or contradicted reference is refused."""
    if life.contract_id != contract_id:
        return "watched_life_foreign_contract"
    if life.market_session != market_session:
        return "watched_life_foreign_session"
    minutes = _TF_MINUTES.get(life.source_tf)
    if minutes is None:
        return "watched_life_unsupported_timeframe"
    if life.side not in ("low", "high"):
        return "watched_life_invalid_side"
    level = _finite(life.level)
    if level is None or level != life.level:
        return "watched_life_invalid_level"
    if not isinstance(life.swing_id, str) or not life.swing_id \
            or not isinstance(life.basis, str) or not life.basis:
        return "watched_life_invalid_identity"
    registered = _instant(life.registered_at)
    if registered is None or registered != life.registered_at:
        return "watched_life_registered_at_not_canonical"
    if registered > cutoff:
        return "watched_life_registered_after_cutoff"
    if _session_of(registered) != market_session:
        return "watched_life_registered_in_other_session"
    anchor = life.registration_bucket_open
    if anchor is not None:
        anchor = _instant(anchor)
        if (anchor is None or anchor != life.registration_bucket_open
                or _iso(_floor(_dt(anchor), minutes)) != anchor or anchor > registered):
            return "watched_life_registration_anchor_invalid"
    # The ref may not contradict the producer's own registration record.
    for row in rows:
        if row.get("event_type") != _REGISTERED:
            continue
        named = (life.registration_occurrence_id is not None
                 and row.get("occurrence_id") == life.registration_occurrence_id)
        same_life = (row.get("source_tf") == life.source_tf
                     and row.get("side") == life.side and _matches_life(row, life)
                     and row.get("basis") == life.basis)
        if not (named or same_life):
            continue
        if not same_life:
            return "watched_life_registration_mismatch"
        if (life.registration_occurrence_id is not None
                and row.get("occurrence_id") != life.registration_occurrence_id):
            return "watched_life_registration_mismatch"
        if anchor is not None and _instant(row.get("source_bar_time")) != anchor:
            return "watched_life_registration_mismatch"
    return None


def _refused_certificate(life: LifeRef, reason: str, history_revision, cutoff) -> dict:
    return {"status": UNKNOWN, "reason": _bounded(reason),
            "own_tf": life.source_tf,
            "registration_bucket_open": life.registration_bucket_open,
            "first_covered": None, "last_covered": None, "settled_through": None,
            "failure_bucket": None, "covered_buckets": 0, "tip_bucket_open": None,
            "tip_member_digests": [], "history_revision": history_revision,
            "lineage_id": None, "cutoff": cutoff}


def unavailable(*, reason, cutoff=None, history_revision=None, contract_id=None,
                market_session=None) -> dict:
    return {"schema": SCHEMA, "authority": AUTHORITY, "status": UNAVAILABLE,
            "reason": _bounded(reason), "cutoff": _instant(cutoff),
            "history_revision": history_revision, "contract_id": contract_id,
            "market_session": market_session, "lives": [], "watched_lives": [],
            "retained_chains": 0}


class CampaignPremiseShadow:
    """Process-local shadow facts. Production passes no watched lives, so it
    retains ZERO chains; an explicit observer may watch at most two."""

    def __init__(self):
        self._chains: dict = {}
        self._lineage = None

    def reset(self) -> None:
        self._chains = {}
        self._lineage = None

    @property
    def retained_chains(self) -> int:
        return len(self._chains)

    def advance(self, *, snapshot, settled_1m, ledger_rows, history_revision,
                contract_id, market_session, cutoff, watched_lives=()) -> dict:
        try:
            return self._advance(snapshot=snapshot, settled_1m=settled_1m,
                                 ledger_rows=ledger_rows,
                                 history_revision=history_revision,
                                 contract_id=contract_id,
                                 market_session=market_session, cutoff=cutoff,
                                 watched_lives=watched_lives)
        except Exception as exc:  # noqa: BLE001 -- shadow facts never cost a scan
            return unavailable(reason=f"shadow_error:{type(exc).__name__}",
                               cutoff=cutoff, history_revision=history_revision,
                               contract_id=contract_id, market_session=market_session)

    def _advance(self, *, snapshot, settled_1m, ledger_rows, history_revision,
                 contract_id, market_session, cutoff, watched_lives):
        stamp = _instant(cutoff)
        if stamp is None:
            return unavailable(reason="cutoff_unparseable", cutoff=None,
                               history_revision=history_revision,
                               contract_id=contract_id, market_session=market_session)
        if isinstance(history_revision, bool) or not isinstance(history_revision, int):
            return unavailable(reason="history_revision_invalid", cutoff=stamp,
                               contract_id=contract_id, market_session=market_session)
        if not contract_id or not market_session:
            return unavailable(reason="contract_or_session_unavailable", cutoff=stamp,
                               history_revision=history_revision,
                               contract_id=contract_id, market_session=market_session)
        watched = tuple(watched_lives or ())
        if len(watched) > MAX_WATCHED_LIVES:
            return unavailable(reason=f"watched_lives_limit_exceeded:{len(watched)}",
                               cutoff=stamp, history_revision=history_revision,
                               contract_id=contract_id, market_session=market_session)
        if any(not isinstance(life, LifeRef) for life in watched):
            return unavailable(reason="watched_life_invalid", cutoff=stamp,
                               history_revision=history_revision,
                               contract_id=contract_id, market_session=market_session)

        lineage = (contract_id, market_session, history_revision)
        if lineage != self._lineage:
            self._chains = {}                 # retired: never carried across lineage
            self._lineage = lineage

        # Only this contract's lifetime/sweep facts of THIS production session;
        # the durable ledger outlives sessions and is never copied whole.
        relevant = (_SWEEP, _REGISTERED, _REPLACED, _VIOLATED)
        rows = [copy.deepcopy(r) for r in (ledger_rows or ())
                if isinstance(r, dict) and r.get("contract") == contract_id
                and r.get("event_type") in relevant
                and _session_of(r.get("event_time")) == market_session]
        protected = copy.deepcopy(((snapshot or {}).get("protected_swings") or {})
                                  .get("by_timeframe") or {})
        bars = [copy.deepcopy(r) for r in (settled_1m or ())]

        lives = []
        for row in life_inventory(ledger_rows=rows, protected_by_timeframe=protected,
                                  contract_id=contract_id,
                                  market_session=market_session, cutoff=stamp):
            life = life_ref(row)
            certificate = apply_tracker_witness(
                observe_life(life, settled_1m=bars, history_revision=history_revision,
                             contract_id=contract_id, cutoff=stamp),
                row.get("terminal_event"))
            verdict = selection_eligibility(row, certificate,
                                            protected_by_timeframe=protected,
                                            ledger_rows=rows, cutoff=stamp)
            lives.append({**row, "certificate": certificate,
                          "eligible_for_new_selection": verdict["eligible"],
                          "eligibility_failures": verdict["failures"]})

        observed, kept = [], {}
        for life in watched:
            key = life.identity()
            refusal = _watch_refusal(life, contract_id=contract_id,
                                     market_session=market_session, cutoff=stamp,
                                     rows=rows)
            if refusal is not None:
                # never measured, never retained, never another life's facts
                certificate = _refused_certificate(life, refusal, history_revision, stamp)
            else:
                certificate = apply_tracker_witness(
                    observe_life(life, settled_1m=bars, history_revision=history_revision,
                                 contract_id=contract_id, cutoff=stamp,
                                 retained=self._chains.get(key)),
                    _terminal_event(rows, life, stamp))
                kept[key] = copy.deepcopy(certificate)
            observed.append({**life.as_dict(),
                             "tracker_slot_present": _slot_holds(protected, life),
                             "terminal_event": _terminal_event(rows, life, stamp),
                             "certificate": certificate})
        self._chains = kept                   # only explicitly watched lives

        return copy.deepcopy({
            "schema": SCHEMA, "authority": AUTHORITY, "status": AVAILABLE,
            "reason": None, "cutoff": stamp, "history_revision": history_revision,
            "contract_id": contract_id, "market_session": market_session,
            "lives": lives, "watched_lives": observed,
            "retained_chains": len(self._chains),
        })
