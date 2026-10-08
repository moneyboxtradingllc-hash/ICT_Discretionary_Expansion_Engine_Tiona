"""
Phase AB-1 — Brain stance memory (ends the amnesia).

The old wrapper had zero memory of its own prior output: the 10:15 bearish
read on June 11 had vanished by 10:28. This is a cross-scan ring buffer of
the brain's own stances, supplied back into the next scan's input so the
brain can answer "what did I say last scan / when the thesis began / what
changed". AB-4: persisted across restart/replay/session to data/ai_brain/stance_memory.json,
so the brain answers "what was my prior stance?" without relying on the current
process. Never raises.

STAGE-3B-1A (cognitive history hygiene). A persisted stance is cognition, not
market fact. A production custody is BOUND to its cycle's contract and process
session; each row it records carries producer-authored scope (schema version,
contract, market session, settled cutoff, process session and history lineage)
and may supply the incumbent to the next canonical cognition only while that
scope is PROVED against the current snapshot. Every other row stays visible as
labelled `withheld_context` and supplies nothing. An unbound memory (standalone
callers, tests) keeps the legacy behaviour.
"""
import copy
import json
import math
import os
import uuid

from ai_brain.narrative_continuity import (CAMPAIGN_FALSIFIER_STATUS_UNBOUND,
                                           campaign_premise_unbound, leg_evidence)

#: Rows written by a bound production custody. Anything else is legacy.
STANCE_SCHEMA_VERSION = 2

# Why a row was withheld from authority. Checked in this order.
LEGACY_SCHEMA = "legacy_schema"
MALFORMED_SCOPE = "malformed_scope"
SUPERSEDED_HISTORY_REVISION = "superseded_history_revision"
HISTORY_LINEAGE_UNPROVED = "history_lineage_unproved"
SCOPE_MISMATCH = "scope_mismatch"
FUTURE_DATED = "future_dated"
CURRENT_SCOPE_UNPROVED = "current_scope_unproved"

#: How many of the most recently recorded withheld rows are shown as context.
#: The full withheld count and the count per reason are always reported.
WITHHELD_CONTEXT_ROWS = 5

SELECTION_RULE = ("most recent ELIGIBLE row by canonical recorded_at_cutoff; "
                  "ties broken by the custody's recording sequence")


def _stance_path() -> str:
    d = os.getenv("AI_BRAIN_DIR", os.path.join("data", "ai_brain"))
    return os.path.join(d, "stance_memory.json")


