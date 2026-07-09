"""
REPLAY-2 — canonical per-scan pipeline stage vector (2026-07-09).

One flat, ordered projection of a scan's decision pipeline. It is the unit of
divergence for every replay comparison: two runs differ at the FIRST stage whose
fields differ, and that stage names an owner file — divergence is attributed to
code, never to vibes.

Also extracts the same vector from STORED live snapshots (the ground-truth
baseline). Stored snapshots persist decisions, not raw inputs, so perception
fields are marked non-comparable there (see PERCEPTION_FIELDS).
"""
import json

# Ordered stages; each field lives in exactly one stage.
STAGES = (
    "perception", "narrative", "brain", "qualification", "playbook",
    "toolbox", "trigger", "decision", "gate", "intent",
)

STAGE_OWNER = {
    "perception":    "volatility/expansion_detector.py + volatility_classifier.py + structure/po3_engine.py",
    "narrative":     "ai_layer/narrative_builder.py",
    "brain":         "ai_brain/ecu.py + ai_brain/narrative_brain.py",
    "qualification": "qualification/trade_qualification_engine.py",
    "playbook":      "playbooks/playbook_classifier.py",
    "toolbox":       "toolbox/toolbox_engine.py",
    "trigger":       "toolbox/entry_trigger_prep.py",
    "decision":      "decision_authority/decision_engine.py",
    "gate":          "execution_gate/execution_gate.py",
    "intent":        "trade_intent/intent_builder.py",
}

# Fields only reproducible from raw candles — absent from stored live snapshots.
PERCEPTION_FIELDS = ("expansion_5m", "expansion_15m", "volatility_5m",
                     "volatility_15m", "po3_alignment")

# ai_context fields the snapshot store TRIMS (it persists only market_narrative /
# confidence_score / confidence_tier / summary) — never comparable vs stored.
STORED_TRIMMED_FIELDS = ("market_state", "directional_bias")

# brain_thesis fields — persisted only from THESIS-PERSIST (723151b) onward;
# non-comparable for sessions stored before it.
BRAIN_FIELDS = ("brain_direction", "brain_source", "brain_playbook_family",
                "brain_sovereign")

# DECISION-level calibration set: fields that are (a) persisted by the store and
# (b) revision-stable DECISIONS rather than telemetry/reason text. Ground-truth
# calibration compares these; enriched text (disqualifier reasons, gate blocker
# wording) evolves across revisions and would count code-comment changes as
# behavioral divergence.
CALIBRATION_FIELDS = (
    "market_narrative",
    "qual_status", "qual_score",
    "playbook_selected", "playbook_direction",
    "preferred_tool", "tool_raw_status",
    "trigger_status",
    "decision",
    "would_authorize",
    "intent_created", "intent_type",
)

_FIELD_STAGE = {}  # filled below by _field()


def _field(stage: str, name: str):
    _FIELD_STAGE[name] = stage
    return name


_SCHEMA = (
    _field("perception", "expansion_5m"), _field("perception", "expansion_15m"),
    _field("perception", "volatility_5m"), _field("perception", "volatility_15m"),
    _field("perception", "po3_alignment"),
    _field("narrative", "market_narrative"), _field("narrative", "market_state"),
    _field("narrative", "directional_bias"),
    _field("brain", "brain_direction"), _field("brain", "brain_source"),
    _field("brain", "brain_playbook_family"), _field("brain", "brain_sovereign"),
    _field("qualification", "qual_status"), _field("qualification", "qual_score"),
    _field("qualification", "qual_disqualifier"),
    _field("playbook", "playbook_selected"), _field("playbook", "playbook_direction"),
    _field("toolbox", "preferred_tool"), _field("toolbox", "tool_raw_status"),
    _field("trigger", "trigger_status"), _field("trigger", "execution_ready"),
    _field("decision", "decision"),
    _field("gate", "would_authorize"), _field("gate", "gate_blockers"),
    _field("intent", "intent_created"), _field("intent", "intent_type"),
)


