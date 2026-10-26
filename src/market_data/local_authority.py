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


def resolve_profile(value):
    """(profile, reason). Only the exact offline object enables anything."""
    if value is None:
        return DISABLED, "default_disabled"
    if value is not OFFLINE_TEST_PROFILE_V1:
        return DISABLED, "unrecognized_profile_disabled"
    armed = [name for name in _EXECUTION_SWITCHES
             if str(os.environ.get(name, "")).strip().lower() in _TRUTHY]
    if armed:
        return DISABLED, "offline_profile_refused_execution_environment"
    return OFFLINE_TEST_PROFILE_V1, None


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
    """When a local failure became knowable: its settled edge, else its bar's close."""
    if not isinstance(failure, dict):
        return None
    edge = _dt(failure.get("settled_edge_time"))
    if edge is not None:
        return edge
    source = _dt(failure.get("source_bar_time"))
    minutes = _TF_MINUTES.get(failure.get("source_tf"))
    return source + timedelta(minutes=minutes) if source and minutes else None


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
        """Derive and attach this cutoff's local witnesses BEFORE publication.

        Same-cutoff assembly republishes the first derivation exactly, so a
        retry can neither revise sealed facts nor mint a second witness.
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
        if (stamp is None or not isinstance(path, dict)
                or path.get("state_available") is not True
                or not cycle.derived_state_is_current()):
            self._cache = (key, copy.deepcopy(path), None)
            return
        issue = {"cutoff": stamp, "history_revision": history_revision,
                 "contract_id": contract_id, "market_session": market_session,
                 "process_session_id": getattr(cycle, "session_id", None),
                 "member_order": None}
        if self.profile.member_order_witness:
            witness = member_order_witness(
                path=path, ledger_rows=ledger_rows, settled_1m=settled_1m,
                cutoff=stamp, contract_id=contract_id, market_session=market_session,
                history_revision=history_revision)
            if witness is not None:
                path = copy.deepcopy(path)
                path["origin"]["member_order_witness"] = witness
                snapshot["active_path_state"] = path
                issue["member_order"] = witness["witness_id"]
        self._pending = issue
        self._cache = (key, copy.deepcopy(snapshot["active_path_state"]),
                       copy.deepcopy(issue))

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
