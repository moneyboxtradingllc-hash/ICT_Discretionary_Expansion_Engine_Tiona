"""Campaign Draw facts measured on the production settled 1-minute chart.

This module owns no strategy authority. It records how an already accepted
campaign destination has behaved according to settled provider candles. It
does not claim exhaustive exchange-trade history, choose an objective, or
authorize an entry.

The tracker is deliberately process-local. A new process has no live draw
authority until a fresh settled snapshot and accepted campaign view establish
one again. Production decision records are the audit trail; they are never
loaded back as current authority.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import uuid
from datetime import datetime

from market_data.object_identity import canonical_instant, row_contract

PROVEN_DELIVERED = "PROVEN_DELIVERED"
PROVEN_NOT_DELIVERED = "PROVEN_NOT_DELIVERED"
UNKNOWN = "UNKNOWN"

_CONTIGUOUS = "contiguous"
_EXPECTED_BREAK = "expected_market_break"

# PARTICIPATION AUTHORITY (STAGE 2 TEMPORAL-AUTHORITY CLOSURE).
#
# A scan's measured Draw (`campaign_draw_truth` / `campaign_draw_context`) is a
# market fact. Its PARTICIPATION authority is narrower: the one Draw projection
# Lifecycle, CandidateProducer and conditional plans may treat as positive for
# THIS scan. Two causal facts can withhold a positive measurement:
#
#   RETIRED      the scan's own current acceptance superseded/replaced the
#                record that was measured before cognition. A judgment that
#                retired a destination may not trade toward it on the same scan.
#   UNMEASURED   no settled bar exists after the record's birth anchor. A Draw
#                is born from a Brain judgment at its anchor; until the market
#                has printed at least one newer settled 1m bar, "not delivered"
#                is only that judgment restated, so a same-cutoff re-cognition
#                cannot be authorized by its predecessor's output.
#
# Withholding never deletes or rewrites the record: the tracker keeps it and a
# later healthy scan may use it. Missing authority is the same UNKNOWN shape.
PARTICIPATION_WITHHELD_RETIRED = (
    "pre_cognition_campaign_draw_retired_by_current_acceptance")
PARTICIPATION_WITHHELD_UNMEASURED = (
    "campaign_draw_not_measured_beyond_birth_anchor")
PARTICIPATION_AUTHORITY_MISSING = "campaign_draw_participation_authority_missing"
PARTICIPATION_AUTHORITY_ERROR = "campaign_draw_participation_authority_error"


def withheld_participation_authority(reason: str, measured: dict | None = None) -> dict:
    """The UNKNOWN participation projection, naming why authority is absent."""
    out = {"authority_status": UNKNOWN, "authority_reason": str(reason),
           "coverage_status": "UNKNOWN", "history_complete": False,
           "process_authority": "CURRENT_PROCESS_ONLY",
           "evidence_basis": "provider_settled_1m_chart",
           "claim_scope": "chart_delivery_not_exchange_tick_sequence",
           "participation_withheld_reason": str(reason)}
    if isinstance(measured, dict) and measured.get("record_id"):
        out["withheld_record_id"] = measured.get("record_id")
        out["withheld_authority_status"] = measured.get("authority_status")
    return out


def scan_participation_authority(scan) -> dict:
    """The only Draw a scan result may lend to a participation decision.

    `campaign_draw_truth` may contain a record born from this scan's own
    response, so it is never a substitute: an absent authority is UNKNOWN.
    """
    authority = scan.get("campaign_draw_authority") if isinstance(scan, dict) else None
    if isinstance(authority, dict):
        return authority
    return withheld_participation_authority(PARTICIPATION_AUTHORITY_MISSING)


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _bar_state(bar: dict) -> tuple:
    return tuple(bar.get(k) for k in
                 ("open", "high", "low", "close", "volume", "contract"))


def _bar_digest(bar: dict) -> str:
    payload = {k: bar.get(k) for k in
               ("timestamp", "open", "high", "low", "close", "volume",
                "contract", "contractId")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str,
                                     separators=(",", ":")).encode()).hexdigest()


def _canonical_settled_bars(bars, contract_id: str) -> tuple[list, str | None]:
    """Validate the provider's completed-candle series without repairing it."""
    if not isinstance(bars, (list, tuple)) or not bars:
        return [], "settled_candles_unavailable"
    from market_data.canonical_history import candle_defects

    by_stamp = {}
    input_stamps = []
    for index, original in enumerate(bars):
        if not isinstance(original, dict):
            return [], f"malformed_candle_row:{index}"
        try:
            stamp = canonical_instant(original.get("timestamp"), strict=True)
        except Exception:
            return [], f"malformed_candle_timestamp:{index}"
        if original.get("complete") is not True:
            return [], f"candle_not_proven_settled:{stamp}"
        defects = candle_defects(original)
        if defects:
            return [], f"malformed_candle:{stamp}:{','.join(defects)}"
        try:
            named_contract = row_contract(original, where="campaign draw candle")
        except Exception:
            return [], f"candle_contract_conflict:{stamp}"
        if named_contract and named_contract != contract_id:
            return [], f"candle_contract_mismatch:{stamp}"
        normalized = dict(original)
        normalized["timestamp"] = stamp
        # Bind contractless 1m rows to the exact provider contract supplied by
        # ProductionScanCycle. TopstepX's closed-candle adapter strips row
        # contract fields after fetching from its contract-bound provider.
        normalized["contract"] = named_contract or contract_id
        for field in ("open", "high", "low", "close"):
            normalized[field] = _finite(original.get(field))
        if any(normalized[k] is None for k in ("open", "high", "low", "close")):
            return [], f"malformed_candle:{stamp}:non_finite_ohlc"
        if not (normalized["low"] <= normalized["open"] <= normalized["high"]
                and normalized["low"] <= normalized["close"] <= normalized["high"]):
            return [], f"malformed_candle:{stamp}:ohlc_order"
        input_stamps.append(stamp)
        prior = by_stamp.get(stamp)
        if prior is not None and _bar_state(prior) != _bar_state(normalized):
            return [], f"conflicting_duplicate_candle:{stamp}"
        by_stamp[stamp] = normalized

    # The production history boundary promises oldest-first canonical rows.
    # Identical duplicate rows are harmless; out-of-order input is not silently
    # sorted into a more authoritative-looking history.
    unique_input = list(dict.fromkeys(input_stamps))
    if unique_input != sorted(unique_input):
        return [], "settled_candles_not_chronological"
    return [by_stamp[k] for k in sorted(by_stamp)], None


