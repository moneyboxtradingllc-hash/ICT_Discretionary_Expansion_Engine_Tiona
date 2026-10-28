"""LOCAL-AUTHORITY-20261026 -- explicit, versioned, DISABLED-BY-DEFAULT local proofs.

A participation-policy expansion, not a telemetry repair. Every route here can
admit a candidate the accepted source (ec8197e) refuses, so none of it runs
unless a ProductionScanCycle is constructed with the exact offline profile
object below. A normal launch, a legacy config, an absent/unknown profile, a
copied profile string or a saved authority JSON all resolve to DISABLED, and a
disabled cycle publishes nothing new: its snapshots are the accepted ones.

THE PRODUCER OWNS EVERY FACT. Each witness is derived before cognition from the
current process's canonical settled 1m prefix, its current-revision chronology
rows and the current premise inventory, then sealed into the existing
campaign-scope publication (`campaign_scope._PUBLICATIONS`, whose fact seal
covers `active_path_state`). Consumers resolve it again through that same
publication and this cycle's private issue record. A deep copy, a serialized
snapshot, a bare digest or another process's identical market facts cannot
mint or renew it.

MISSION 1 -- constituent member order (same-direction successor only).
    A native parent raid bucket may open before a 1m local failure while its
    complete settled 1m members prove the first strict crossing of the swept
    reference happened AFTER that failure settled (Friday 11:40 5m bucket,
    failure 11:43, first crossing 11:44). The witness proves that order; the
    native ids, bucket times and every other successor requirement are kept.
    A crossing that shares the failure minute (12:23) stays unproved: no
    intraminute order is invented. Scoped D3's native R is never touched.

MISSION 2 -- two UNBOUND-only local bases (explicit participation expansion).
    Retained support: a native generation that genuinely follows the failure
    it recovers from (source order, or the current witness above) and rests on
    nothing may revalidate an exact still-INTACT raid-associated life as its
    support -- no registration replayed, no ladder credit, withdrawn the cutoff
    its graph no longer holds. Delivery change: an earlier rejected raid and
    its still-INTACT associated 5m/15m life, a settled body-open break and an
    independent settled structure break, completed only after the released
    incumbent's specific failure settled, adopt the composite
    DELIVERY_CHANGE_CONFIRMED generation (never a fictitious raid). Both are
    revalidated on every continuing cutoff, never adopted or kept beside a
    bound/pending campaign, and excluded from scoped D3-B at its own consumer.

MISSION 3 -- consumers. Conditional plans bind the route's stable identity
    (market proof ids, owner lineage, process, contract, session, revision);
    the brainless trigger and the final quote resolve it again on the current
    authenticated snapshot. v2 decision records name the route, proof, current
    source and first refusal.

NOTHING HERE IS AN ENTRY. A verified local proof only lets the existing
narrative-continuity tables consider a direction; the Brain, Draw, Lifecycle,
exact tool, CandidateProducer, risk and execution gates are all unchanged.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

SCHEMA = "local_authority/v1"
MEMBER_ORDER_SCHEMA = "member_order_witness/v1"
FACT_ORDER_ESTABLISHED = "FACT_ORDER_ESTABLISHED"
NOT_ESTABLISHED = "NOT_ESTABLISHED"
#: The only family whose origin order this witness may refine.
NATIVE_RAID_FAMILY = "rejected_raid_reclaim"

_TF_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15}
_DIRECTIONS = ("bullish", "bearish")
_TRUTHY = frozenset(("1", "true", "yes", "on"))
#: An offline profile never runs beside an armed/permitted execution
#: environment. These are the existing execution switches; none is changed.
_EXECUTION_SWITCHES = ("EXECUTION_ENABLED", "ALLOW_PAPER_ORDERS",
                       "AUTO_EXECUTION_ENABLED", "TOPSTEPX_ARM_ORDERS")


@dataclass(frozen=True)
class LocalAuthorityProfile:
    """Which local refinements a cycle may produce. Identity is the object."""

    version: str
    member_order_witness: bool
    retained_support: bool
    delivery_change: bool


#: The accepted participation policy: nothing in this module runs.
DISABLED = LocalAuthorityProfile("disabled", False, False, False)
#: The explicit offline engineering/test profile. Activation for any operator
#: session is reserved to Maurice/Codex review; nothing references this object
#: outside tests.
OFFLINE_TEST_PROFILE_V1 = LocalAuthorityProfile(
    "local_authority_offline_test/v1", True, True, True)
#: The same offline profile without the delivery-change family, so the
#: retained-support case is observable on a tape where an adopted
#: delivery-change generation would otherwise change the later native path.
OFFLINE_RETAINED_SUPPORT_TEST_PROFILE_V1 = LocalAuthorityProfile(
    "local_authority_offline_retained_support_test/v1", True, True, False)
#: Mission 1's witness alone, so its own chronology stays observable after
#: 12:24 ET (where the full profile's delivery change supersedes the forming
#: bullish hypothesis the same-minute case belongs to).
OFFLINE_MEMBER_ORDER_TEST_PROFILE_V1 = LocalAuthorityProfile(
    "local_authority_offline_member_order_test/v1", True, False, False)
_OFFLINE_PROFILES = (OFFLINE_TEST_PROFILE_V1, OFFLINE_RETAINED_SUPPORT_TEST_PROFILE_V1,
                     OFFLINE_MEMBER_ORDER_TEST_PROFILE_V1)
#: The production-capable profile: the same three reviewed cases, the same
#: proof functions, no other law. Unlike the offline objects it may run beside
#: truthy execution switches; whether an armed session may run at all is still
#: decided only by the durable SessionAuthorization and the source fingerprint.
PRODUCTION_PROFILE_V1 = LocalAuthorityProfile(
    "local_authority_production/v1", True, True, True)
_PRODUCTION_PROFILES = (PRODUCTION_PROFILE_V1,)

#: THE compiled release selection, read by the production launcher. None is
#: OFF: the legacy DISABLED participation. It lives in this closure-bound file
#: so a reviewed change to it rotates the Brain contract fingerprint (and with
#: it every prior session authorization); no env, CLI, JSON or account record
#: can select a profile. Activation is reserved to the owner -- do not edit.
RELEASE_SELECTION = PRODUCTION_PROFILE_V1
RELEASE_SELECTION_SOURCE = "src/market_data/local_authority.py:RELEASE_SELECTION"


class ProfileSelectionRefused(ValueError):
    """An explicit selection that cannot run; never a silent legacy fallback."""


def resolve_profile(value):
    """(profile, reason). Only an exact known object enables anything."""
    if value is None:
        return DISABLED, "default_disabled"
    if any(value is profile for profile in _PRODUCTION_PROFILES):
        return value, None
    if not any(value is profile for profile in _OFFLINE_PROFILES):
        return DISABLED, "unrecognized_profile_disabled"
    armed = [name for name in _EXECUTION_SWITCHES
             if str(os.environ.get(name, "")).strip().lower() in _TRUTHY]
    if armed:
        return DISABLED, "offline_profile_refused_execution_environment"
    return value, None


def release_selection():
    """Resolve the compiled RELEASE_SELECTION; raise rather than fall back.

    None is the legitimate legacy OFF. Anything else must be the exact
    production object, or the launch is refused before any provider is used.
    """
    requested = RELEASE_SELECTION
    if requested is None:
        return {"requested": None, "profile": None, "resolved": DISABLED.version,
                "cases": [], "reason": "release_selection_off",
                "source": RELEASE_SELECTION_SOURCE}
    if not any(requested is profile for profile in _PRODUCTION_PROFILES):
        known = any(requested is profile for profile in _OFFLINE_PROFILES)
        raise ProfileSelectionRefused(
            "offline_profile_not_releasable" if known else "unknown_release_selection")
    profile, reason = resolve_profile(requested)
    if profile is not requested:
        raise ProfileSelectionRefused(reason or "release_selection_refused")
    return {"requested": requested.version, "profile": profile, "resolved": profile.version,
            "cases": profile_cases(profile), "reason": None,
            "source": RELEASE_SELECTION_SOURCE}


def profile_cases(profile):
    return [name for name in ("member_order_witness", "retained_support", "delivery_change")
            if getattr(profile, name)]


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     default=str).encode("utf-8")).hexdigest()


def _instant(value):
    if value is None or value == "":
        return None
    try:
        from market_data.object_identity import canonical_instant
        return canonical_instant(value, strict=True)
    except Exception:  # noqa: BLE001 -- ambiguous time is not evidence
        return None


def _dt(value):
    stamp = _instant(value)
    return datetime.fromisoformat(stamp) if stamp else None


def _finite(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _session_of(value):
    try:
        from market_state.active_path import production_session_key
        return production_session_key(value)
    except Exception:  # noqa: BLE001
        return None


def failure_available_at(failure):
    """When a local failure became knowable: the CLOSE of its settled source bucket.

    One clock domain with the body/structure completion edges (source + tf).
    Native clocks (snapshot_builder.settled_source_provenance): source_bar_time
    is the bucket OPEN; settled_edge_time is the OPEN of its terminal 1m
    constituent (None on 1m), so it is never itself a close. It is only checked
    to name a constituent minute of that bucket; an inconsistent or unreadable
    edge proves nothing (None). The native fields are not rewritten.
    """
    if not isinstance(failure, dict):
        return None
    source = _dt(failure.get("source_bar_time"))
    minutes = _TF_MINUTES.get(failure.get("source_tf"))
    if source is None or not minutes:
        return None
    close = source + timedelta(minutes=minutes)
    raw_edge = failure.get("settled_edge_time")
    if raw_edge not in (None, ""):
        edge = _dt(raw_edge)
        if (edge is None or not source <= edge < close
                or (edge - source) % timedelta(minutes=1)):
            return None
    return close


# ── Mission 1: constituent member-order witness ─────────────────────────────
def member_order_witness(*, path, ledger_rows, settled_1m, cutoff, contract_id,
                         market_session, history_revision):
    """Typed witness for the CURRENT origin/failure pair, or None when inapplicable.

    Applicable only to a native rejected-raid origin on a multi-minute bucket
    following a same-direction local failure; otherwise the native comparison
    already states the exact order. Returns NOT_ESTABLISHED (never authority)
    whenever any relation is missing, ambiguous, revised or unsettled.
    """
    path = path if isinstance(path, dict) else {}
    origin = path.get("origin") if isinstance(path.get("origin"), dict) else None
    failure = (path.get("last_invalidated")
               if isinstance(path.get("last_invalidated"), dict) else None)
    if (path.get("state_available") is not True or origin is None or failure is None
            or origin.get("proof_family") != NATIVE_RAID_FAMILY
            or origin.get("direction") not in _DIRECTIONS
            or failure.get("owner") != origin.get("direction")):
        return None
    minutes = _TF_MINUTES.get(origin.get("source_tf"))
    if not minutes or minutes == 1:
        return None
    direction = origin["direction"]
    stamp = _instant(cutoff)
    start = _dt(origin.get("source_bar_time"))
    available = failure_available_at(failure)
    base = {
        "schema": MEMBER_ORDER_SCHEMA, "authority": "LOCAL_PROFILE_ONLY",
        "contract_id": contract_id, "market_session": market_session,
        "history_revision": history_revision, "cutoff": stamp,
        "direction": direction,
        "origin_occurrence_id": origin.get("occurrence_id"),
        "native_source_bar_time": origin.get("source_bar_time"),
        "native_source_tf": origin.get("source_tf"),
        "failure_occurrence_id": failure.get("occurrence_id"),
        "failure_source_bar_time": failure.get("source_bar_time"),
        "failure_source_tf": failure.get("source_tf"),
        "failure_available_at": available.isoformat() if available else None,
    }

    def result(status, reason, **facts):
        out = {**base, "status": status, "reason": reason, **facts}
        out["witness_id"] = "mow:" + digest(out)
        return out

    if (stamp is None or start is None or available is None
            or not contract_id or not market_session
            or isinstance(history_revision, bool) or not isinstance(history_revision, int)
            or not origin.get("occurrence_id") or not failure.get("occurrence_id")
            or str(path.get("contract_id") or "") != contract_id
            or path.get("session") != market_session):
        return result(NOT_ESTABLISHED, "witness_context_incomplete")
    edge = datetime.fromisoformat(stamp) + timedelta(minutes=1)
    end = start + timedelta(minutes=minutes)
    if end > edge:
        return result(NOT_ESTABLISHED, "parent_bucket_not_settled")
    if available > edge:
        return result(NOT_ESTABLISHED, "failure_not_settled")
    side = "below_low" if direction == "bullish" else "above_high"
    from market_data import campaign_premise as CP
    parents = [r for r in (ledger_rows or ()) if isinstance(r, dict)
               and r.get("contract") == contract_id
               and CP._canonical_sweep(r, contract_id) and CP._available(r, stamp)
               and r.get("source_tf") == origin.get("source_tf")
               and _instant(r.get("event_time")) == start.isoformat()
               and r.get("sweep_direction") == side and r.get("reclaimed") is True]
    ids = {r.get("occurrence_id") for r in parents}
    payloads = {json.dumps(r, sort_keys=True, default=str) for r in parents}
    if len(ids) != 1 or len(payloads) != 1:
        return result(NOT_ESTABLISHED, "canonical_parent_raid_missing_or_ambiguous")
    parent = parents[0]
    level = _finite(parent.get("swept_level"))
    if level is None:
        return result(NOT_ESTABLISHED, "raid_reference_missing")
    expected = [(start + timedelta(minutes=i)).isoformat() for i in range(minutes)]
    members, seen = [], set()
    for bar in settled_1m or ():
        if not isinstance(bar, dict):
            return result(NOT_ESTABLISHED, "member_unreadable")
        at = _instant(bar.get("timestamp"))
        if at is None:
            return result(NOT_ESTABLISHED, "member_unreadable")
        if at in seen:
            return result(NOT_ESTABLISHED, "member_duplicate")
        seen.add(at)
        if at in expected:
            if bar.get("contract") not in (None, contract_id):
                return result(NOT_ESTABLISHED, "member_foreign_contract")
            members.append(bar)
    if [_instant(b.get("timestamp")) for b in members] != expected:
        return result(NOT_ESTABLISHED, "parent_members_incomplete_or_unordered")
    rows = []
    for bar in members:
        prices = [_finite(bar.get(k)) for k in ("open", "high", "low", "close")]
        if None in prices or not (prices[2] <= min(prices[0], prices[3])
                                  and prices[1] >= max(prices[0], prices[3])):
            return result(NOT_ESTABLISHED, "member_prices_invalid")
        rows.append({"timestamp": _instant(bar.get("timestamp")), "open": prices[0],
                     "high": prices[1], "low": prices[2], "close": prices[3]})
    crossed = [r for r in rows if (r["low"] < level if direction == "bullish"
                                   else r["high"] > level)]
    facts = {"canonical_parent_raid_id": parent.get("occurrence_id"),
             "swept_level": level, "parent_available_at": end.isoformat(),
             "member_digest": digest(rows)}
    if not crossed:
        return result(NOT_ESTABLISHED, "no_member_crosses_raid_reference", **facts)
    first = crossed[0]
    facts["first_crossing"] = first
    crossing = datetime.fromisoformat(first["timestamp"])
    if crossing < available:
        return result(NOT_ESTABLISHED, "first_crossing_not_after_settled_failure", **facts)
    if (first["open"] < level if direction == "bullish" else first["open"] > level):
        return result(NOT_ESTABLISHED, "first_member_opens_beyond_reference", **facts)
    return result(FACT_ORDER_ESTABLISHED,
                  "settled_member_proves_post_failure_crossing_despite_parent_bucket",
                  available_at=max(end, crossing + timedelta(minutes=1)).isoformat(),
                  **facts)




# ── Mission 2: settled delivery change (body-open break) ────────────────────
#: Typed fact definition carried over from the existing shadow proposal
#: (cisd_shadow.py): over SETTLED own-timeframe buckets, the maximal contiguous
#: opposite-delivery body run ending at/before the bucket that printed the
#: selected extreme; a doji ends the run; the FIRST later settled close
#: strictly through the run's first open confirms it. Equal close, wick-only
#: breach, a forming/partial bucket, a gap or a newer extreme before the break
#: confirm nothing. A versioned fact contract, not ratified trading policy.
BODY_BREAK_SCHEMA = "settled_body_open_break/v1"
DELIVERY_CHANGE_SCHEMA = "delivery_change_packet/v1"
DELIVERY_CHANGE_FAMILY = "raid_reclaim_delivery_change"
DELIVERY_CHANGE_EVENT = "delivery_change_confirmed"
RETAINED_SUPPORT_SCHEMA = "retained_support_revalidation/v1"
#: Families and support bases that are LOCAL ONLY: excluded from scoped D3-B.
LOCAL_ONLY_FAMILIES = frozenset({DELIVERY_CHANGE_FAMILY})
LOCAL_ONLY_SCOPE_REASON = "local_only_authority_excluded_from_scoped_d3_b"
CAMPAIGN_TIMEFRAMES = ("5m", "15m")
_OPPOSITE = {"bullish": "bearish", "bearish": "bullish"}


def settled_buckets(bars_1m, minutes, settled_through):
    """Complete, settled own-timeframe buckets; None when the tape is unreadable."""
    edge = _dt(settled_through)
    if edge is None or not isinstance(minutes, int) or minutes < 1 or 60 % minutes:
        return None
    rows = {}
    for bar in bars_1m or ():
        if not isinstance(bar, dict):
            return None
        stamp = _dt(bar.get("timestamp"))
        prices = [_finite(bar.get(k)) for k in ("open", "high", "low", "close")]
        if stamp is None or None in prices or stamp.second or stamp.microsecond:
            return None
        if stamp in rows:
            return None
        o, h, l, c = prices
        if not (l <= min(o, c) and h >= max(o, c)):
            return None
        rows[stamp] = (o, h, l, c)
    out = []
    starts = sorted({s - timedelta(minutes=s.minute % minutes) for s in rows})
    for start in starts:
        if start + timedelta(minutes=minutes) > edge:
            continue
        parts = [rows.get(start + timedelta(minutes=i)) for i in range(minutes)]
        if None in parts:
            continue
        out.append({"open_time": start.isoformat(), "open": parts[0][0],
                    "high": max(p[1] for p in parts), "low": min(p[2] for p in parts),
                    "close": parts[-1][3],
                    "available_at": (start + timedelta(minutes=minutes)).isoformat()})
    return out


def _delivery(bucket):
    if bucket["close"] > bucket["open"]:
        return "bullish"
    if bucket["close"] < bucket["open"]:
        return "bearish"
    return "doji"


def body_open_break(bars_1m, *, minutes, direction, extreme_at, settled_through, contract):
    """The settled body-open break for one selected extreme, or a typed non-event."""
    base = {"schema": BODY_BREAK_SCHEMA, "contract": contract,
            "timeframe": f"{minutes}m", "direction": direction}
    if direction not in _DIRECTIONS or not contract:
        return {**base, "status": "UNAVAILABLE", "reason": "invalid_request"}
    buckets = settled_buckets(bars_1m, minutes, settled_through)
    target = _dt(extreme_at)
    if buckets is None or target is None:
        return {**base, "status": "UNAVAILABLE", "reason": "tape_unreadable"}
    index = {b["open_time"]: i for i, b in enumerate(buckets)}
    at = index.get(target.isoformat())
    if at is None:
        return {**base, "status": "UNAVAILABLE", "reason": "extreme_bucket_not_settled"}
    prior = _OPPOSITE[direction]
    key = "high" if direction == "bearish" else "low"
    extreme = buckets[at][key]
    last = at
    while last >= 0 and _delivery(buckets[last]) != prior:
        last -= 1
    if last < 0:
        return {**base, "status": "UNAVAILABLE", "reason": "no_prior_delivery_run"}
    step = timedelta(minutes=minutes)
    for earlier, later in zip(buckets[last:at], buckets[last + 1:at + 1]):
        if _dt(later["open_time"]) - _dt(earlier["open_time"]) != step:
            return {**base, "status": "UNAVAILABLE", "reason": "tape_gap",
                    "gap_after": earlier["open_time"]}
    first = last
    while first - 1 >= 0 and _delivery(buckets[first - 1]) == prior:
        if _dt(buckets[first]["open_time"]) - _dt(buckets[first - 1]["open_time"]) != step:
            break
        first -= 1
    # The run's FIRST open is the anchor, so its start must be proved: the
    # bucket before it must be settled, contiguous and of another delivery. A
    # gap or the window's edge leaves the true first open unknown.
    if first == 0:
        return {**base, "status": "UNAVAILABLE", "reason": "run_start_not_covered"}
    if _dt(buckets[first]["open_time"]) - _dt(buckets[first - 1]["open_time"]) != step:
        return {**base, "status": "UNAVAILABLE", "reason": "tape_gap",
                "gap_after": buckets[first - 1]["open_time"]}
    anchor = buckets[first]["open"]
    side = max if direction == "bearish" else min
    if side(b[key] for b in buckets[first:at + 1]) != extreme:
        return {**base, "status": "UNAVAILABLE", "reason": "extreme_not_maximal"}
    run = {"first_open_time": buckets[first]["open_time"],
           "last_open_time": buckets[last]["open_time"],
           "buckets": last - first + 1, "anchor_open": anchor,
           "extreme": extreme, "extreme_open_time": buckets[at]["open_time"]}
    for previous, bucket in zip(buckets[last:], buckets[last + 1:]):
        if _dt(bucket["open_time"]) - _dt(previous["open_time"]) != step:
            return {**base, "status": "UNAVAILABLE", "run": run, "reason": "tape_gap",
                    "gap_after": previous["open_time"]}
        close = bucket["close"]
        if close < anchor if direction == "bearish" else close > anchor:
            event = {"break_open_time": bucket["open_time"], "break_close": close,
                     "available_at": bucket["available_at"]}
            ident = ":".join(["BODY_OPEN_BREAK", contract, f"{minutes}m", direction,
                              run["first_open_time"], repr(anchor), bucket["open_time"]])
            return {**base, "status": "CONFIRMED", "run": run, "event": event,
                    "occurrence_id": ident}
        beyond = bucket["high"] > extreme if direction == "bearish" else bucket["low"] < extreme
        if beyond and _dt(bucket["open_time"]) > target:
            return {**base, "status": "SUPERSEDED", "run": run,
                    "reason": "new_extreme_before_break",
                    "superseded_at": bucket["available_at"]}
    return {**base, "status": "PENDING", "run": run, "reason": "no_settled_break"}


def _failure_identity(failure):
    keys = ("owner", "occurrence_id", "source_tf", "source_bar_time", "swing_id",
            "registered_at", "level", "side")
    if (not isinstance(failure, dict) or failure.get("owner") not in _DIRECTIONS
            or failure.get("source_tf") not in _TF_MINUTES
            or _finite(failure.get("level")) is None
            or any(not failure.get(k) for k in keys if k != "level")):
        return None
    available = failure_available_at(failure)
    if available is None:
        return None
    return {**{k: failure.get(k) for k in keys}, "available_at": available.isoformat()}


def _life_record(life):
    keys = ("contract_id", "market_session", "source_tf", "side", "swing_id",
            "registered_at", "level", "basis", "registration_occurrence_id",
            "registration_bucket_open")
    return {k: life.get(k) for k in keys}


def _current_life(life, *, facts, contract_id, market_session, side, timeframes=None):
    cert = life.get("certificate") if isinstance(life.get("certificate"), dict) else {}
    return bool(isinstance(life, dict)
                and life.get("contract_id") == contract_id
                and life.get("market_session") == market_session
                and life.get("side") == side
                and (timeframes is None or life.get("source_tf") in timeframes)
                and life.get("eligible_for_new_selection") is True
                and cert.get("status") == "INTACT"
                and isinstance(cert.get("covered_buckets"), int)
                and cert.get("covered_buckets", 0) >= 1
                and life.get("registration_occurrence_id")
                and life.get("registration_bucket_open"))


def _facts_current(facts, *, cutoff, contract_id, market_session, history_revision):
    return bool(isinstance(facts, dict) and facts.get("status") == "AVAILABLE"
                and facts.get("cutoff") == cutoff
                and facts.get("history_revision") == history_revision
                and facts.get("contract_id") == contract_id
                and facts.get("market_session") == market_session)


def _canonical_rows(ledger_rows, contract_id, cutoff):
    from market_data import campaign_premise as CP
    return {r["occurrence_id"]: r for r in (ledger_rows or ())
            if isinstance(r, dict) and r.get("occurrence_id")
            and r.get("contract") == contract_id
            and CP._canonical_sweep(r, contract_id) and CP._available(r, cutoff)
            and not CP._association_withheld(r, cutoff)}


def _raid_row(row, *, life, sweep_side):
    level = _finite(row.get("swept_level"))
    association = row.get("protected_swing_lifetime") or {}
    return bool(row.get("sweep_direction") == sweep_side and row.get("reclaimed") is True
                and row.get("source_tf") == life.get("source_tf")
                and level is not None and level == _finite(life.get("level"))
                and association.get("swing_id") == life.get("swing_id")
                and _instant(association.get("registered_at")) == life.get("registered_at")
                and _instant(row.get("event_time")) in [
                    _instant(b) for b in (row.get("source_bars") or [])])


def _structure_event(ledger_rows, *, contract_id, timeframe, direction, not_before, edge, cutoff):
    from market_data import campaign_premise as CP
    minutes = _TF_MINUTES[timeframe]
    found = []
    for row in ledger_rows or ():
        if not (isinstance(row, dict) and row.get("event_type") == "STRUCTURE_BREAK"
                and row.get("contract") == contract_id and row.get("source_tf") == timeframe
                and row.get("direction") == direction and CP._available(row, cutoff)):
            continue
        source = _dt(row.get("source_bar_time"))
        if (source is None or source < not_before
                or source + timedelta(minutes=minutes) > edge
                or _finite(row.get("broken_level")) is None or not row.get("occurrence_id")):
            continue
        found.append((source, str(row["occurrence_id"]), row))
    if not found:
        return None
    source, _, row = min(found, key=lambda x: (x[0], x[1]))
    return {"occurrence_id": row["occurrence_id"], "source_tf": timeframe,
            "direction": direction, "source_bar_time": source.isoformat(),
            "observed_at": _instant(row.get("observed_at") or row.get("event_time")),
            "event_time": _instant(row.get("event_time")),
            "broken_level": _finite(row.get("broken_level")),
            "available_at": (source + timedelta(minutes=minutes)).isoformat()}


def market_proof_id(packet):
    """Which market facts are claimed: stable identities only, never currency."""
    stable = {k: packet.get(k) for k in
              ("family", "direction", "contract_id", "market_session", "history_revision",
               "failure", "earlier_raid", "life", "body_confirmation", "structure")}
    return "ldc:" + digest(stable)


def delivery_change_packet(*, path, facts, ledger_rows, settled_1m, cutoff, contract_id,
                           market_session, history_revision, cited=None):
    """(packet, None) for one complete, current, source-owned causal graph, else (None, reason).

    earlier rejected raid -> exact still-intact associated protected life ->
    settled body-open break and independent settled structural break -> both
    completed only after the incumbent's specific local failure settled.
    `cited` (a prior packet) restricts revalidation to that exact graph.
    """
    stamp = _instant(cutoff)
    failure = _failure_identity((path or {}).get("last_invalidated"))
    if stamp is None or failure is None:
        return None, "incumbent_failure_unestablished"
    if not _facts_current(facts, cutoff=stamp, contract_id=contract_id,
                          market_session=market_session, history_revision=history_revision):
        return None, "premise_facts_not_current"
    if (path or {}).get("contract_id") != contract_id or path.get("session") != market_session:
        return None, "path_context_mismatch"
    edge = datetime.fromisoformat(stamp) + timedelta(minutes=1)
    failure_at = datetime.fromisoformat(failure["available_at"])
    if failure_at > edge:
        return None, "incumbent_failure_not_settled"
    direction = _OPPOSITE[failure["owner"]]
    side, sweep_side = (("high", "above_high") if direction == "bearish"
                        else ("low", "below_low"))
    rows = _canonical_rows(ledger_rows, contract_id, stamp)
    candidates, reasons = [], []   # (stage reached, reason) per candidate graph
    for life in facts.get("lives") or ():
        if not _current_life(life, facts=facts, contract_id=contract_id,
                             market_session=market_session, side=side,
                             timeframes=CAMPAIGN_TIMEFRAMES):
            continue
        record = _life_record(life)
        if cited and record != cited.get("life"):
            continue
        minutes = _TF_MINUTES[life["source_tf"]]
        for raid_id in life.get("sweep_occurrence_ids") or ():
            row = rows.get(raid_id)
            if row is None or not _raid_row(row, life=life, sweep_side=sweep_side):
                continue
            raid_bucket = _dt(row.get("event_time"))
            raid = {"occurrence_id": raid_id, "source_tf": row.get("source_tf"),
                    "source_bar_time": raid_bucket.isoformat(),
                    "sweep_direction": row.get("sweep_direction"),
                    "swept_level": _finite(row.get("swept_level")),
                    "association_observed_at": _instant(
                        (row.get("protected_swing_lifetime") or {}).get("observed_at"))}
            if cited and raid != cited.get("earlier_raid"):
                continue
            prefix = [b for b in settled_1m or () if _dt(b.get("timestamp"))
                      and _dt(b.get("timestamp")) <= datetime.fromisoformat(stamp)]
            body = body_open_break(prefix, minutes=minutes, direction=direction,
                                   extreme_at=raid_bucket.isoformat(),
                                   settled_through=edge.isoformat(), contract=contract_id)
            if body.get("status") != "CONFIRMED":
                reasons.append((1, f"body_open_break_{str(body.get('status')).lower()}:"
                                   f"{body.get('reason')}"))
                continue
            event = body["event"]
            broke = _dt(event["break_open_time"])
            if broke <= raid_bucket:
                reasons.append((2, "body_break_not_after_raid"))
                continue
            structure = _structure_event(ledger_rows, contract_id=contract_id,
                                         timeframe=life["source_tf"], direction=direction,
                                         not_before=broke, edge=edge, cutoff=stamp)
            if structure is None:
                reasons.append((3, "no_settled_structural_break"))
                continue
            completed = max(_dt(event["available_at"]), _dt(structure["available_at"]))
            if not failure_at < completed:
                reasons.append((4, "confirmation_not_after_settled_failure"))
                continue
            packet = {
                "schema": DELIVERY_CHANGE_SCHEMA, "family": DELIVERY_CHANGE_FAMILY,
                "event": DELIVERY_CHANGE_EVENT, "direction": direction,
                "contract_id": contract_id, "market_session": market_session,
                "history_revision": history_revision, "failure": failure,
                "earlier_raid": raid, "life": record,
                "body_confirmation": {"occurrence_id": body["occurrence_id"],
                                      "timeframe": body["timeframe"], "run": body["run"],
                                      **event},
                "structure": structure, "completed_at": completed.isoformat()}
            if cited and any(packet[k] != cited.get(k) for k in
                             ("failure", "body_confirmation", "structure", "completed_at")):
                reasons.append((5, "cited_graph_changed"))
                continue
            packet["market_proof_id"] = market_proof_id(packet)
            candidates.append(packet)
    if not candidates:
        # Report the candidate graph that got furthest; ties keep source order.
        best = max(reasons, key=lambda r: r[0]) if reasons else None
        return None, (best[1] if best else "no_exact_current_supporting_life_and_raid")
    # Earliest completion; then the LATEST earlier raid (the most recent
    # rejection of that liquidity); then a total order on the life record.
    best = min(candidates, key=lambda p: (
        p["completed_at"],
        -_dt(p["earlier_raid"]["source_bar_time"]).timestamp(),
        json.dumps(p["life"], sort_keys=True)))
    return best, None


def composite_origin(packet, observed_at):
    """The DELIVERY_CHANGE_CONFIRMED origin. Never a fictitious post-failure raid."""
    body = packet["body_confirmation"]
    return {"event_type": "DELIVERY_CHANGE_CONFIRMED", "proof_family": DELIVERY_CHANGE_FAMILY,
            "direction": packet["direction"], "event_time": observed_at,
            "observed_at": observed_at, "source_bar_time": body["break_open_time"],
            "settled_edge_time": packet["completed_at"], "source_tf": body["timeframe"],
            "occurrence_id": ":".join(["DELIVERY_CHANGE_CONFIRMED", packet["contract_id"],
                                       body["timeframe"], body["break_open_time"],
                                       packet["direction"]]),
            "local_proof_id": packet["market_proof_id"],
            "earlier_raid": copy.deepcopy(packet["earlier_raid"]),
            "body_confirmation_id": body["occurrence_id"],
            "structure_id": packet["structure"]["occurrence_id"],
            "failure_id": packet["failure"]["occurrence_id"]}


def adopted_support(life, *, observed_at, cited_raid_id, basis_id):
    """Explicit revalidation of an EXISTING life as the new owner's support.

    No registration is replayed, no life is created and no ladder credit is
    awarded: the life keeps its own registration identity and instant.
    """
    return {"level": _finite(life["level"]), "side": life["side"],
            "timeframe": life["source_tf"], "basis": life["basis"],
            "swing_id": life["swing_id"], "registered_at": life["registered_at"],
            "occurrence_id": life["registration_occurrence_id"],
            "source_bar_time": life["registration_bucket_open"],
            "settled_edge_time": None, "observed_at": observed_at, "at": observed_at,
            "intact": True, "producer_backed": True, "last_move_favourable": False,
            "adoption": {"schema": RETAINED_SUPPORT_SCHEMA,
                         "basis": "retained_support_revalidation",
                         "revalidated_at": observed_at, "cited_raid_id": cited_raid_id,
                         "proof_id": basis_id, "ladder_credit": 0}}


def retained_support_adoption(*, path, facts, ledger_rows, cutoff, contract_id,
                              market_session, history_revision, witness=None, cited=None):
    """(adoption, None) for the legacy family's retained-support case, else (None, reason).

    The incumbent generation genuinely failed; the current native rejected-raid
    origin is post-failure in SOURCE order (or by the current producer's
    established member-order witness); independent later progression exists;
    and the new owner rests on nothing. An exact, still-INTACT, raid-associated
    protected life on the supporting side -- whose birth may precede the
    failure and the ownership -- is then revalidated as that owner's support.
    Only lives the existing premise inventory certifies are citable; the life
    is read, never selected, watched or re-registered.
    """
    stamp = _instant(cutoff)
    path = path if isinstance(path, dict) else {}
    owner = path.get("owner")
    origin = path.get("origin") if isinstance(path.get("origin"), dict) else {}
    failure = _failure_identity(path.get("last_invalidated"))
    if stamp is None or owner not in _DIRECTIONS or failure is None:
        return None, "established_owner_or_failure_missing"
    if (origin.get("proof_family") != NATIVE_RAID_FAMILY or origin.get("direction") != owner
            or origin.get("source_tf") not in _TF_MINUTES or not origin.get("occurrence_id")):
        return None, "native_origin_unavailable"
    if path.get("load_bearing_structure") not in (None, {}) and not cited:
        return None, "owner_already_supported"
    if not _facts_current(facts, cutoff=stamp, contract_id=contract_id,
                          market_session=market_session, history_revision=history_revision):
        return None, "premise_facts_not_current"
    if path.get("contract_id") != contract_id or path.get("session") != market_session:
        return None, "path_context_mismatch"
    origin_source = _dt(origin.get("source_bar_time"))
    failure_at = datetime.fromisoformat(failure["available_at"])
    if origin_source is None:
        return None, "native_origin_unavailable"
    causal = origin_source
    if origin_source < failure_at:
        crossing = _dt(((witness or {}).get("first_crossing") or {}).get("timestamp"))
        if crossing is None or crossing < failure_at:
            return None, "origin_not_post_failure_in_source_order"
        causal = crossing
    latest = ((path.get("progression") or {}).get("latest_supporting_event") or {})
    if (latest.get("direction") != owner or _dt(latest.get("source_bar_time")) is None
            or _dt(latest.get("source_bar_time")) <= causal):
        return None, "no_independent_later_progression"
    flags = path.get("transfer_evidence") or {}
    names = ("opposing_structure_break", "load_bearing_failure",
             "load_bearing_replaced_against_path", "ambiguous_load_bearing_invalidation")
    if path.get("status") != "active" or any(
            not isinstance(flags.get(n), bool) or flags.get(n) for n in names):
        return None, "new_owner_contradiction"
    rows = _canonical_rows(ledger_rows, contract_id, stamp)
    side, sweep_side = (("low", "below_low") if owner == "bullish" else ("high", "above_high"))
    candidates = []
    for life in facts.get("lives") or ():
        if not _current_life(life, facts=facts, contract_id=contract_id,
                             market_session=market_session, side=side):
            continue
        raids = [rows[i] for i in life.get("sweep_occurrence_ids") or ()
                 if i in rows and _raid_row(rows[i], life=life, sweep_side=sweep_side)]
        if cited:   # revalidation keeps citing the same raid while it holds
            raids = [r for r in raids if r["occurrence_id"] == cited.get("cited_raid_id")]
        if not raids:
            continue
        raid = max(raids, key=lambda r: (_instant(r.get("event_time")), r["occurrence_id"]))
        candidates.append((life, raid))
    if cited:
        candidates = [(l, r) for l, r in candidates if _life_record(l) == cited.get("life")]
    if not candidates:
        return None, "no_exact_current_associated_life"
    # The most recently registered certified life, as the native machine
    # rests on its latest registration; equal registration instants are
    # ambiguous and refused rather than ordered by price.
    newest = max(c[0]["registered_at"] for c in candidates)
    chosen = [c for c in candidates if c[0]["registered_at"] == newest]
    if len(chosen) != 1:
        return None, "retained_support_ambiguous"
    life, raid = chosen[0]
    record = _life_record(life)
    basis = {"schema": RETAINED_SUPPORT_SCHEMA, "owner": owner, "failure": failure,
             "origin_occurrence_id": origin.get("occurrence_id"),
             "cited_raid_id": raid["occurrence_id"], "life": record,
             "contract_id": contract_id, "market_session": market_session,
             "history_revision": history_revision}
    basis["adoption_id"] = "rsa:" + digest(basis)
    if cited and basis["adoption_id"] != cited.get("adoption_id"):
        return None, "cited_adoption_changed"
    return basis, None


# ── producer-owned issue record ─────────────────────────────────────────────
class LocalAuthority:
    """One cycle's private issue record. Reads authenticate; they never mint."""

    def __init__(self, profile=None):
        self.profile, self.profile_reason = resolve_profile(profile)
        self.reset("constructed")

    @property
    def enabled(self) -> bool:
        return self.profile is not DISABLED

    def reset(self, reason="reset"):
        self._issued = None
        self._pending = None
        self._cache = None
        #: The exact packet / adoption this cycle adopted; revalidated every cutoff.
        self._generation = None
        self._support = None
        self.last_reset_reason = reason
        self.diagnostics = []

    def revoke(self, reason="revoked"):
        """Withdraw the current issue; every consumer refuses until re-derived."""
        self._issued = None
        self._pending = None
        self._cache = None
        self.diagnostics.append({"revoked": reason})

    def advance(self, *, cycle, snapshot, settled_1m, ledger_rows, contract_id,
                market_session, history_revision):
        """Derive, revalidate and attach this cutoff's local facts BEFORE publication.

        Order: revalidate any adopted generation/support against the current
        settled facts (withdrawing it when the cited graph no longer holds),
        then consider a new adoption, then derive the member-order witness on
        the resulting path. Same-cutoff assembly republishes the first
        derivation exactly, so a retry can neither revise sealed facts nor
        mint a second proof, registration or ladder improvement.
        """
        self._pending = None
        if not self.enabled:
            return
        stamp = _instant(snapshot.get("timestamp"))
        key = (history_revision, contract_id, market_session, stamp)
        if self._cache is not None and self._cache[0] == key:
            snapshot["active_path_state"] = copy.deepcopy(self._cache[1])
            self._pending = copy.deepcopy(self._cache[2])
            return
        self._issued = None
        path = snapshot.get("active_path_state")
        active_path = getattr(cycle, "_active_path", None)
        if (stamp is None or not isinstance(path, dict)
                or path.get("state_available") is not True or active_path is None
                or not cycle.derived_state_is_current()):
            self._cache = (key, copy.deepcopy(path), None)
            return
        facts = snapshot.get("campaign_premise_shadow")
        common = dict(facts=facts, ledger_rows=ledger_rows, cutoff=stamp,
                      contract_id=contract_id, market_session=market_session,
                      history_revision=history_revision)
        issue = {"cutoff": stamp, "history_revision": history_revision,
                 "contract_id": contract_id, "market_session": market_session,
                 "process_session_id": getattr(cycle, "session_id", None),
                 "member_order": None, "delivery_change": None, "retained_support": None}
        events = []
        changed = False
        # UNBOUND-only, enforced at the producer as well as at every consumer:
        # a bound or pending campaign is never cleared, relabelled or shadowed
        # by a local refinement, so none is adopted -- or kept -- beside one.
        custody = getattr(cycle, "campaign_scope_custody", None)
        unbound = bool(custody is not None and getattr(custody, "_campaign", True) is None
                       and getattr(custody, "_pending", True) is None)
        # 0. Forget a citation whose state the native machine already ended
        #    (the adopted leg died, or a native registration replaced the
        #    revalidated support): there is nothing left to revalidate.
        if (self._generation is not None
                and (active_path.origin or {}).get("event_type") != "DELIVERY_CHANGE_CONFIRMED"):
            self._generation = None
            events.append({"kind": "delivery_change_ended_natively"})
        if (self._support is not None
                and not (active_path.load_bearing or {}).get("adoption")):
            self._support = None
            events.append({"kind": "retained_support_ended_natively"})
        # 1. Revalidate what this cycle adopted earlier: incumbency is never
        #    enough, the cited graph must still be current at this cutoff.
        if (active_path.origin or {}).get("event_type") == "DELIVERY_CHANGE_CONFIRMED":
            cited = self._generation
            packet, reason = (delivery_change_packet(path=path, settled_1m=settled_1m,
                                                     cited=cited, **common)
                              if cited and self.profile.delivery_change
                              else (None, "no_cited_generation"))
            if not unbound:
                packet, reason = None, "campaign_scope_not_unbound"
            if packet is None or packet["market_proof_id"] != (cited or {}).get("market_proof_id"):
                active_path.release_local_generation()
                self._generation = None
                changed = True
                events.append({"kind": "delivery_change_withdrawn", "reason": reason})
            else:
                issue["delivery_change"] = packet["market_proof_id"]
        elif (active_path.load_bearing or {}).get("adoption"):
            cited = self._support
            adoption, reason = (retained_support_adoption(
                path=path, witness=self._witness_for(path, settled_1m, common),
                cited=cited, **common) if cited and self.profile.retained_support
                else (None, "no_cited_support"))
            if not unbound:
                adoption, reason = None, "campaign_scope_not_unbound"
            if adoption is None:
                active_path.withdraw_adopted_support()
                self._support = None
                changed = True
                events.append({"kind": "retained_support_withdrawn", "reason": reason})
            else:
                issue["retained_support"] = adoption["adoption_id"]
        withdrawn = bool(events)
        # 2. A new adoption, only from the facts of THIS cutoff.
        if not unbound and not withdrawn:
            events.append({"kind": "local_refinement_not_considered",
                           "reason": "campaign_scope_not_unbound"})
        if (not withdrawn and unbound and self.profile.delivery_change
                and active_path.owner == "none"
                and issue["delivery_change"] is None):
            packet, reason = delivery_change_packet(path=path, settled_1m=settled_1m, **common)
            if packet is not None:
                life = next(l for l in facts.get("lives") or ()
                            if _life_record(l) == packet["life"])
                adopted = active_path.adopt_local_generation(
                    direction=packet["direction"],
                    origin=composite_origin(packet, stamp),
                    load_bearing=adopted_support(
                        life, observed_at=stamp,
                        cited_raid_id=packet["earlier_raid"]["occurrence_id"],
                        basis_id=packet["market_proof_id"]),
                    progression={**packet["structure"], "at": packet["structure"]["event_time"]})
                if adopted:
                    self._generation = copy.deepcopy(packet)
                    issue["delivery_change"] = packet["market_proof_id"]
                    changed = True
                    events.append({"kind": "delivery_change_adopted",
                                   "market_proof_id": packet["market_proof_id"]})
            else:
                events.append({"kind": "delivery_change_absent", "reason": reason})
        if (not withdrawn and unbound and self.profile.retained_support
                and active_path.owner in _DIRECTIONS and active_path.load_bearing is None
                and (active_path.origin or {}).get("event_type") == "LIQUIDITY_SWEEP"):
            adoption, reason = retained_support_adoption(
                path=path, witness=self._witness_for(path, settled_1m, common), **common)
            if adoption is not None:
                life = next(l for l in facts.get("lives") or ()
                            if _life_record(l) == adoption["life"])
                if active_path.adopt_support(adopted_support(
                        life, observed_at=stamp, cited_raid_id=adoption["cited_raid_id"],
                        basis_id=adoption["adoption_id"])):
                    self._support = copy.deepcopy(adoption)
                    issue["retained_support"] = adoption["adoption_id"]
                    changed = True
                    events.append({"kind": "retained_support_adopted",
                                   "adoption_id": adoption["adoption_id"]})
        if changed:
            path = active_path.state(available=True)
            active_path.mark_scan_end()
        # 3. Member order on the path this cutoff actually publishes.
        if self.profile.member_order_witness:
            witness = member_order_witness(
                path=path, ledger_rows=ledger_rows, settled_1m=settled_1m, cutoff=stamp,
                contract_id=contract_id, market_session=market_session,
                history_revision=history_revision)
            if witness is not None:
                path = copy.deepcopy(path)
                path["origin"]["member_order_witness"] = witness
                issue["member_order"] = witness["witness_id"]
        snapshot["active_path_state"] = path
        self.diagnostics = (self.diagnostics + [{"cutoff": stamp, "events": events}])[-8:]
        self._pending = issue
        self._cache = (key, copy.deepcopy(path), copy.deepcopy(issue))

    @staticmethod
    def _witness_for(path, settled_1m, common):
        witness = member_order_witness(
            path=path, ledger_rows=common["ledger_rows"], settled_1m=settled_1m,
            cutoff=common["cutoff"], contract_id=common["contract_id"],
            market_session=common["market_session"],
            history_revision=common["history_revision"])
        return witness if (witness or {}).get("status") == FACT_ORDER_ESTABLISHED else None

    def seal(self, custody):
        """Bind the pending issue to the publication the scope custody just made."""
        pending, self._pending = self._pending, None
        context = getattr(custody, "_context", None) or {}
        if (not self.enabled or pending is None
                or context.get("cutoff") != pending["cutoff"]
                or context.get("history_revision") != pending["history_revision"]
                or context.get("contract_id") != pending["contract_id"]
                or context.get("market_session") != pending["market_session"]
                or context.get("process_session_id") != pending["process_session_id"]):
            self._issued = None
            return
        self._issued = {**pending, "custody_lineage": custody._lineage}