class StanceMemory:
    def __init__(self, max_len: int = 30, persist: bool = True):
        self._buf: list = []
        self._max = max_len
        self._thesis_anchor = None   # stance at the start of the current direction run
        self._persist = persist
        # Per-instance custody. Persisted rows from another instance (another
        # process, another cycle) carry another token and never prove lineage.
        self._custody_token = uuid.uuid4().hex
        self._scope = None
        self._sequence = 0
        if persist:
            self._load()

    # ── STAGE-3B-1A custody and scope ────────────────────────────────────────
    @property
    def custody_token(self) -> str:
        return self._custody_token

    def bind_production_scope(self, contract_id, process_session_id) -> None:
        """Bind this custody to the cycle that owns it. Never raises.

        Scope is recorded exactly as supplied; an empty value is recorded as
        missing and such rows are never eligible -- nothing is manufactured.
        """
        try:
            self._scope = {
                "contract_id": str(contract_id or "").strip() or None,
                "process_session_id": str(process_session_id or "").strip() or None,
            }
        except Exception:  # noqa: BLE001
            self._scope = {"contract_id": None, "process_session_id": None}

    @property
    def production_scope(self):
        return dict(self._scope) if self._scope is not None else None

    def _current_scope(self, snapshot) -> dict:
        """The proved scope of the cognition about to read or record."""
        snap = snapshot if isinstance(snapshot, dict) else {}
        scope = self._scope or {}
        cutoff = _settled_instant(snap.get("timestamp"))
        contract = scope.get("contract_id")
        snapshot_contract = str(snap.get("contract_id") or "").strip()
        if snapshot_contract and snapshot_contract != contract:
            contract = None   # the snapshot does not belong to this custody
        derived = snap.get("derived_state")
        revision = (derived.get("history_revision")
                    if isinstance(derived, dict) else None)
        return {
            "recorded_at_cutoff": cutoff,
            "market_session": _session_key(cutoff) if cutoff else None,
            "contract_id": contract,
            "process_session_id": scope.get("process_session_id"),
            "history_revision": revision if _is_int(revision) else None,
        }

    def _withheld_reason(self, row, current) -> "str | None":
        """None when the row is PROVED eligible to supply the incumbent."""
        if not isinstance(row, dict):
            return MALFORMED_SCOPE
        if row.get("stance_schema_version") != STANCE_SCHEMA_VERSION:
            return LEGACY_SCHEMA
        lineage = row.get("history_lineage")
        cutoff = _settled_instant(row.get("recorded_at_cutoff"))
        if (not isinstance(lineage, dict)
                or not isinstance(lineage.get("custody"), str)
                or not lineage.get("custody")
                or not _is_int(lineage.get("history_revision"))
                or not _is_int(lineage.get("sequence"))
                or cutoff is None
                or not all(isinstance(row.get(k), str) and row.get(k)
                           for k in ("contract_id", "market_session",
                                     "process_session_id"))
                or not _consumed_fields_well_formed(row, cutoff)):
            return MALFORMED_SCOPE
        if row.get("superseded_by_history_revision") is not None:
            return SUPERSEDED_HISTORY_REVISION
        if lineage.get("custody") != self._custody_token:
            return HISTORY_LINEAGE_UNPROVED
        if not all(current.get(k) is not None for k in (
                "recorded_at_cutoff", "market_session", "contract_id",
                "process_session_id", "history_revision")):
            return CURRENT_SCOPE_UNPROVED
        if lineage["history_revision"] < current["history_revision"]:
            return SUPERSEDED_HISTORY_REVISION
        if lineage["history_revision"] > current["history_revision"]:
            return MALFORMED_SCOPE
        if (row["contract_id"] != current["contract_id"]
                or row["market_session"] != current["market_session"]
                or row["process_session_id"] != current["process_session_id"]):
            return SCOPE_MISMATCH
        if _session_key(cutoff) != row["market_session"]:
            return MALFORMED_SCOPE
        if _instant_after(cutoff, current["recorded_at_cutoff"]):
            return FUTURE_DATED
        return None

    def _safe_withheld_reason(self, row, current) -> "str | None":
        """One bad row is one withheld row; it never fails the whole read."""
        try:
            return self._withheld_reason(row, current)
        except Exception:  # noqa: BLE001
            return MALFORMED_SCOPE

    def _partition(self, snapshot):
        """(eligible rows in canonical order, withheld [(index, row, reason)])."""
        current = self._current_scope(snapshot)
        eligible, withheld = [], []
        for index, row in enumerate(self._buf):
            reason = self._safe_withheld_reason(row, current)
            if reason is None:
                eligible.append(row)
            else:
                withheld.append((index, row, reason))
        eligible.sort(key=lambda r: (_instant_key(r["recorded_at_cutoff"]),
                                     r["history_lineage"]["sequence"]))
        return eligible, withheld, current

    # ── AB-4 persistence ────────────────────────────────────────────────────
    def _load(self) -> None:
        try:
            path = _stance_path()
            if os.path.exists(path):
                data = json.load(open(path, encoding="utf-8"))
                # STAGE-3B-1A-R1: a parseable but malformed container is kept
                # as ONE retained malformed element -- quarantined like any
                # other bad row, never dropped or reset (the next save writes
                # it back inside a list).
                if not isinstance(data, dict):
                    data = {"buf": [data]}
                buf = data.get("buf", [])
                self._buf = (buf if isinstance(buf, list) else [buf])[-self._max:]
                self._thesis_anchor = data.get("thesis_anchor")
        except Exception:  # noqa: BLE001
            self._buf, self._thesis_anchor = [], None

    def _save(self) -> None:
        if not self._persist:
            return
        try:
            path = _stance_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"buf": self._buf, "thesis_anchor": self._thesis_anchor},
                          fh, default=str)
        except Exception:  # noqa: BLE001
            pass

    def record(self, ts: str, stance: dict, narrative_continuity: dict = None,
               snapshot: dict = None) -> None:
        try:
            continuity = (narrative_continuity
                          if isinstance(narrative_continuity, dict) else {})
            path = continuity.get("active_path") or {}
            direction = str(stance.get("narrative_direction", "neutral")).lower()
            prior = continuity.get("prior_thesis") or {}
            campaign_direction = (continuity.get("dominant_direction")
                                  or prior.get("direction") or direction)
            has_load_bearing = (isinstance(path.get("load_bearing_structure"), dict)
                                and path["load_bearing_structure"].get("level") is not None)
            # STAGE-3B-1B: LOCAL active-leg evidence, recorded under leg names.
            # (A continuity built before 3B-1B carried the same leg values under
            # the campaign-falsifier names; they are read here as leg evidence.)
            continuity_leg_status = (
                continuity.get("active_leg_failure_status")
                if "active_leg_failure_status" in continuity
                else continuity.get("thesis_falsifier_status"))
            leg_failure_status = (
                continuity.get("active_leg_failure_status")
                if "active_leg_failure_status" in continuity
                else (continuity.get("current_thesis_falsifier_status")
                      or continuity.get("thesis_falsifier_status")))
            if continuity.get("control_state") == "confirmed_transfer":
                # The continuity status above describes the PREVIOUS owner's
                # leg. A newly confirmed owner starts with its own active
                # load-bearing structure and its own leg not yet failed.
                leg_failure_status = "not_occurred"
            campaign_established = bool(
                path.get("available") is True
                and path.get("owner") == campaign_direction
                and path.get("status") in ("active", "contested")
                and has_load_bearing)
            # Unchanged carry rule, now read from the equivalent LEG status. The
            # campaign premise is UNKNOWN and is deliberately not consulted.
            if (not campaign_established and prior.get("campaign_established") is True
                    and continuity_leg_status != "occurred"):
                campaign_established = True
            entry = {
                "timestamp":  ts,
                "direction":  direction,
                "phase":      stance.get("narrative_phase", "transition"),
                "confidence": stance.get("phase_confidence", 0),
                "action":     stance.get("current_action", "stand_down"),
                # NARRATIVE-AUTHORITY-1: persist the causal campaign state the
                # Brain actually received. Old records remain readable but are
                # not treated as authoritative campaign anchors.
                "narrative_state_version": 1,
                "campaign_direction": campaign_direction,
                "campaign_established": campaign_established,
                "market_story": str(stance.get("market_story") or "")[:1200],
                "dominant_reasoning": str(stance.get("dominant_reasoning") or "")[:1200],
                "invalidation_level": stance.get("invalidation_level"),
                # STAGE-3B-1B: local leg evidence (formerly stored under the
                # campaign-falsifier names) ...
                "active_leg_structure": (
                    leg_evidence(continuity, "active_leg_structure",
                                 "current_thesis_falsifier")
                    or leg_evidence(prior, "active_leg_structure", "thesis_falsifier")
                    or path.get("load_bearing_structure")),
                "active_leg_failure_status": leg_failure_status,
                "prior_active_leg_failure_status": leg_evidence(
                    continuity, "prior_active_leg_failure_status",
                    "prior_thesis_falsifier_status"),
                # ... and the campaign premise, which no producer binds yet.
                "campaign_premise": campaign_premise_unbound(),
                "thesis_falsifier": None,
                "thesis_falsifier_status": CAMPAIGN_FALSIFIER_STATUS_UNBOUND,
                "prior_thesis_falsifier_status": CAMPAIGN_FALSIFIER_STATUS_UNBOUND,
                "active_draw": str(stance.get("active_draw") or "")[:300],
                "objective_id": stance.get("objective_id"),
                "control_state": continuity.get("control_state"),
            }
            if self._scope is not None:
                # STAGE-3B-1A: producer-authored scope from the snapshot this
                # stance was formed on. A field that cannot be established is
                # recorded as missing (the row is then never eligible).
                current = self._current_scope(snapshot)
                self._sequence += 1
                entry.update({
                    "stance_schema_version": STANCE_SCHEMA_VERSION,
                    "contract_id": current["contract_id"],
                    "market_session": current["market_session"],
                    "process_session_id": current["process_session_id"],
                    "recorded_at_cutoff": current["recorded_at_cutoff"],
                    "history_lineage": {
                        "custody": self._custody_token,
                        "history_revision": current["history_revision"],
                        "sequence": self._sequence,
                    },
                })
                eligible, _withheld, _current = self._partition(snapshot)
                prev_dir = eligible[-1]["direction"] if eligible else None
            else:
                prev = self._buf[-1] if self._buf else None
                prev_dir = prev.get("direction") if isinstance(prev, dict) else None
            # The stored row never aliases the transported input it was built from.
            entry = copy.deepcopy(entry)
            if entry["direction"] != prev_dir:
                self._thesis_anchor = copy.deepcopy(entry)   # new directional thesis began
            self._buf.append(entry)
            if len(self._buf) > self._max:
                self._buf.pop(0)
            self._save()
        except Exception:  # noqa: BLE001
            pass

    def recent(self, n: int = 5) -> list:
        return list(self._buf[-n:])

    def history_summary(self, snapshot: dict = None) -> dict:
        """The block injected into the next brain input. Never raises.

        Returned rows are copies: nothing recorded or re-anchored later can
        alter an input that was already handed to the model.
        """
        if self._scope is not None:
            return self._scoped_history_summary(snapshot)
        try:
            if not self._buf:
                return {"available": False, "last": None, "prior_5": [],
                        "thesis_anchor": None, "changed_since_last": None}
            last = self._buf[-1]
            prev = self._buf[-2] if len(self._buf) >= 2 else None
            changed = None
            if prev:
                changed = {
                    "direction": prev["direction"] != last["direction"],
                    "phase":     prev["phase"] != last["phase"],
                    "from": {"direction": prev["direction"], "phase": prev["phase"]},
                    "to":   {"direction": last["direction"], "phase": last["phase"]},
                }
            return copy.deepcopy({
                "available":          True,
                "last":               last,
                "prior_5":            self.recent(5),
                "thesis_anchor":      self._thesis_anchor,
                "changed_since_last": changed,
                # CONTINUITY-2B: prior stances may have been reasoned from a
                # tape that was later repaired. Terra is told, not steered.
                "history_revision":   self.superseded_summary(),
            })
        except Exception:  # noqa: BLE001
            return {"available": False, "last": None, "prior_5": [],
                    "thesis_anchor": None, "changed_since_last": None}

    def _scoped_history_summary(self, snapshot) -> dict:
        """STAGE-3B-1A: only PROVED rows supply last/prior_5/anchor/change.

        "Most recent" is the eligible row with the latest canonical settled
        cutoff, ties broken by recording sequence -- never wall-clock and
        never buffer position alone. Withheld rows cannot block a healthy
        incumbent and cannot become one.
        """
        try:
            eligible, withheld, current = self._partition(snapshot)
            reasons = {}
            for _index, _row, reason in withheld:
                reasons[reason] = reasons.get(reason, 0) + 1
            context = [_withheld_view(row, reason) for _index, row, reason
                       in withheld[-WITHHELD_CONTEXT_ROWS:]]
            summary = {
                "available": bool(eligible),
                "last": None, "prior_5": [], "thesis_anchor": None,
                "changed_since_last": None,
                "history_revision": self.superseded_summary(),
                "withheld_context": context,
                "eligibility": {
                    "stance_schema_version": STANCE_SCHEMA_VERSION,
                    "selection_rule": SELECTION_RULE,
                    "current_scope": {k: current[k] for k in (
                        "contract_id", "market_session", "process_session_id",
                        "recorded_at_cutoff", "history_revision")},
                    "eligible_count": len(eligible),
                    "withheld_count": len(withheld),
                    "withheld_reasons": reasons,
                    "authority": ("withheld_context rows are audit context only; "
                                  "they supply no prior thesis or falsifier status"),
                },
            }
            if eligible:
                last = eligible[-1]
                prev = eligible[-2] if len(eligible) >= 2 else None
                if prev:
                    summary["changed_since_last"] = {
                        "direction": prev["direction"] != last["direction"],
                        "phase":     prev["phase"] != last["phase"],
                        "from": {"direction": prev["direction"], "phase": prev["phase"]},
                        "to":   {"direction": last["direction"], "phase": last["phase"]},
                    }
                summary.update(last=last, prior_5=eligible[-5:],
                               thesis_anchor=self._eligible_anchor(eligible, current))
            return copy.deepcopy(summary)
        except Exception:  # noqa: BLE001
            return {"available": False, "last": None, "prior_5": [],
                    "thesis_anchor": None, "changed_since_last": None,
                    "withheld_context": [], "eligibility": {"error": True}}

    def _eligible_anchor(self, eligible, current):
        """Start of the trailing same-direction run of ELIGIBLE rows.

        The stored anchor is kept only when it is itself eligible and the run
        spans every retained eligible row (the run began before the buffer
        window); otherwise the run start inside the window is exact.
        """
        direction = eligible[-1]["direction"]
        start = len(eligible) - 1
        while start > 0 and eligible[start - 1]["direction"] == direction:
            start -= 1
        run_start = eligible[start]
        stored = self._thesis_anchor
        if (start == 0 and isinstance(stored, dict)
                and stored.get("direction") == direction
                and self._safe_withheld_reason(stored, current) is None
                and (_instant_key(stored["recorded_at_cutoff"]),
                     stored["history_lineage"]["sequence"])
                <= (_instant_key(run_start["recorded_at_cutoff"]),
                    run_start["history_lineage"]["sequence"])):
            return stored
        return run_start

    # ── history revision (CONTINUITY-2B, 2026-08-11) ─────────────────────────
    #
    # A stance is a BELIEF Terra formed about a market it was shown. When the
    # canonical tape is retroactively repaired, every stance recorded before
    # that repair was reasoned from a world that no longer exists -- and this
    # buffer feeds straight back into the next prompt via `history_summary`.
    # Mechanical state can be re-derived; a belief cannot, so it is RE-ANCHORED
    # rather than replayed.
    #
    # The entries are NOT deleted. They are evidence of what Terra actually
    # thought, and destroying them would be the same error as erasing a
    # rejection. What is removed is their AUTHORITY: they are marked as formed
    # before a revision, and the summary says so, so Terra is told rather than
    # quietly steered by a superseded conviction.
    def supersede(self, revision: int, note: str = "") -> dict:
        """Mark every stance recorded so far as predating `revision`."""
        try:
            marked = not_markable = 0
            for entry in self._buf:
                # STAGE-3B-1A-R1: a non-object element cannot carry a mark and
                # is never eligible anyway; it must not stop the valid rows
                # after it from being marked and persisted.
                if not isinstance(entry, dict):
                    not_markable += 1
                    continue
                if entry.get("superseded_by_history_revision") is None:
                    entry["superseded_by_history_revision"] = int(revision)
                    marked += 1
            if isinstance(self._thesis_anchor, dict):
                self._thesis_anchor["superseded_by_history_revision"] = int(revision)
            self._history_revision = int(revision)
            self._supersede_note = str(note or "")
            self._save()
            return {"marked": marked, "revision": int(revision),
                    "not_markable": not_markable}
        except Exception:  # noqa: BLE001 — memory may never cost a scan
            return {"marked": 0, "revision": revision, "error": True}

    def superseded_summary(self) -> dict:
        """What the next prompt should be told about its own history."""
        revision = getattr(self, "_history_revision", None)
        stale = [e for e in self._buf if isinstance(e, dict)
                 and e.get("superseded_by_history_revision") is not None]
        return {
            "history_revision": revision,
            "stances_formed_before_a_repair": len(stale),
            "note": (getattr(self, "_supersede_note", "")
                     or ("market history was repaired after these stances were "
                         "formed; they described a tape that has since changed"
                         if stale else "")),
        }