def _opportunity_authority(bar: dict, instrument: str) -> tuple[bool, str | None]:
    from market_data.evidence_continuity import trade_opportunity_authority
    verdict = trade_opportunity_authority(
        bar["timestamp"], bar_present=True, instrument=instrument)
    if not verdict.get("trade_opportunity_authority"):
        return False, str(verdict.get("reason") or verdict.get("calendar_class"))
    return True, None


def _continuity(bars: list) -> tuple[bool, str | None, dict]:
    if len(bars) < 2:
        return True, None, {"continuity_class": _CONTIGUOUS,
                            "observation_count": len(bars), "gaps": []}
    from market_data.evidence_continuity import evaluate
    report = evaluate(bars, source_tf="1m")
    kind = report.get("continuity_class")
    if kind in (_CONTIGUOUS, _EXPECTED_BREAK):
        return True, None, report
    return False, f"settled_history_continuity:{kind}", report


class CampaignDrawTruth:
    """Process-local campaign-draw history and current chart measurement."""

    def __init__(self, *, contract_id: str, session_id: str,
                 instrument: str = "MNQ", audit_records=None):
        self.contract_id = str(contract_id or "").strip()
        self.session_id = str(session_id or "").strip()
        self.instrument = str(instrument or "").strip()
        # This is an audit-record namespace only. It is never used as market
        # identity or chronology; a restarted process intentionally gets a
        # different namespace and cannot appear to resume the old authority.
        self._process_namespace = uuid.uuid4().hex
        self._ownership_episode_id: str | None = None
        self._records: list[dict] = copy.deepcopy(list(audit_records or []))
        # Imported records are strictly audit-only. Even if a caller passes a
        # record whose last in-memory status was COMPLETE, no active authority
        # crosses a tracker replacement/restart boundary.
        for record in self._records:
            if not record.get("superseded"):
                record["historical_result"] = record.get("authority_status", UNKNOWN)
                record["superseded"] = True
                record["superseded_reason"] = "tracker_replaced_no_authority_restore"
                record["authority_status"] = UNKNOWN
                record["authority_reason"] = "tracker_replaced_no_authority_restore"
        self._active: dict | None = None

    @property
    def audit_records(self) -> list[dict]:
        return copy.deepcopy(self._records)

    def invalidate_for_history_revision(self, revision: int) -> None:
        """Retire active authority while preserving the prior audit record."""
        if self._active is not None:
            self._active["invalidated_by_history_revision"] = int(revision)
        self._supersede("canonical_history_revision_changed", close_episode=True)

    def observe(self, *, settled_bars, settled_source: dict,
                contract_id: str, session_id: str, history_revision: int,
                derived_state_current: bool,
                accepted_view: dict | None = None,
                ownership_state: dict | None = None,
                advance_existing: bool = True,
                acceptance_outcome: dict | None = None) -> dict:
        """Advance existing facts and optionally bind a fresh accepted view.

        `accepted_view` must already contain the canonical objective resolved
        from the deterministic snapshot catalog and a Narrative Authority
        authorization result. This module never interprets Brain prose.

        `advance_existing=False` is reserved for the post-cognition acceptance
        lane after this same scan has already measured the incumbent. It still
        validates and persists the current response, but never advances the
        incumbent through the settled interval a second time.
        """
        if isinstance(acceptance_outcome, dict):
            acceptance_outcome.clear()
            acceptance_outcome.update({
                "accepted": False,
                "reason": "campaign_draw_acceptance_unresolved",
            })

        def note_acceptance(accepted: bool, reason: str | None = None) -> None:
            if isinstance(acceptance_outcome, dict):
                acceptance_outcome["accepted"] = bool(accepted)
                acceptance_outcome["reason"] = (None if accepted else
                                                 str(reason or
                                                     "campaign_draw_acceptance_refused"))

        contract = str(contract_id or "").strip()
        session = str(session_id or "").strip()
        source = settled_source if isinstance(settled_source, dict) else {}
        try:
            cutoff = canonical_instant(source.get("source_bar_time"), strict=True)
        except Exception:
            cutoff = None
        if (not self.contract_id or contract != self.contract_id
                or not session or session != self.session_id):
            self._supersede("session_or_contract_identity_changed",
                            close_episode=True)
            note_acceptance(False, "session_or_contract_identity_unavailable")
            return self._unknown("session_or_contract_identity_unavailable")

        # ActivePath is the canonical mechanical owner state. A Campaign Draw
        # is one continuous ownership episode: contested, invalidated, absent,
        # unavailable, or differently owned state ends that episode. A later
        # same-direction reacquisition must receive a new episode ID and anchor.
        # Descriptive Brain text is deliberately not consulted here.
        ownership_state = (ownership_state if isinstance(ownership_state, dict)
                           else None)
        ownership_loss = self._ownership_loss_reason(self._active,
                                                       ownership_state)
        if ownership_loss:
            self._supersede(ownership_loss, close_episode=True)
        elif self._active is not None and ownership_state is not None:
            self._active["active_path_last_invalidated"] = copy.deepcopy(
                ownership_state.get("last_invalidated") or {})
        if not derived_state_current:
            self._supersede("derived_history_not_current", close_episode=True)
            note_acceptance(False, "derived_history_not_current")
            return self._unknown("derived_history_not_current")
        if source.get("temporal_status") != "settled" or cutoff is None:
            self._break_current("settled_source_unavailable")
            note_acceptance(False, "settled_source_unavailable")
            return self._unknown("settled_source_unavailable", active=self._active)

        from market_state.active_path import production_session_key
        market_session = production_session_key(cutoff)
        if not market_session:
            self._supersede("market_session_unavailable", close_episode=True)
            note_acceptance(False, "anchor_market_session_unavailable")
            return self._unknown("anchor_market_session_unavailable")

        rows, error = _canonical_settled_bars(settled_bars, contract)
        if error:
            proof_bar = (self._active or {}).get("delivery_evidence_bar")
            if proof_bar and proof_bar in error:
                self._supersede("campaign_delivery_evidence_superseded:" + error)
            else:
                self._break_current(error)
            note_acceptance(False, error)
            return self._unknown(error, active=self._active)
        if not rows or rows[-1]["timestamp"] != cutoff:
            reason = "settled_cutoff_does_not_match_market_source"
            self._break_current(reason)
            note_acceptance(False, reason)
            return self._unknown(reason, active=self._active)

        # A changed revision invalidates every current conclusion that depended
        # on the old tape. A fresh accepted view may establish a new anchor in
        # this same scan, because it was authored after the canonical rebuild.
        if (self._active is not None
                and int(history_revision) != self._active["history_revision"]):
            self._supersede("canonical_history_revision_changed",
                            close_episode=True)
        elif (self._active is not None
              and self._active.get("market_session") != market_session):
            self._supersede("market_session_changed", close_episode=True)
        elif self._active is not None and advance_existing:
            self._advance(self._active, rows, cutoff)

        view = accepted_view if isinstance(accepted_view, dict) else None
        if view is None:
            if self._active is not None:
                return self._public(self._active)
            return self._unknown("no_accepted_campaign_draw")
        if view.get("direction_authorized") is not True:
            note_acceptance(False, str(view.get("refusal_reason") or
                                        "campaign_direction_not_authorized"))
            if self._active is not None:
                return self._public(self._active)
            return self._unknown(str(view.get("refusal_reason") or
                                     "campaign_direction_not_authorized"))

        direction = str(view.get("direction") or "").strip().lower()
        objective = view.get("objective")
        if direction not in ("bullish", "bearish") or not isinstance(objective, dict):
            note_acceptance(False, "accepted_campaign_objective_unavailable")
            return self._unknown("accepted_campaign_objective_unavailable",
                                 active=self._active)
        if ownership_state is None:
            note_acceptance(False, "campaign_owner_state_unavailable")
            return self._unknown("campaign_owner_state_unavailable",
                                 active=self._active)
        named_owner = str(ownership_state.get("owner") or "").strip().lower()
        named_status = str(ownership_state.get("status") or "").strip().lower()
        if (ownership_state.get("state_available") is not True
                or named_owner != direction or named_status != "active"):
            note_acceptance(False, "campaign_owner_not_currently_established")
            return self._unknown("campaign_owner_not_currently_established",
                                 active=self._active)
        identity = str(objective.get("identity") or "").strip()
        kind = str(objective.get("kind") or "").strip()
        price = _finite(objective.get("price"))
        anchor = rows[-1]
        anchor_close = _finite(anchor.get("close"))
        if not identity or not kind or price is None or anchor_close is None:
            note_acceptance(False, "campaign_objective_or_anchor_incomplete")
            return self._unknown("campaign_objective_or_anchor_incomplete",
                                 active=self._active)
        if ((direction == "bullish" and price <= anchor_close)
                or (direction == "bearish" and price >= anchor_close)):
            note_acceptance(False, "campaign_objective_wrong_side_of_anchor")
            return self._unknown("campaign_objective_wrong_side_of_anchor",
                                 active=self._active)
        anchor_ok, anchor_reason = _opportunity_authority(anchor, self.instrument)
        if not anchor_ok:
            note_acceptance(False, "anchor_bar_lacks_trade_opportunity_authority:" +
                            str(anchor_reason))
            return self._unknown("anchor_bar_lacks_trade_opportunity_authority:" +
                                 str(anchor_reason), active=self._active)

        if self._active is not None and self._active.get("campaign_direction") != direction:
            self._supersede("campaign_owner_changed", close_episode=True)
        if self._ownership_episode_id is None:
            self._ownership_episode_id = uuid.uuid4().hex

        key = (session, market_session, contract, direction, identity,
               self._ownership_episode_id)
        active_key = self._key(self._active) if self._active else None
        same = active_key == key
        # Reuse a same campaign and draw across changing catalog indices or
        # scan IDs. A different stable objective, owner, contract or session
        # begins a new record at the current settled source bar.
        if same and self._active.get("objective_price") == price:
            self._active["brain_lineage"] = copy.deepcopy(view.get("brain_lineage") or {})
            note_acceptance(True)
            return self._public(self._active)
        if same and self._active.get("objective_price") != price:
            self._supersede("objective_price_revised")
        elif self._active is not None:
            self._supersede("campaign_or_draw_identity_changed")

        record = {
            "record_id": hashlib.sha256(
                "|".join((self._process_namespace, str(len(self._records) + 1),
                          session, market_session, contract, direction,
                          identity, cutoff, _bar_digest(anchor))).encode()
                ).hexdigest()[:24],
            "process_authority": "CURRENT_PROCESS_ONLY",
            "session_id": session,
            "market_session": market_session,
            "contract_id": contract,
            "campaign_direction": direction,
            "campaign_episode_id": self._ownership_episode_id,
            "active_path_last_invalidated": copy.deepcopy(
                (ownership_state or {}).get("last_invalidated") or {}),
            "objective_identity": identity,
            "objective_kind": kind,
            "objective_price": price,
            "objective_side_of_anchor": "above" if price > anchor_close else "below",
            "anchor_bar_time": cutoff,
            "anchor_bar_close": anchor_close,
            "anchor_bar_digest": _bar_digest(anchor),
            "anchor_price_basis": "settled_1m_source_bar_close",
            "history_revision": int(history_revision),
            "settled_cutoff": cutoff,
            "coverage_status": "COMPLETE",
            "authority_status": PROVEN_NOT_DELIVERED,
            "historical_result": PROVEN_NOT_DELIVERED,
            "authority_reason": "continuous_settled_history_through_anchor",
            "history_complete": True,
            "history_issues": [],
            "evidence_bars": {cutoff: copy.deepcopy(anchor)},
            "highest_price_after_anchor": None,
            "highest_bar_time": None,
            "lowest_price_after_anchor": None,
            "lowest_bar_time": None,
            "observed_highest_price_after_anchor": None,
            "observed_highest_bar_time": None,
            "observed_lowest_price_after_anchor": None,
            "observed_lowest_bar_time": None,
            "progress_points": 0.0,
            "total_distance_points": abs(price - anchor_close),
            "observed_progress_fraction": 0.0,
            "progress_authoritative": True,
            "delivery_evidence_bar": None,
            "delivery_evidence_price": None,
            "superseded": False,
            "superseded_reason": None,
            "brain_lineage": copy.deepcopy(view.get("brain_lineage") or {}),
        }
        self._records.append(record)
        self._active = record
        note_acceptance(True)
        return self._public(record)

    def accept_current_view(self, *, settled_bars, settled_source: dict,
                            contract_id: str, session_id: str,
                            history_revision: int,
                            derived_state_current: bool,
                            accepted_view: dict,
                            ownership_state: dict | None = None) -> tuple[dict, dict]:
        """Persist a current Brain view without advancing the incumbent.

        Production calls this only after the same scan has measured the
        pre-cognition incumbent. The returned acceptance status is separate
        from market measurement so a refused response can veto participation
        without being mistaken for a new market fact.
        """
        outcome: dict = {}
        truth = self.observe(
            settled_bars=settled_bars, settled_source=settled_source,
            contract_id=contract_id, session_id=session_id,
            history_revision=history_revision,
            derived_state_current=derived_state_current,
            accepted_view=accepted_view, ownership_state=ownership_state,
            advance_existing=False, acceptance_outcome=outcome)
        if outcome.get("accepted") is not True:
            reason = outcome.get("reason")
            if reason in (None, "campaign_draw_acceptance_unresolved"):
                reason = (truth.get("authority_reason") or
                          (accepted_view or {}).get("refusal_reason") or
                          "campaign_draw_acceptance_refused")
            outcome["accepted"] = False
            outcome["reason"] = str(reason)
        return truth, outcome

    def participation_authority(self, measured: dict | None) -> dict:
        """Project this scan's measured Draw into participation authority.

        Call AFTER the scan's current acceptance (if any) has been processed,
        so liveness is judged against the tracker as this scan leaves it.
        Only a PROVEN_NOT_DELIVERED measurement is positive; every other
        status already refuses and passes through unchanged, preserving its
        own classification (for example a delivered destination).
        """
        if not isinstance(measured, dict):
            return withheld_participation_authority(PARTICIPATION_AUTHORITY_MISSING)
        if measured.get("authority_status") != PROVEN_NOT_DELIVERED:
            return copy.deepcopy(measured)
        active = self._active
        if (active is None or active.get("superseded") is not False
                or not measured.get("record_id")
                or active.get("record_id") != measured.get("record_id")):
            return withheld_participation_authority(
                PARTICIPATION_WITHHELD_RETIRED, measured)
        try:
            anchor = canonical_instant(measured.get("anchor_bar_time"), strict=True)
            cutoff = canonical_instant(measured.get("settled_cutoff"), strict=True)
            measured_beyond_birth = (
                datetime.fromisoformat(cutoff) > datetime.fromisoformat(anchor))
        except Exception:  # noqa: BLE001 -- unprovable chronology is not authority
            measured_beyond_birth = False
        if not measured_beyond_birth:
            return withheld_participation_authority(
                PARTICIPATION_WITHHELD_UNMEASURED, measured)
        return copy.deepcopy(measured)

    @staticmethod
    def _key(record: dict | None):
        if not record:
            return None
        return tuple(record.get(k) for k in
                     ("session_id", "market_session", "contract_id",
                      "campaign_direction", "objective_identity",
                      "campaign_episode_id"))

    @staticmethod
    def _ownership_loss_reason(record: dict | None, state: dict | None) -> str | None:
        if record is None:
            return None
        if state is None or state.get("state_available") is not True:
            return "campaign_ownership_unavailable"
        owner = str(state.get("owner") or "").strip().lower()
        status = str(state.get("status") or "").strip().lower()
        if owner != record.get("campaign_direction") or status != "active":
            return f"campaign_ownership_lost:owner={owner or 'none'}:status={status or 'unknown'}"
        invalidation = state.get("last_invalidated") or {}
        prior_invalidation = record.get("active_path_last_invalidated") or {}
        direction = record.get("campaign_direction")
        if (invalidation.get("owner") == direction
                and (invalidation.get("owner"), invalidation.get("at"),
                     invalidation.get("level"))
                != (prior_invalidation.get("owner"), prior_invalidation.get("at"),
                    prior_invalidation.get("level"))):
            return "campaign_ownership_lost:load_bearing_structure_invalidated"
        return None

    def _supersede(self, reason: str, *, close_episode: bool = False) -> None:
        if self._active is None:
            if close_episode:
                self._ownership_episode_id = None
            return
        self._active["historical_result"] = self._active.get(
            "authority_status", UNKNOWN)
        self._active["superseded"] = True
        self._active["superseded_reason"] = str(reason)
        self._active["authority_status"] = UNKNOWN
        self._active["authority_reason"] = str(reason)
        self._active = None
        if close_episode:
            self._ownership_episode_id = None

    def _break_current(self, reason: str) -> None:
        """Remove negative/extrema completeness without erasing a proved touch."""
        if self._active is None:
            return
        record = self._active
        record["coverage_status"] = "INCOMPLETE"
        record["history_complete"] = False
        record["progress_authoritative"] = False
        record["progress_points"] = None
        record["observed_progress_fraction"] = None
        record["history_issues"] = [str(reason)]
        if record.get("delivery_evidence_bar") is not None:
            record["authority_status"] = PROVEN_DELIVERED
            record["historical_result"] = PROVEN_DELIVERED
            record["authority_reason"] = (
                "settled_delivery_fact_preserved_after_coverage_break:" + str(reason))
        else:
            record["authority_status"] = UNKNOWN
            record["historical_result"] = UNKNOWN
            record["authority_reason"] = str(reason)

    def _advance(self, record: dict, rows: list, cutoff: str) -> None:
        evidence = record["evidence_bars"]
        last_before = max(evidence)
        for bar in rows:
            stamp = bar["timestamp"]
            if stamp < record["anchor_bar_time"] or stamp > cutoff:
                continue
            prior = evidence.get(stamp)
            if prior is not None:
                if _bar_digest(prior) != _bar_digest(bar):
                    self._supersede("campaign_input_bar_superseded")
                    return
                continue
            if stamp <= last_before:
                self._supersede("retroactive_settled_bar_inserted")
                return
            if stamp == record["anchor_bar_time"]:
                if _bar_digest(bar) != record["anchor_bar_digest"]:
                    self._supersede("campaign_anchor_bar_superseded")
                    return
                continue
            evidence[stamp] = copy.deepcopy(bar)
            last_before = stamp

        record["settled_cutoff"] = cutoff
        all_bars = [evidence[k] for k in sorted(evidence)]
        # Record observations for audit, but bars within a scheduled/unknown
        # non-trading period cannot prove either a touch or an extreme.
        eligible = []
        market_reason = None
        for bar in all_bars:
            if bar["timestamp"] == record["anchor_bar_time"]:
                eligible.append(bar)
                continue
            ok, reason = _opportunity_authority(bar, self.instrument)
            if ok:
                eligible.append(bar)
            else:
                market_reason = "bar_without_trade_opportunity_authority:" + str(reason)

        complete, gap_reason, continuity = _continuity(all_bars)
        issues = []
        if not complete:
            issues.append(gap_reason)
        if market_reason:
            issues.append(market_reason)
        record["history_complete"] = complete and market_reason is None
        record["coverage_status"] = "COMPLETE" if record["history_complete"] else "INCOMPLETE"
        record["history_issues"] = issues
        record["continuity_evidence"] = {
            "continuity_class": continuity.get("continuity_class"),
            "observation_count": continuity.get("observation_count"),
            "gaps": copy.deepcopy(continuity.get("gaps") or []),
        }

        after = [b for b in eligible if b["timestamp"] > record["anchor_bar_time"]]
        high = max(after, key=lambda b: b["high"], default=None)
        low = min(after, key=lambda b: b["low"], default=None)
        record["observed_highest_price_after_anchor"] = high.get("high") if high else None
        record["observed_highest_bar_time"] = high.get("timestamp") if high else None
        record["observed_lowest_price_after_anchor"] = low.get("low") if low else None
        record["observed_lowest_bar_time"] = low.get("timestamp") if low else None
        # A maximum/minimum over the whole campaign interval is not established
        # by partial history. Keep raw observed extrema for audit, but publish
        # authoritative extrema only when continuity proves the entire window.
        record["highest_price_after_anchor"] = (
            record["observed_highest_price_after_anchor"]
            if record["history_complete"] else None)
        record["highest_bar_time"] = (
            record["observed_highest_bar_time"] if record["history_complete"] else None)
        record["lowest_price_after_anchor"] = (
            record["observed_lowest_price_after_anchor"]
            if record["history_complete"] else None)
        record["lowest_bar_time"] = (
            record["observed_lowest_bar_time"] if record["history_complete"] else None)

        if record.get("delivery_evidence_bar") is None:
            for bar in after:
                touched = (bar["high"] >= record["objective_price"]
                           if record["campaign_direction"] == "bullish"
                           else bar["low"] <= record["objective_price"])
                if touched:
                    record["delivery_evidence_bar"] = bar["timestamp"]
                    record["delivery_evidence_price"] = (
                        bar["high"] if record["campaign_direction"] == "bullish"
                        else bar["low"])
                    break

        distance = record["total_distance_points"]
        if record["campaign_direction"] == "bullish":
            extreme = record["highest_price_after_anchor"]
            favorable = max(0.0, float(extreme) - record["anchor_bar_close"]
                            ) if extreme is not None else 0.0
        else:
            extreme = record["lowest_price_after_anchor"]
            favorable = max(0.0, record["anchor_bar_close"] - float(extreme)
                            ) if extreme is not None else 0.0
        record["progress_points"] = favorable if record["history_complete"] else None
        record["observed_progress_fraction"] = (
            favorable / distance if record["history_complete"] and distance > 0
            else (0.0 if record["history_complete"] else None))
        record["progress_authoritative"] = bool(record["history_complete"])

        if record.get("delivery_evidence_bar") is not None:
            record["authority_status"] = PROVEN_DELIVERED
            record["authority_reason"] = "settled_1m_bar_reached_objective"
        elif record["history_complete"]:
            record["authority_status"] = PROVEN_NOT_DELIVERED
            record["authority_reason"] = "continuous_settled_history_no_objective_touch"
        else:
            record["authority_status"] = UNKNOWN
            record["authority_reason"] = ";".join(issues) or "settled_history_incomplete"
        record["historical_result"] = record["authority_status"]

    @staticmethod
    def _public(record: dict) -> dict:
        out = {k: copy.deepcopy(v) for k, v in record.items()
               if k not in ("evidence_bars", "anchor_bar_digest")}
        out["evidence_basis"] = "provider_settled_1m_chart"
        out["claim_scope"] = "chart_delivery_not_exchange_tick_sequence"
        return out

    def _unknown(self, reason: str, *, active: dict | None = None) -> dict:
        if active is not None:
            out = self._public(active)
            if active.get("delivery_evidence_bar") is not None:
                # Positive settled-bar evidence is monotonic. Failure to resolve
                # a newer proposed view cannot make that historical chart fact
                # disappear; it only withholds new negative/progress claims.
                out["authority_status"] = PROVEN_DELIVERED
                out["authority_reason"] = active.get("authority_reason")
            else:
                out["authority_status"] = UNKNOWN
                out["authority_reason"] = str(reason)
            out["progress_authoritative"] = False
            out["progress_points"] = None
            out["observed_progress_fraction"] = None
            return out
        return {"authority_status": UNKNOWN, "authority_reason": str(reason),
                "coverage_status": "UNKNOWN", "history_complete": False,
                "process_authority": "CURRENT_PROCESS_ONLY",
                "evidence_basis": "provider_settled_1m_chart",
                "claim_scope": "chart_delivery_not_exchange_tick_sequence"}