def current_issue(snapshot):
    """(issue, None) for the actual producer's current publication, else (None, reason)."""
    try:
        from market_data import campaign_scope as CS
        custody = CS._read_publication(snapshot)
        if custody is None:
            return None, "local_authority_publication_unavailable"
        publication = CS._PUBLICATIONS.get(custody) or {}
        owner = publication.get("owner")() if publication.get("owner") else None
        authority = getattr(owner, "local_authority", None)
        if not isinstance(authority, LocalAuthority) or not authority.enabled:
            return None, "local_authority_disabled"
        issued = authority._issued
        context = custody._context or {}
        if (not issued or issued.get("custody_lineage") != custody._lineage
                or issued.get("cutoff") != context.get("cutoff")
                or issued.get("history_revision") != context.get("history_revision")
                or issued.get("contract_id") != context.get("contract_id")
                or issued.get("market_session") != context.get("market_session")
                or issued.get("process_session_id") != context.get("process_session_id")):
            return None, "local_authority_issue_not_current"
        return copy.deepcopy(issued), None
    except Exception as exc:  # noqa: BLE001 -- unverifiable authority is absent
        return None, f"local_authority_unverifiable:{type(exc).__name__}"


_UNIDENTIFIED = "unidentified_local_refinement"


def local_refinements(path):
    """Which profile-gated refinements this published path carries.

    Presence is decided by the markers alone, so a path that merely LOOKS
    refined (a copied family label, an adoption block without an id) is still
    a refinement -- and therefore refused unless the current producer issued it.
    """
    path = path if isinstance(path, dict) else {}
    origin = path.get("origin") if isinstance(path.get("origin"), dict) else {}
    bearing = (path.get("load_bearing_structure")
               if isinstance(path.get("load_bearing_structure"), dict) else {})
    change = None
    if ("local_proof_id" in origin or origin.get("proof_family") == DELIVERY_CHANGE_FAMILY
            or origin.get("event") == DELIVERY_CHANGE_EVENT):
        change = origin.get("local_proof_id") or _UNIDENTIFIED
    support = None
    if "adoption" in bearing:
        adoption = bearing.get("adoption") if isinstance(bearing.get("adoption"), dict) else {}
        proof = adoption.get("proof_id") or _UNIDENTIFIED
        # The delivery-change generation's own support is part of THAT proof.
        support = None if (change and proof == change) else proof
    return {"delivery_change": change, "retained_support": support}