# ── STAGE-3B-1A helpers ──────────────────────────────────────────────────────
def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _settled_instant(value):
    """Canonical UTC instant of a settled cutoff, or None.

    The cutoff is the snapshot's own timestamp: the last settled 1m bar of
    the tape the stance was formed on (ProductionScanCycle refuses a scan
    without candles), never the time the row happened to be written.
    """
    try:
        from market_data.object_identity import canonical_instant
        return canonical_instant(value, strict=True) if value else None
    except Exception:  # noqa: BLE001
        return None


def _instant_key(value):
    from datetime import datetime
    return datetime.fromisoformat(str(value))


def _instant_after(left, right) -> bool:
    return _instant_key(left) > _instant_key(right)


def _session_key(instant):
    try:
        from market_state.active_path import production_session_key
        return production_session_key(instant)
    except Exception:  # noqa: BLE001
        return None


def _consumed_fields_well_formed(row, cutoff) -> bool:
    """STAGE-3B-1A-R1: every field selection, the anchor/change summary and
    narrative continuity read from an eligible row has the producer's shape.

    Only shape is checked; nothing is repaired or defaulted. `timestamp` must
    be the same settled instant as `recorded_at_cutoff`, because continuity
    judges session and causal order from it.
    """
    return bool(
        isinstance(row.get("direction"), str) and row.get("direction")
        and "phase" in row
        and (row["phase"] is None or isinstance(row["phase"], str))
        and _is_int(row.get("narrative_state_version"))
        and row.get("narrative_state_version") == 1
        and _settled_instant(row.get("timestamp")) == cutoff
        and isinstance(row.get("campaign_direction"), str)
        and isinstance(row.get("campaign_established"), bool)
        and (row.get("thesis_falsifier_status") is None
             or isinstance(row.get("thesis_falsifier_status"), str))
        and (row.get("thesis_falsifier") is None
             or isinstance(row.get("thesis_falsifier"), dict))
        # STAGE-3B-1B: continuity reads the prior row's LEG evidence. A row
        # without these fields predates 3B-1B (it carried leg values under the
        # campaign-falsifier names) and is never re-read as current custody.
        and "active_leg_failure_status" in row
        and (row["active_leg_failure_status"] is None
             or isinstance(row["active_leg_failure_status"], str))
        and "active_leg_structure" in row
        and (row["active_leg_structure"] is None
             or isinstance(row["active_leg_structure"], dict)))


