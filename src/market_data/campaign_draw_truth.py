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
        self._supersede("canonical_history_revision_changed")

    def observe(self, *, settled_bars, settled_source: dict,
                contract_id: str, session_id: str, history_revision: int,
                derived_state_current: bool,
                accepted_view: dict | None = None) -> dict:
        """Advance existing facts and optionally bind a fresh accepted view.

        `accepted_view` must already contain the canonical objective resolved
        from the deterministic snapshot catalog and a Narrative Authority
        authorization result. This module never interprets Brain prose.
        """
        contract = str(contract_id or "").strip()
        session = str(session_id or "").strip()
        source = settled_source if isinstance(settled_source, dict) else {}
        try:
            cutoff = canonical_instant(source.get("source_bar_time"), strict=True)
        except Exception:
            cutoff = None
        if (not self.contract_id or contract != self.contract_id
                or not session or session != self.session_id):
            self._supersede("session_or_contract_identity_changed")
            return self._unknown("session_or_contract_identity_unavailable")
        if not derived_state_current:
            self._supersede("derived_history_not_current")
            return self._unknown("derived_history_not_current")
        if source.get("temporal_status") != "settled" or cutoff is None:
            self._break_current("settled_source_unavailable")
            return self._unknown("settled_source_unavailable", active=self._active)

        from market_state.active_path import production_session_key
        market_session = production_session_key(cutoff)
        if not market_session:
            self._supersede("market_session_unavailable")
            return self._unknown("anchor_market_session_unavailable")

        rows, error = _canonical_settled_bars(settled_bars, contract)
        if error:
            proof_bar = (self._active or {}).get("delivery_evidence_bar")
            if proof_bar and proof_bar in error:
                self._supersede("campaign_delivery_evidence_superseded:" + error)
            else:
                self._break_current(error)
            return self._unknown(error, active=self._active)
        if not rows or rows[-1]["timestamp"] != cutoff:
            reason = "settled_cutoff_does_not_match_market_source"
            self._break_current(reason)
            return self._unknown(reason, active=self._active)

        # A changed revision invalidates every current conclusion that depended
        # on the old tape. A fresh accepted view may establish a new anchor in
        # this same scan, because it was authored after the canonical rebuild.
        if (self._active is not None
                and int(history_revision) != self._active["history_revision"]):
            self._supersede("canonical_history_revision_changed")
        elif (self._active is not None
              and self._active.get("market_session") != market_session):
            self._supersede("market_session_changed")
        elif self._active is not None:
            self._advance(self._active, rows, cutoff)

        view = accepted_view if isinstance(accepted_view, dict) else None
        if view is None:
            if self._active is not None:
                return self._public(self._active)
            return self._unknown("no_accepted_campaign_draw")
        if view.get("direction_authorized") is not True:
            if self._active is not None:
                return self._public(self._active)
            return self._unknown(str(view.get("refusal_reason") or
                                     "campaign_direction_not_authorized"))

        direction = str(view.get("direction") or "").strip().lower()
        objective = view.get("objective")
        if direction not in ("bullish", "bearish") or not isinstance(objective, dict):
            return self._unknown("accepted_campaign_objective_unavailable",
                                 active=self._active)
        identity = str(objective.get("identity") or "").strip()
        kind = str(objective.get("kind") or "").strip()
        price = _finite(objective.get("price"))
        anchor = rows[-1]
        anchor_close = _finite(anchor.get("close"))
        if not identity or not kind or price is None or anchor_close is None:
            return self._unknown("campaign_objective_or_anchor_incomplete",
                                 active=self._active)
        if ((direction == "bullish" and price <= anchor_close)
                or (direction == "bearish" and price >= anchor_close)):
            return self._unknown("campaign_objective_wrong_side_of_anchor",
                                 active=self._active)
        anchor_ok, anchor_reason = _opportunity_authority(anchor, self.instrument)
        if not anchor_ok:
            return self._unknown("anchor_bar_lacks_trade_opportunity_authority:" +
                                 str(anchor_reason), active=self._active)

        key = (session, market_session, contract, direction, identity)
        active_key = self._key(self._active) if self._active else None
        same = active_key == key
        # Reuse a same campaign and draw across changing catalog indices or
        # scan IDs. A different stable objective, owner, contract or session
        # begins a new record at the current settled source bar.
        if same and self._active.get("objective_price") == price:
            self._active["brain_lineage"] = copy.deepcopy(view.get("brain_lineage") or {})
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
        return self._public(record)

    @staticmethod
    def _key(record: dict | None):
        if not record:
            return None
        return tuple(record.get(k) for k in
                     ("session_id", "market_session", "contract_id",
                      "campaign_direction", "objective_identity"))

    def _supersede(self, reason: str) -> None:
        if self._active is None:
            return
        self._active["historical_result"] = self._active.get(
            "authority_status", UNKNOWN)
        self._active["superseded"] = True
        self._active["superseded_reason"] = str(reason)
        self._active["authority_status"] = UNKNOWN
        self._active["authority_reason"] = str(reason)
        self._active = None

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