def authenticated_local_route(path, snapshot):
    """{} when the path carries no local refinement; the authenticated route
    when the current producer issued every refinement it carries; else None."""
    refinements = local_refinements(path)
    if not any(refinements.values()):
        return {}
    if not isinstance(snapshot, dict) or path != snapshot.get("active_path_state"):
        return None
    issued, _ = current_issue(snapshot)
    if not issued or issued.get("cutoff") != _instant(snapshot.get("timestamp")):
        return None
    if any(value is not None and (value == _UNIDENTIFIED or issued.get(key) != value)
           for key, value in refinements.items()):
        return None
    route = {key: value for key, value in refinements.items() if value is not None}
    route["route"] = "delivery_change" if refinements["delivery_change"] else "retained_support"
    return route


def plan_binding(snapshot, direction):
    """Stable identity of the CURRENT local route a plan relies on, or None.

    None: the snapshot's path carries no local refinement and its generation
    does not depend on a member-order witness (the accepted behaviour).
    Raises ValueError when it does but the current producer does not issue
    it for this exact snapshot. The binding names market facts by stable ids
    (no cutoff) plus the live owner: custody lineage, process, contract,
    session and history revision -- so the same market digest in another
    issuer, process or revision never matches.
    """
    snap = snapshot if isinstance(snapshot, dict) else {}
    path = snap.get("active_path_state") if isinstance(snap.get("active_path_state"), dict) else {}
    refinements = local_refinements(path)
    dependent = member_order_dependent(path, direction)
    if not any(refinements.values()) and not dependent:
        return None
    if authenticated_local_route(path, snap) is None:
        raise ValueError("local_authority_not_current")
    binding = {"schema": SCHEMA, "routes": {k: v for k, v in refinements.items() if v}}
    if dependent:
        witness = authenticated_member_order(path, snap, direction)
        if witness is None:
            raise ValueError("local_authority_not_current")
        binding["member_order_fact"] = "mof:" + digest(
            {k: v for k, v in witness.items() if k not in ("witness_id", "cutoff")})
    issued, reason = current_issue(snap)
    if issued is None:
        raise ValueError(reason or "local_authority_not_current")
    binding.update({k: issued.get(k) for k in ("custody_lineage", "process_session_id",
                                               "contract_id", "market_session",
                                               "history_revision")})
    return binding