#: Longest rendering of any one withheld field or malformed item.
CONTEXT_VALUE_LIMIT = 200


def _safe_text(value) -> str:
    """Text for a preview; never raises (huge ints, cyclic or odd objects)."""
    try:
        return repr(value)
    except Exception:  # noqa: BLE001
        if isinstance(value, int) and not isinstance(value, bool):
            return f"<int of {value.bit_length()} bits>"
        return f"<unrenderable {type(value).__name__}>"


def _typed_preview(text, value) -> dict:
    return {"truncated_preview": text[:CONTEXT_VALUE_LIMIT],
            "type": type(value).__name__}


def _bounded(value):
    """A detached, size-bounded, strict-JSON rendering of retained content.

    Small finite numbers, None and bools pass unchanged. A long number, a
    non-finite float or a large/non-JSON object becomes a typed preview whose
    preview text is at most CONTEXT_VALUE_LIMIT characters (plus the fixed
    wrapper keys); strings are cut to the limit. The stored row is never
    modified and withholding reasons are unaffected.
    """
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        try:
            text = repr(value)
        except ValueError:   # beyond the interpreter's int-to-text limit
            return _typed_preview(f"<int of {value.bit_length()} bits>", value)
        return value if len(text) <= CONTEXT_VALUE_LIMIT else _typed_preview(text, value)
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        return _typed_preview(_safe_text(value), value)
    if isinstance(value, str):
        return value[:CONTEXT_VALUE_LIMIT]
    try:
        text = json.dumps(value, sort_keys=True, allow_nan=False)
    except Exception:  # noqa: BLE001 -- not strict JSON: preview only
        return _typed_preview(_safe_text(value), value)
    if len(text) <= CONTEXT_VALUE_LIMIT:
        return copy.deepcopy(value)
    return _typed_preview(text, value)


def _withheld_view(row, reason) -> dict:
    """What an un-proved row may still say: context, never authority."""
    if not isinstance(row, dict):
        try:
            preview = json.dumps(row, default=str, allow_nan=False)
        except Exception:  # noqa: BLE001
            preview = _safe_text(row)
        return {"item_type": type(row).__name__,
                "item_preview": preview[:CONTEXT_VALUE_LIMIT],
                "authority_withheld_reason": reason}
    view = {key: _bounded(row.get(key)) for key in (
        "timestamp", "recorded_at_cutoff", "direction", "campaign_direction",
        "phase", "action", "contract_id", "market_session", "history_lineage",
        "superseded_by_history_revision")}
    view["authority_withheld_reason"] = reason
    return view