def _preferred_candidate(snapshot: dict) -> dict:
    tb = snapshot.get("toolbox") or {}
    pref = tb.get("preferred_tool") or ""
    for c in tb.get("tool_candidates") or []:
        if c.get("tool") == pref:
            return c
    return {}


def _sovereign(snapshot: dict):
    # Prefer the persisted derived verdict (THESIS-PERSIST); fall back to live
    # computation on in-memory snapshots.
    bs = snapshot.get("brain_sovereignty")
    if isinstance(bs, dict):
        return bool(bs.get("sovereign"))
    try:
        from ai_brain.ecu import sovereign_conversion
        return bool(sovereign_conversion(snapshot)[0])
    except Exception:  # noqa: BLE001
        return None


def build_stage_trace(snapshot: dict) -> dict:
    """Project a snapshot (live, stored, or replayed) onto the canonical vector.
    Missing blocks become None — never raises."""
    s = snapshot or {}
    exp = s.get("expansion") or {}
    vol = s.get("volatility") or {}
    po3 = s.get("po3") or {}
    ai = s.get("ai_context") or {}
    bt = s.get("brain_thesis") or {}
    q = s.get("qualification") or {}
    pb = s.get("playbook") or {}
    tb = s.get("toolbox") or {}
    cand = _preferred_candidate(s)
    tp = cand.get("trigger_prep") or {}
    da = s.get("decision_authority") or {}
    g = s.get("execution_gate") or {}
    ti = s.get("trade_intent") or {}

    def _tf_state(block, tf):
        d = block.get(tf)
        return d.get("state") if isinstance(d, dict) else None

    return {
        "timestamp": s.get("timestamp"),
        "expansion_5m": _tf_state(exp, "5m"),
        "expansion_15m": _tf_state(exp, "15m"),
        "volatility_5m": _tf_state(vol, "5m"),
        "volatility_15m": _tf_state(vol, "15m"),
        "po3_alignment": po3.get("alignment"),
        "market_narrative": ai.get("market_narrative"),
        "market_state": ai.get("market_state"),
        "directional_bias": ai.get("directional_bias"),
        "brain_direction": bt.get("direction"),
        "brain_source": bt.get("source"),
        "brain_playbook_family": bt.get("playbook_family"),
        "brain_sovereign": _sovereign(s),
        "qual_status": q.get("status"),
        "qual_score": q.get("opportunity_score"),
        "qual_disqualifier": q.get("disqualifier_reason"),
        "playbook_selected": pb.get("selected_playbook"),
        "playbook_direction": pb.get("direction"),
        "preferred_tool": tb.get("preferred_tool"),
        "tool_raw_status": tb.get("best_available_raw_status"),
        "trigger_status": tp.get("raw_trigger_status") or ti.get("trigger_status"),
        "execution_ready": tp.get("execution_ready"),
        "decision": da.get("decision"),
        "would_authorize": g.get("would_authorize_if_enabled"),
        "gate_blockers": tuple(g.get("blocking_factors") or []),
        "intent_created": ti.get("intent_created"),
        "intent_type": ti.get("intent_type"),
    }


def trace_from_stored(path: str) -> dict:
    """Stage trace from a stored live snapshot JSON (the ground-truth baseline)."""
    with open(path, encoding="utf-8") as fh:
        return build_stage_trace(json.load(fh))


def first_divergence(a: dict, b: dict, skip_fields=()) -> "dict | None":
    """First stage-ordered field where two traces differ.
    Returns {stage, field, a, b, owner} or None when identical. skip_fields
    lets a caller exclude non-comparable fields (e.g. PERCEPTION_FIELDS when
    comparing against a stored snapshot)."""
    for name in _SCHEMA:
        if name in skip_fields:
            continue
        va, vb = (a or {}).get(name), (b or {}).get(name)
        if va != vb:
            stage = _FIELD_STAGE[name]
            return {"stage": stage, "field": name, "a": va, "b": vb,
                    "owner": STAGE_OWNER[stage]}
    return None