ROUTE_EVIDENCE_SCHEMA = "local_authority_route.v1"


def route_evidence(snapshot):
    """Typed evidence of the local route a decision saw; None when there is none.

    Observational only. Missing current-source evidence is UNKNOWN, never
    inferred; nothing here is participation authority.
    """
    try:
        snap = snapshot if isinstance(snapshot, dict) else {}
        path = (snap.get("active_path_state")
                if isinstance(snap.get("active_path_state"), dict) else {})
        origin = path.get("origin") if isinstance(path.get("origin"), dict) else {}
        refinements = local_refinements(path)
        witness = origin.get("member_order_witness")
        if not any(refinements.values()) and not isinstance(witness, dict):
            return None
        routes = []
        if refinements["delivery_change"]:
            routes.append({"route": "delivery_change", "family": origin.get("proof_family"),
                           "proof_id": refinements["delivery_change"]})
        if refinements["retained_support"]:
            routes.append({"route": "retained_support",
                           "proof_id": refinements["retained_support"]})
        if isinstance(witness, dict):
            routes.append({"route": "member_order_witness", "proof_id": witness.get("witness_id"),
                           "status": witness.get("status"), "reason": witness.get("reason")})
        issued, reason = current_issue(snap)
        source = ({"status": "CURRENT_PRODUCER_ISSUE", "reason": None,
                   **{k: issued.get(k) for k in ("cutoff", "history_revision", "contract_id",
                                                 "market_session", "process_session_id")}}
                  if issued else {"status": "UNKNOWN", "reason": reason})
        owner = path.get("owner")
        authenticated = bool(
            issued and authenticated_local_route(path, snap) is not None
            and (not isinstance(witness, dict) or not member_order_dependent(path, owner)
                 or authenticated_member_order(path, snap, owner) is not None))
        return {"schema": ROUTE_EVIDENCE_SCHEMA, "routes": routes, "current_source": source,
                "authenticated": authenticated,
                "note": "evidence only; never participation authority"}
    except Exception as exc:  # noqa: BLE001 -- evidence must never gate a scan
        return {"schema": ROUTE_EVIDENCE_SCHEMA, "routes": None,
                "current_source": {"status": "UNKNOWN",
                                   "reason": f"capture_error:{type(exc).__name__}"},
                "authenticated": None}


