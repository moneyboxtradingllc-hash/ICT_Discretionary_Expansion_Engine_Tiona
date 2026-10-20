"""Six-layer projection of the actual producer outputs, and its scoring (gap mission 4).

At every non-PREWARM tick the driver projects what the production graph itself
produced -- the settled snapshot, the campaign Draw, the active path and
Lifecycle, the selected tool or live plan, the loop outcome and final-quote
economics -- into one `layer_projection/v1` artifact bound to the event:

    MARKET_FACTS  the settled 1m bar the snapshot was built on, and the sealed
                  release it came from (version, availability, settlement)
    CAMPAIGN      Draw direction, objective, episode and authority; path origin;
                  the Brain's own direction (a contradiction is never resolved)
    DELIVERY      Lifecycle state, path owner/status, opposing-transfer evidence,
                  last invalidation; mapped onto the annotation vocabulary
    TOOL          playbook, tool family, exact occurrence, zone and its direction
    COMPOSITION   outcome, route, candidate/plan presence, final-quote economics
    TIMING        market open, settled cutoff, latest availability, decision,
                  plan capture, trigger and final-quote times, kept separate

Nothing is inferred beyond the producers: an output the production graph did
not produce is ABSENT with its reason. DELIVERY is mapped from production's own
Lifecycle and path ownership only; local opposing price movement never becomes
a reversal here (a retracement inside an intact campaign stays a retracement).

Scoring compares projections only to sealed admissible truth -- the sealed
corpus for MARKET_FACTS, annotation fields for the other layers. An absent
annotation field is UNSCORED; absent or unusable evidence is UNPROVEN, each with
its reason and source binding. Neither is a MISS, and a no-trade is never
wrong. No win rate or economics is ever truth.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from recognition_validation import contracts as C

SCHEMA = "layer_projection/v1"
LAYERS = ("MARKET_FACTS", "CAMPAIGN", "DELIVERY", "TOOL", "COMPOSITION", "TIMING")
METRICS = {layer: f"layer_{layer.lower()}" for layer in LAYERS}
BAR = timedelta(minutes=1)
#: The candle port's own default lookback (ports.LocalCandlePort.fetch_1m_candles).
LOOKBACK_BARS = 300
DIRECTIONAL = ("bullish", "bearish")
#: Production Lifecycle states -> annotation delivery vocabulary (market_data/campaign_lifecycle.py).
LIFECYCLE_DELIVERY = {"ACTIVE_DELIVERY": "ACTIVE_DELIVERY", "RETRACING": "RETRACEMENT",
                      "TRANSFER_UNRESOLVED": "REVERSAL_DEVELOPING",
                      "DESTINATION_SUBSTANTIALLY_DELIVERED": "DESTINATION_DELIVERED"}
REVERSAL_STATES = ("REVERSAL_DEVELOPING", "TRANSFER_CONFIRMED")
INTACT_STATES = ("ACTIVE_DELIVERY", "RETRACEMENT")
ENTRY_OUTCOMES = ("QUALIFIED_CANDIDATE_OBSERVED", "SUBMIT_FAILED", "TRADE_MISSION_REFUSED")
WATCHING_OUTCOMES = ("CONDITIONAL_PLAN_PUBLISHED", "CONDITIONAL_PLAN_WAITING")
#: Chronology/composition codes that are invariant violations, never scores.
VIOLATIONS = ("FACT_AFTER_DECISION", "FUTURE_EVIDENCE", "FORMING_BAR_AS_FACT", "FACT_NOT_SEALED",
              "TRIGGER_BEFORE_CAPTURE", "FINAL_QUOTE_BEFORE_TRIGGER", "FINAL_QUOTE_OUTSIDE_ZONE",
              "DUPLICATE_COGNITION_CUTOFF")


def _iso(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _at(value):
    return None if value is None else C.instant(str(value))


def _absent(reason, source):
    return {"state": "ABSENT", "reason": reason, "source": source}


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def project(*, tick, scan, candidate, plan, outcome: dict, route: str, trace: dict, releases: list,
            market_open: str, history_revision: int) -> dict:
    """One tick's six layers, read only from what the producers returned.

    The artifact holds no process-random identity (no process lineage, no
    per-process campaign episode id, no candidate or plan id): those stay on
    the event, where `compare` alpha-renames them, so repeats hash identically.
    """
    scan = scan or {}
    snapshot = scan.get("snapshot") or {}
    decision = tick.decision_time
    # -- MARKET_FACTS -------------------------------------------------------------
    last = ((snapshot.get("timeframes") or {}).get("1m") or {}).get("last_candle")
    latest = releases[-1] if releases else None
    if isinstance(last, dict) and last.get("timestamp"):
        bar_open = _at(last["timestamp"])
        release = next((r for r in reversed(releases) if r.bar_open == bar_open), None)
        facts = {"state": "PROJECTED", "source": "snapshot.timeframes.1m.last_candle",
                 "bar_open": bar_open.isoformat(), "settled_cutoff": (bar_open + BAR).isoformat(),
                 "bar": {k: last.get(k) for k in ("open", "high", "low", "close")},
                 "temporal_status": last.get("temporal_status"), "complete": last.get("complete"),
                 "snapshot_timestamp": _iso(snapshot.get("timestamp")),
                 "release": None if release is None else {
                     "version": release.version, "available_at": release.available_at.isoformat(),
                     "settled_at": _iso(release.settled_at),
                     "bar": {k: release.bar[k] for k in ("open", "high", "low", "close")}}}
    else:
        facts = _absent("no_settled_snapshot" if not snapshot else "snapshot_without_1m_bar",
                        "snapshot.timeframes.1m.last_candle")
    # -- CAMPAIGN -----------------------------------------------------------------
    from market_data.campaign_draw_truth import scan_participation_authority
    draw = scan_participation_authority(scan) if scan else None
    path = snapshot.get("active_path_state") or {}
    parsed = ((scan.get("brain_result") or {}).get("parsed") or {}) if isinstance(scan.get("brain_result"), dict) else {}
    history_start = releases[max(0, len(releases) - LOOKBACK_BARS)].bar_open if releases else None
    if isinstance(draw, dict) and draw.get("record_id"):
        origin = path.get("origin") or {}
        campaign = {"state": "PROJECTED", "source": "scan_participation_authority(scan) + snapshot.active_path_state.origin",
                    "direction": draw.get("campaign_direction"),
                    "objective": {"identity": draw.get("objective_identity"), "kind": draw.get("objective_kind"),
                                  "price": draw.get("objective_price")},
                    "origin": {"event": origin.get("event"), "at": origin.get("at"),
                               "occurrence_id": origin.get("occurrence_id")} if origin else None,
                    "authority_status": draw.get("authority_status"), "history_complete": draw.get("history_complete"),
                    "draw_history_revision": draw.get("history_revision"),
                    "brain_direction": parsed.get("narrative_direction"),
                    "history_start": _iso(history_start)}
    else:
        campaign = _absent("campaign_draw_unavailable", "scan_participation_authority(scan)")
    # -- DELIVERY -----------------------------------------------------------------
    lifecycle = snapshot.get("campaign_lifecycle") or scan.get("campaign_lifecycle") or {}
    if path or lifecycle:
        flags = sorted(k for k, v in (path.get("transfer_evidence") or {}).items() if v)
        direction = campaign.get("direction") if campaign["state"] == "PROJECTED" else None
        if path.get("owner") in DIRECTIONAL and direction in DIRECTIONAL and path.get("owner") != direction:
            mapped = "TRANSFER_CONFIRMED"     # production's own ownership change, never price movement
        else:
            mapped = LIFECYCLE_DELIVERY.get(lifecycle.get("state"), "UNKNOWN")
        delivery = {"state": "PROJECTED", "source": "snapshot.campaign_lifecycle + snapshot.active_path_state",
                    "lifecycle_state": lifecycle.get("state"), "lifecycle_reason": lifecycle.get("reason"),
                    "owner": path.get("owner"), "path_status": path.get("status"), "transfer_flags": flags,
                    "last_invalidated": (path.get("last_invalidated") or {}).get("occurrence_id"),
                    "projected_state": mapped}
    else:
        delivery = _absent("lifecycle_and_path_unavailable", "snapshot.campaign_lifecycle")
    # -- TOOL ---------------------------------------------------------------------
    holder, source = candidate, "loop.active_candidate"
    if holder is None and isinstance(plan, dict):
        holder, source = plan.get("candidate"), "loop.active_conditional_plan.candidate"
    extras = getattr(holder, "extras", None) or {}
    if holder is not None:
        zone = extras.get("activation_zone") or extras.get("selected_tool_zone") or {}
        tool = {"state": "PROJECTED", "source": source, "playbook": extras.get("playbook"),
                "tool_family": extras.get("tool_family"),
                "occurrence_id": extras.get("selected_tool_occurrence_id") or zone.get("occurrence_id"),
                "direction": getattr(holder, "direction", None),
                "zone": {"low": zone.get("low"), "high": zone.get("high")},
                "invalidation_id": (extras.get("structural_invalidation") or {}).get("structure_identity")}
    else:
        tool = _absent("no_candidate_or_plan", "loop.active_candidate")
    # -- COMPOSITION / TIMING -----------------------------------------------------
    economics = trace.get("final_quote_economics") or {}
    plan_doc = trace.get("plan_before") if route == "CONDITIONAL_TRIGGER" else (trace.get("plan_after") or trace.get("plan_before"))
    trigger = next((w for w in (trace.get("registry") or {}).get("new_wakes") or []
                    if w.get("reason") in ("conditional_plan_zone_reached", "conditional_plan_armed_inside")), None)
    composition = {"state": "PROJECTED", "source": "loop outcome + offline_tick_trace/v1",
                   "outcome": (outcome or {}).get("outcome"), "route": route,
                   "candidate_present": candidate is not None, "plan_present": bool(plan_doc),
                   "zone": None if not plan_doc else {"low": plan_doc.get("zone_low"), "high": plan_doc.get("zone_high")},
                   "brain_primary_calls": (trace.get("brain_calls") or {}).get("primary", 0),
                   "final_quote": None if not economics else {
                       "decision": economics.get("decision"), "reference": economics.get("final_entry_reference"),
                       "refusal_reason": economics.get("refusal_reason")}}
    timing = {"state": "PROJECTED", "source": "corpus session window + releases + tick + plan/trigger/final quote",
              "market_open": market_open,
              "settled_cutoff": facts.get("settled_cutoff"),
              "latest_available_at": _iso(latest.available_at) if latest else None,
              "observed_at": decision.isoformat(), "decision_time": decision.isoformat(),
              "plan_capture_at": _iso((plan_doc or {}).get("published_at")),
              "trigger_at": _iso(trigger.get("observed_at")) if trigger and route == "CONDITIONAL_TRIGGER" else None,
              "final_quote_at": _iso(economics.get("final_quote_timestamp"))}
    return {"schema": SCHEMA, "tick": {"ordinal": tick.ordinal, "kind": tick.kind, "decision_time": decision.isoformat()},
            "history_revision": int(history_revision),
            "layers": {"MARKET_FACTS": facts, "CAMPAIGN": campaign, "DELIVERY": delivery, "TOOL": tool,
                       "COMPOSITION": composition, "TIMING": timing}}


def check_projection(p: dict) -> None:
    """Shape guard for a projection read back from evidence."""
    C.require(isinstance(p, dict) and p.get("schema") == SCHEMA, "LAYER_PROJECTION_SCHEMA", "/schema")
    C.require(set(p.get("layers") or {}) == set(LAYERS), "LAYER_PROJECTION_LAYERS", "/layers")
    for name, layer in p["layers"].items():
        C.require(layer.get("state") in ("PROJECTED", "ABSENT") and bool(layer.get("source")),
                  "LAYER_PROJECTION_STATE", f"/layers/{name}")
        C.require(layer["state"] == "PROJECTED" or bool(layer.get("reason")), "LAYER_ABSENT_WITHOUT_REASON",
                  f"/layers/{name}")


def chronology(p: dict, *, stream=None) -> list:
    """Per-projection violations (codes in VIOLATIONS) against its own times and the sealed corpus."""
    out = []
    facts, timing, comp = p["layers"]["MARKET_FACTS"], p["layers"]["TIMING"], p["layers"]["COMPOSITION"]
    decision = _at(timing["decision_time"])
    if facts["state"] == "PROJECTED":
        if _at(facts["settled_cutoff"]) > decision:
            out.append("FACT_AFTER_DECISION")
        if facts.get("temporal_status") == "forming" or facts.get("complete") is False:
            out.append("FORMING_BAR_AS_FACT")
        release = facts.get("release")
        if release and (_at(release["available_at"]) > decision
                        or (release.get("settled_at") and _at(release["settled_at"]) > decision)):
            out.append("FUTURE_EVIDENCE")
        if stream is not None:
            sealed = next((r for r in stream.visible(decision) if r.bar_open == _at(facts["bar_open"])), None)
            if sealed is None or any(_num(facts["bar"][k]) != _num(sealed.bar[k]) for k in ("open", "high", "low", "close")):
                out.append("FACT_NOT_SEALED")
    if timing.get("latest_available_at") and _at(timing["latest_available_at"]) > decision \
            and "FUTURE_EVIDENCE" not in out:
        out.append("FUTURE_EVIDENCE")
    capture, trigger, final = (_at(timing.get(k)) for k in ("plan_capture_at", "trigger_at", "final_quote_at"))
    if trigger and capture and trigger < capture:
        out.append("TRIGGER_BEFORE_CAPTURE")
    if final and trigger and final < trigger:
        out.append("FINAL_QUOTE_BEFORE_TRIGGER")
    quote, zone = comp.get("final_quote") or {}, comp.get("zone") or {}
    if quote.get("decision") == "EXECUTE_AS_AUTHORIZED" and None not in (zone.get("low"), zone.get("high")) and \
            not (_num(zone["low"]) <= _num(quote.get("reference")) <= _num(zone["high"])):
        out.append("FINAL_QUOTE_OUTSIDE_ZONE")
    return out


def sequence(projections: list) -> dict:
    """Cross-tick findings: duplicate cognition cutoffs, missed scans, revisions, restarts."""
    duplicates, gaps, revisions, restarts = [], [], [], []
    seen, last_scan, last = {}, None, None
    for p in projections:
        cutoff = p["layers"]["TIMING"]["settled_cutoff"]
        key = (p["process_lineage_id"], p["history_revision"], cutoff)
        if p["layers"]["COMPOSITION"]["brain_primary_calls"] and cutoff:
            if key in seen:
                duplicates.append({"settled_cutoff": cutoff, "ticks": [seen[key], p["tick"]["ordinal"]]})
            seen[key] = p["tick"]["ordinal"]
        if last is not None:
            if p["process_lineage_id"] != last["process_lineage_id"]:
                restarts.append({"at": p["tick"]["decision_time"], "from": last["process_lineage_id"],
                                 "to": p["process_lineage_id"]})
            if p["history_revision"] != last["history_revision"]:
                revisions.append({"at": p["tick"]["decision_time"], "from": last["history_revision"],
                                  "to": p["history_revision"]})
        if p["tick"]["kind"] == "SCAN" and cutoff:
            if last_scan is not None and _at(cutoff) - _at(last_scan) > BAR:
                gaps.append({"after_cutoff": last_scan, "catch_up_cutoff": cutoff,
                             "missed_bars": int((_at(cutoff) - _at(last_scan)) / BAR) - 1})
            last_scan = cutoff
        last = p
    return {"duplicate_cognition_cutoffs": duplicates, "missed_scans": gaps, "revisions": revisions,
            "restarts": restarts}


def _cell(layer, label, *, expected, observed, state, reason=None, agreement=None, ticks=(), source=None,
          truth_field=None):
    return {"layer": layer, "label_id": label["label_id"], "expected": str(expected), "observed": str(observed),
            "state": state, "agreement": agreement, "reason": reason, "truth_field": truth_field,
            "source_binding": source, "projection_ticks": list(ticks)}


def _in(moment, start, end):
    return start <= moment < end


def score_label(label: dict, projections: list, findings: dict, *, stream=None, tolerance_seconds: int = 0,
                stream_supplied: bool = False) -> list:
    """Six cells for one label. Pure function of projections, findings and the label."""
    w0, w1 = C.instant(label["window"]["start_utc"]), C.instant(label["window"]["end_utc"])
    earliest = C.instant(label["earliest_available_utc"])
    t0 = C.instant(label["recognition_target"]["start_utc"])
    t1 = C.instant(label["recognition_target"]["end_utc"]) + timedelta(seconds=max(0, tolerance_seconds))
    window = [p for p in projections if _in(_at(p["tick"]["decision_time"]), w0, w1)]
    lawful = [p for p in window if _at(p["tick"]["decision_time"]) >= earliest]
    unknown = label["ambiguous"] or label["confidence"] == "UNKNOWN"
    direction = label["dominant_campaign_direction"]
    cells = []
    # MARKET_FACTS against the sealed corpus
    facts = [p for p in window if p["layers"]["MARKET_FACTS"]["state"] == "PROJECTED"]
    if not facts:
        cells.append(_cell("MARKET_FACTS", label, expected="SEALED_SETTLED_FACTS", observed="unavailable",
                           state="UNPROVEN", reason="EVIDENCE_ABSENT:no_settled_projection_in_window",
                           source="snapshot.timeframes.1m.last_candle", truth_field="corpus releases"))
    elif not stream_supplied:
        cells.append(_cell("MARKET_FACTS", label, expected="SEALED_SETTLED_FACTS", observed="unverified",
                           state="UNPROVEN", reason="SEALED_CORPUS_NOT_SUPPLIED", ticks=[p["tick"]["ordinal"] for p in facts],
                           source="snapshot.timeframes.1m.last_candle", truth_field="corpus releases"))
    else:
        bad = [(p["tick"]["ordinal"], code) for p in facts for code in chronology(p, stream=stream)
               if code in ("FACT_AFTER_DECISION", "FUTURE_EVIDENCE", "FORMING_BAR_AS_FACT", "FACT_NOT_SEALED")]
        cells.append(_cell("MARKET_FACTS", label, expected="SEALED_SETTLED_FACTS",
                           observed=bad[0][1] if bad else "CONSISTENT", state="SCORED", agreement=not bad,
                           ticks=[t for t, _ in bad] or [p["tick"]["ordinal"] for p in facts],
                           source="snapshot.timeframes.1m.last_candle", truth_field="corpus releases"))
    # CAMPAIGN
    projected = [p for p in lawful if p["layers"]["CAMPAIGN"]["state"] == "PROJECTED"]
    first = projected[0] if projected else None
    camp = first["layers"]["CAMPAIGN"] if first else None
    source = "scan_participation_authority(scan)"
    if direction == "UNKNOWN" or unknown:
        cells.append(_cell("CAMPAIGN", label, expected=direction, observed=camp["direction"] if camp else "unavailable",
                           state="UNSCORED", reason="ANNOTATION_UNKNOWN", source=source,
                           truth_field="dominant_campaign_direction"))
    elif camp is None:
        cells.append(_cell("CAMPAIGN", label, expected=direction, observed="unavailable", state="UNPROVEN",
                           reason="EVIDENCE_ABSENT:campaign_draw", source=source, truth_field="dominant_campaign_direction"))
    else:
        tick = [first["tick"]["ordinal"]]
        origins = [o for o in label["campaign_origin"] if not o.get("unresolved_reason")]
        evicted = camp.get("history_start") and any(o.get("source_time") and _at(o["source_time"]) < _at(camp["history_start"])
                                                    for o in origins)
        brain = camp.get("brain_direction")
        if evicted:
            cells.append(_cell("CAMPAIGN", label, expected=direction, observed=camp["direction"], state="UNPROVEN",
                               reason="PREFIX_EVICTED", ticks=tick, source=source, truth_field="campaign_origin"))
        elif camp.get("draw_history_revision") is not None and camp["draw_history_revision"] != first["history_revision"]:
            cells.append(_cell("CAMPAIGN", label, expected=direction, observed=camp["direction"], state="UNPROVEN",
                               reason="STALE_DRAW", ticks=tick, source=source, truth_field="dominant_campaign_direction"))
        elif brain in DIRECTIONAL and camp["direction"] in DIRECTIONAL and brain != camp["direction"]:
            cells.append(_cell("CAMPAIGN", label, expected=direction, observed="CONTRADICTORY_JUDGMENT",
                               state="UNPROVEN", reason=f"BRAIN_{brain}_VS_DRAW_{camp['direction']}", ticks=tick,
                               source=source, truth_field="dominant_campaign_direction"))
        else:
            problems = []
            if camp["direction"] != direction:
                problems.append(f"DIRECTION_{camp['direction']}")
            objectives = [o for o in label["campaign_objective"] if not o.get("unresolved_reason")]
            if objectives and not any(o.get("event_id") == camp["objective"]["identity"] or (
                    o.get("event_id") is None and o.get("level") is not None
                    and _num(o["level"]) == _num(camp["objective"]["price"])) for o in objectives):
                problems.append("OBJECTIVE_MISMATCH")
            origin_ids = [o["event_id"] for o in origins if o.get("event_id")]
            if origin_ids and (camp.get("origin") or {}).get("occurrence_id") not in origin_ids:
                problems.append("ORIGIN_MISMATCH")
            cells.append(_cell("CAMPAIGN", label, expected=direction,
                               observed=problems[0] if problems else camp["direction"], state="SCORED",
                               agreement=not problems, ticks=tick, source=source,
                               truth_field="dominant_campaign_direction/campaign_objective/campaign_origin"))
    # DELIVERY
    expected = label["delivery_state"]
    states = [(p["tick"]["ordinal"], p["layers"]["DELIVERY"]) for p in lawful if p["layers"]["DELIVERY"]["state"] == "PROJECTED"]
    source = "snapshot.campaign_lifecycle + snapshot.active_path_state"
    if expected == "UNKNOWN" or unknown:
        cells.append(_cell("DELIVERY", label, expected=expected, observed="n/a", state="UNSCORED",
                           reason="ANNOTATION_UNKNOWN", source=source, truth_field="delivery_state"))
    elif not states:
        cells.append(_cell("DELIVERY", label, expected=expected, observed="unavailable", state="UNPROVEN",
                           reason="EVIDENCE_ABSENT:lifecycle", source=source, truth_field="delivery_state"))
    else:
        mapped = [(t, d["projected_state"]) for t, d in states]
        known = [(t, m) for t, m in mapped if m != "UNKNOWN"]
        reversal = [(t, m) for t, m in known if m in REVERSAL_STATES]
        required = {x["event_id"] for x in label["required_invalidation_evidence"]
                    if x.get("event_id") and not x.get("unresolved_reason")}
        seen_inv = {d.get("last_invalidated") for _, d in states} | {
            p["layers"]["TOOL"].get("invalidation_id") for p in lawful if p["layers"]["TOOL"]["state"] == "PROJECTED"}
        transfer = {x["kind"] for x in label["opposing_transfer_evidence"] if not x.get("unresolved_reason")}
        flags = {f for _, d in states for f in d["transfer_flags"]}
        if not known:
            cells.append(_cell("DELIVERY", label, expected=expected, observed="UNKNOWN_JUDGMENT", state="UNPROVEN",
                               reason="LIFECYCLE_AUTHORITY_UNKNOWN", ticks=[t for t, _ in mapped], source=source,
                               truth_field="delivery_state"))
        elif required and not required <= seen_inv:
            cells.append(_cell("DELIVERY", label, expected=expected, observed="invalidation_not_projected",
                               state="UNPROVEN", reason="REQUIRED_INVALIDATION_EVIDENCE_NOT_PROJECTED",
                               ticks=[t for t, _ in known], source=source, truth_field="required_invalidation_evidence"))
        elif transfer and not transfer <= flags:
            cells.append(_cell("DELIVERY", label, expected=expected, observed="transfer_evidence_not_projected",
                               state="UNPROVEN", reason="OPPOSING_TRANSFER_EVIDENCE_NOT_PROJECTED",
                               ticks=[t for t, _ in known], source=source, truth_field="opposing_transfer_evidence"))
        elif expected in INTACT_STATES:
            # A retracement inside an intact campaign is not a reversal, and is not a miss of one.
            cells.append(_cell("DELIVERY", label, expected=expected,
                               observed="FALSE_REVERSAL" if reversal else known[0][1], state="SCORED",
                               agreement=not reversal and all(m in INTACT_STATES for _, m in known),
                               ticks=[t for t, _ in (reversal or known)], source=source, truth_field="delivery_state"))
        else:
            hit = [(t, m) for t, m in known if m in REVERSAL_STATES and (m == expected or expected == "REVERSAL_DEVELOPING")]
            cells.append(_cell("DELIVERY", label, expected=expected, observed=hit[0][1] if hit else "MISSED_TRANSFER",
                               state="SCORED", agreement=bool(hit), ticks=[t for t, _ in (hit or known)], source=source,
                               truth_field="delivery_state"))
    # TOOL
    fields = {k: label[k] for k in ("playbook_family", "tool_family", "occurrence_id") if label[k]}
    tools = [p for p in lawful if p["layers"]["TOOL"]["state"] == "PROJECTED"]
    source = "loop.active_candidate | loop.active_conditional_plan.candidate"
    if not fields:
        cells.append(_cell("TOOL", label, expected="n/a", observed="n/a", state="UNSCORED",
                           reason="ANNOTATION_ABSENT:playbook_family/tool_family/occurrence_id", source=source,
                           truth_field="playbook_family/tool_family/occurrence_id"))
    elif not tools:
        cells.append(_cell("TOOL", label, expected=fields.get("occurrence_id") or fields, observed="no_tool_selected",
                           state="UNPROVEN", reason="EVIDENCE_ABSENT:no_tool_selected", source=source,
                           truth_field="occurrence_id"))
    else:
        tool, camp = tools[0]["layers"]["TOOL"], tools[0]["layers"]["CAMPAIGN"]
        def holds(expected, observed):
            # production carries tool_family as a list of families; the label names one
            return expected in observed if isinstance(observed, list) else expected == observed
        problems = [f"{name.upper()}_MISMATCH" for name, key in (("playbook_family", "playbook"),
                    ("tool_family", "tool_family"), ("occurrence_id", "occurrence_id"))
                    if name in fields and not holds(fields[name], tool.get(key))]
        if camp["state"] == "PROJECTED" and tool.get("direction") != camp.get("direction"):
            problems.append("OCCURRENCE_OWNERSHIP_MISMATCH")
        cells.append(_cell("TOOL", label, expected=fields.get("occurrence_id") or fields,
                           observed=problems[0] if problems else (tool.get("occurrence_id") or "selected"),
                           state="SCORED", agreement=not problems, ticks=[tools[0]["tick"]["ordinal"]], source=source,
                           truth_field="/".join(fields)))
    # COMPOSITION
    action = label["expected_action"]
    source = "loop outcome + offline_tick_trace/v1"
    composition = [p for p in lawful if p["layers"]["COMPOSITION"]["state"] == "PROJECTED"]
    broken = [(p["tick"]["ordinal"], code) for p in composition for code in chronology(p)
              if code in ("TRIGGER_BEFORE_CAPTURE", "FINAL_QUOTE_BEFORE_TRIGGER", "FINAL_QUOTE_OUTSIDE_ZONE")]
    outcomes = [p["layers"]["COMPOSITION"]["outcome"] for p in composition]
    observed = ("ENTRY" if any(o in ENTRY_OUTCOMES for o in outcomes) else
                "WATCHING" if any(o in WATCHING_OUTCOMES for o in outcomes) else "STAND_DOWN")
    if broken:
        cells.append(_cell("COMPOSITION", label, expected=action, observed=broken[0][1], state="SCORED",
                           agreement=False, ticks=[t for t, _ in broken], source=source, truth_field="expected_action"))
    elif action == "UNKNOWN" or unknown:
        cells.append(_cell("COMPOSITION", label, expected=action, observed=observed, state="UNSCORED",
                           reason="ANNOTATION_UNKNOWN", source=source, truth_field="expected_action"))
    elif not composition:
        cells.append(_cell("COMPOSITION", label, expected=action, observed="unavailable", state="UNPROVEN",
                           reason="EVIDENCE_ABSENT:no_lawful_tick", source=source, truth_field="expected_action"))
    elif observed == "STAND_DOWN" and action != "STAND_DOWN":
        cells.append(_cell("COMPOSITION", label, expected=action, observed="NO_TRADE", state="UNSCORED",
                           reason="NO_TRADE_NEVER_WRONG", source=source, truth_field="expected_action"))
    else:
        agree = observed == action or (action == "WATCHING" and observed == "ENTRY")
        cells.append(_cell("COMPOSITION", label, expected=action, observed=observed, state="SCORED", agreement=agree,
                           ticks=[p["tick"]["ordinal"] for p in composition if p["layers"]["COMPOSITION"]["outcome"]
                                  in (ENTRY_OUTCOMES + WATCHING_OUTCOMES)][:1], source=source,
                           truth_field="expected_action"))
    # TIMING: first lawful matching Draw direction against availability and target
    source = "projection TIMING + CAMPAIGN"
    matching = [p for p in window if p["layers"]["CAMPAIGN"]["state"] == "PROJECTED"
                and p["layers"]["CAMPAIGN"]["direction"] == direction]
    early = [p for p in matching if _at(p["tick"]["decision_time"]) < earliest and _in(_at(p["tick"]["decision_time"]), t0, t1)]
    on_time = [p for p in matching if _at(p["tick"]["decision_time"]) >= earliest and _in(_at(p["tick"]["decision_time"]), t0, t1)]
    late = [p for p in matching if _at(p["tick"]["decision_time"]) >= max(earliest, t1)]
    gap = [g for g in findings["missed_scans"]
           if _at(g["after_cutoff"]) < t1 and _at(g["catch_up_cutoff"]) > t0]
    restart = [r for r in findings["restarts"] if _in(_at(r["at"]), w0, w1)]
    if direction == "UNKNOWN" or unknown:
        cells.append(_cell("TIMING", label, expected="within_target", observed="n/a", state="UNSCORED",
                           reason="ANNOTATION_UNKNOWN", source=source, truth_field="recognition_target"))
    elif early:
        cells.append(_cell("TIMING", label, expected="after_availability", observed="EARLY_BEFORE_AVAILABILITY",
                           state="SCORED", agreement=False, ticks=[early[0]["tick"]["ordinal"]], source=source,
                           truth_field="earliest_available_utc"))
    elif restart:
        cells.append(_cell("TIMING", label, expected="within_target", observed="restart_in_window", state="UNPROVEN",
                           reason="RESTART_IN_WINDOW", source=source, truth_field="window"))
    elif on_time:
        match = on_time[0]
        superseded = [r for r in findings["revisions"] if _at(match["tick"]["decision_time"]) < _at(r["at"]) < t1]
        if superseded:
            cells.append(_cell("TIMING", label, expected="within_target", observed="match_superseded",
                               state="UNPROVEN", reason="MATCH_ON_SUPERSEDED_REVISION",
                               ticks=[match["tick"]["ordinal"]], source=source, truth_field="recognition_target"))
        else:
            cells.append(_cell("TIMING", label, expected="within_target", observed="ON_TIME", state="SCORED",
                               agreement=True, ticks=[match["tick"]["ordinal"]], source=source,
                               truth_field="recognition_target"))
    elif gap:
        cells.append(_cell("TIMING", label, expected="within_target", observed="missed_scan", state="UNPROVEN",
                           reason="MISSED_SCAN_CATCH_UP", source=source, truth_field="recognition_target"))
    elif late:
        cells.append(_cell("TIMING", label, expected="within_target", observed="LATE", state="SCORED", agreement=False,
                           ticks=[late[0]["tick"]["ordinal"]], source=source, truth_field="recognition_target"))
    else:
        cells.append(_cell("TIMING", label, expected="within_target", observed="unavailable", state="UNPROVEN",
                           reason="EVIDENCE_ABSENT:no_matching_projection", source=source,
                           truth_field="recognition_target"))
    return cells


def metrics(cells: list, metric) -> list:
    """One agreement metric per layer: AGREE over SCORED cells; UNSCORED/UNPROVEN counted apart."""
    out = []
    for layer in LAYERS:
        mine = [c for c in cells if c["layer"] == layer]
        scored = [c for c in mine if c["state"] == "SCORED"]
        out.append(metric(METRICS[layer], sum(1 for c in scored if c["agreement"]), len(scored),
                          excluded=sum(1 for c in mine if c["state"] == "UNSCORED"),
                          unproven=sum(1 for c in mine if c["state"] == "UNPROVEN")))
    return out


def table(cells: list) -> list:
    """Per-layer counts with the reasons and source bindings behind every non-scored cell."""
    rows = []
    for layer in LAYERS:
        mine = [c for c in cells if c["layer"] == layer]
        rows.append({"layer": layer, "cells": len(mine),
                     "scored": sum(c["state"] == "SCORED" for c in mine),
                     "agree": sum(bool(c["agreement"]) for c in mine if c["state"] == "SCORED"),
                     "unscored": sum(c["state"] == "UNSCORED" for c in mine),
                     "unproven": sum(c["state"] == "UNPROVEN" for c in mine),
                     "reasons": sorted({c["reason"] for c in mine if c["reason"]}),
                     "sources": sorted({c["source_binding"] for c in mine if c["source_binding"]})})
    return rows