def member_order_dependent(path, owner):
    """Does this leg's generation exist only by a member-order witness?

    True when the producer attached a witness (profile-enabled cycles only) to
    a native raid origin whose own bucket does not follow the same-direction
    failure it recovers from. Such a leg stays legitimate only while that
    witness is CURRENT -- incumbency cannot launder an expired proof.
    """
    if not isinstance(path, dict) or owner not in _DIRECTIONS:
        return False
    origin = path.get("origin") if isinstance(path.get("origin"), dict) else {}
    failure = (path.get("last_invalidated")
               if isinstance(path.get("last_invalidated"), dict) else {})
    if ("member_order_witness" not in origin or origin.get("proof_family") != NATIVE_RAID_FAMILY
            or origin.get("direction") != owner or failure.get("owner") != owner):
        return False
    origin_source, failure_source = (_dt(origin.get("source_bar_time")),
                                     _dt(failure.get("source_bar_time")))
    return not (origin_source and failure_source and origin_source > failure_source)


def authenticated_member_order(path, snapshot, direction):
    """The current producer's established witness for THIS origin/failure, else None."""
    if not isinstance(path, dict) or not isinstance(snapshot, dict):
        return None
    origin = path.get("origin") if isinstance(path.get("origin"), dict) else {}
    failure = (path.get("last_invalidated")
               if isinstance(path.get("last_invalidated"), dict) else {})
    witness = origin.get("member_order_witness")
    if not isinstance(witness, dict):
        return None
    issued, _ = current_issue(snapshot)
    if not issued or issued.get("member_order") is None:
        return None
    unsigned = {k: v for k, v in witness.items() if k != "witness_id"}
    stamp = _instant(snapshot.get("timestamp"))
    crossing = (witness.get("first_crossing") or {}).get("timestamp")
    available = _dt(witness.get("failure_available_at"))
    if (witness.get("witness_id") != issued["member_order"]
            or "mow:" + digest(unsigned) != witness.get("witness_id")
            or witness.get("schema") != MEMBER_ORDER_SCHEMA
            or witness.get("status") != FACT_ORDER_ESTABLISHED
            or witness.get("direction") != direction
            or witness.get("cutoff") != stamp or stamp != issued.get("cutoff")
            or witness.get("contract_id") != snapshot.get("contract_id")
            or witness.get("contract_id") != issued.get("contract_id")
            or witness.get("market_session") != issued.get("market_session")
            or witness.get("history_revision") != issued.get("history_revision")
            or witness.get("origin_occurrence_id") != origin.get("occurrence_id")
            or witness.get("native_source_bar_time") != origin.get("source_bar_time")
            or witness.get("native_source_tf") != origin.get("source_tf")
            or witness.get("failure_occurrence_id") != failure.get("occurrence_id")
            or witness.get("failure_source_bar_time") != failure.get("source_bar_time")
            or witness.get("failure_source_tf") != failure.get("source_tf")
            or available is None or failure_available_at(failure) != available
            or _dt(crossing) is None or _dt(crossing) < available):
        return None
    return copy.deepcopy(witness)
