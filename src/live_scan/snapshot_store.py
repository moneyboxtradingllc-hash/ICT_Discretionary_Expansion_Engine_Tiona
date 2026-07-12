"""
Snapshot persistence for the live scan loop.
Saves compact JSON to data/live_snapshots/ — no raw candles, no readiness verbosity.

DECON-3 — the forensic truth record. Every scan persists the complete
post-runtime story: what the organism saw (core context), believed (brain /
thesis / commander), chose (decision / gate / intent), what blocked it
(block_trace — layer + owner + exact reason), what mutated it (mutation_trace),
what sized it (authority_trace), and what the broker received and returned
(broker_trace). Writes are POST-RUNTIME ONLY: save_snapshot refuses to persist
a scan whose runtime has not resolved (missing decision/gate/execution/
reconciliation blocks) — no partial snapshots.
"""
import os
import json
from datetime import datetime
import pytz

_EASTERN     = pytz.timezone("America/New_York")
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
# Legacy default + test patch-point; LIVE_SNAPSHOTS_DIR (InstanceContext) overrides.
STORE_DIR = os.path.join(_PROJECT_ROOT, "data", "live_snapshots")

# DECON-3 — a forensic record may only be written AFTER the runtime resolved.
# These keys are attached by the scan loop strictly before save_snapshot();
# their absence means the scan died mid-cycle and there is no truth to record.
_REQUIRED_POST_RUNTIME = (
    "decision_authority", "execution_gate", "paper_execution",
    "position_monitor", "trade_reconciliation",
)


def _store_dir() -> str:
    return os.getenv("LIVE_SNAPSHOTS_DIR") or STORE_DIR


# ── DECON-3 — forensic trace builders (pure derivations; no authority) ────────

_NO_BROKER_TRACE = {
    "broker_called": False, "adapter": None, "request": None,
    "response": None, "error": None, "latency_ms": None,
    "not_called_reason": "execution layer not reached",
}


def build_block_trace(snapshot: dict) -> list:
    """Structured veto record: every layer that blocked this scan, with the
    owning layer and its exact reason. Empty list = nothing blocked. Pure."""
    s = snapshot or {}
    trace = []

    def _add(layer, reason, field=None):
        if reason:
            trace.append({"layer": layer, "reason": str(reason)[:200],
                          "field": field})

    risk = s.get("risk") or {}
    for b in risk.get("blocks") or []:
        _add("risk_governor", b, "risk.blocks")

    rp = s.get("regime_permissions") or {}
    if rp.get("enabled") and not rp.get("allowed", True):
        for b in rp.get("blocking_reasons") or ["regime permission blocked"]:
            _add("regime_authority", b, "regime_permissions.blocking_reasons")

    da = s.get("decision_authority") or {}
    for b in da.get("blocking_factors") or []:
        _add("decision_authority", b, "decision_authority.blocking_factors")

    eg = s.get("execution_gate") or {}
    checks = eg.get("authorization_checks") or {}
    for name, passed in checks.items():
        # decision_trade_authorized is False BY CONSTITUTION pre-gate — not a veto
        if not passed and name != "decision_trade_authorized":
            _add("execution_gate", f"check failed: {name}", name)
    if not eg.get("narrative_permits_trade", True):
        _add("narrative_authority", eg.get("narrative_reason"),
             "execution_gate.narrative_permits_trade")
    if not eg.get("council_permits_trade", True):
        veto = (s.get("council") or {}).get("veto") or {}
        _add("council", veto.get("veto_reason") or "council veto",
             "execution_gate.council_permits_trade")
    if not eg.get("no_promoted_rule_block", True):
        fired = ", ".join(f"{f.get('rule_id')}: {f.get('reason')}"
                          for f in eg.get("promoted_rules_fired") or [])
        _add("rule_governance", fired or "promoted rule fired",
             "execution_gate.promoted_rules_fired")

    ab = s.get("adaptive_block") or {}
    if ab.get("blocked"):
        _add("adaptive_live_authority",
             "; ".join(str(r) for r in ab.get("reason") or ["defensive soft veto"]),
             "adaptive_block")

    ps = s.get("position_supremacy") or {}
    if ps.get("block_entries"):
        _add("position_supremacy",
             f"POSITION_STATE_MISMATCH case={ps.get('case')}", "block_entries")

    iscr = s.get("intent_score") or {}
    if iscr.get("gating_applied"):
        _add("intent_score", iscr.get("gating_reason"), "gating_applied")

    pe = s.get("paper_execution") or {}
    if (pe.get("status") or "").lower() in ("skipped", "disabled"):
        _add("execution_engine", pe.get("reason"), "paper_execution.reason")

    return trace


def build_mutation_trace(snapshot: dict) -> dict:
    """Full adaptive mutation chain for this scan. Pure."""
    m = (snapshot or {}).get("adaptive_mutation") or {}
    c = (snapshot or {}).get("adaptive_live_consumption") or {}
    return {
        "original_confidence": m.get("original_confidence"),
        "new_confidence":      m.get("new_confidence"),
        "original_qty":        m.get("original_qty"),
        "new_qty":             m.get("new_qty"),
        "mutation_types":      m.get("mutation_types") or [],
        "mutation_reasoning":  m.get("mutation_reasoning") or [],
        "trade_blocked":       bool(m.get("trade_blocked")),
        "authority_level":     m.get("authority_level"),
        "posture":             m.get("posture"),
        "consumed_live":       {
            "confidence_consumed": c.get("adaptive_confidence_consumed"),
            "size_consumed":       c.get("adaptive_size_consumed"),
            "notes":               c.get("notes") or [],
        },
    }


def build_authority_trace(snapshot: dict) -> dict:
    """Who owns confidence and qty this scan, with original -> final values."""
    s = snapshot or {}
    c = s.get("adaptive_live_consumption") or {}
    pe = s.get("paper_execution") or {}
    conf_orig = c.get("original_live_confidence")
    conf_final = c.get("final_live_confidence")
    qty_orig = c.get("original_live_qty")
    qty_final = c.get("final_live_qty")
    if qty_final is None:
        qty_final = pe.get("qty")
        qty_orig = qty_orig if qty_orig is not None else pe.get("qty")
    return {
        # TIER-2A (2026-07-10) — wrapper confidence_fusion retired; the Brain
        # thesis confidence is witness-only and no numeric confidence gates
        # anything. The ADAPTIVE-6 confidence overlay now has no live target.
        "confidence_owner":    "retired (wrapper confidence_fusion removed;"
                               " no numeric confidence authorizes)",
        "confidence_original": conf_orig,
        "confidence_final":    conf_final,
        "qty_owner":           "paper_execution.order_builder"
                               " (risk budget x multiplier caps; adaptive may lower)",
        "qty_original":        qty_orig,
        "qty_final":           qty_final,
    }


def _brain_sovereignty_record(snapshot: dict) -> dict:
    """THESIS-PERSIST — derived sovereignty verdict, computed at save time on the
    live in-memory snapshot (where brain_thesis/candidate_thesis still exist).
    Observability only; consumers of authority call sovereign_conversion
    themselves. Never raises."""
    try:
        from ai_brain.ecu import sovereign_conversion, healthy_directional_thesis
        sov, sov_detail = sovereign_conversion(snapshot)
        healthy, health_detail = healthy_directional_thesis(snapshot)
        return {
            "sovereign": bool(sov),
            "detail": sov_detail,
            "healthy_directional": bool(healthy),
            "health_detail": health_detail,
        }
    except Exception as exc:  # noqa: BLE001
        return {"sovereign": False, "detail": f"record_error:{type(exc).__name__}",
                "healthy_directional": False, "health_detail": None}


def save_snapshot(snapshot: dict, symbol: str) -> str:
    """
    Persist a compact scan snapshot to data/live_snapshots/.
    Returns the full filepath on success. Raises on I/O failure.

    DECON-3: POST-RUNTIME ONLY — raises ValueError when the runtime has not
    resolved (required layer outputs absent). No partial snapshots.
    """
    missing = [k for k in _REQUIRED_POST_RUNTIME if k not in (snapshot or {})]
    if missing:
        raise ValueError(
            "forensic write refused — runtime incomplete, missing: "
            + ", ".join(missing)
        )

    os.makedirs(_store_dir(), exist_ok=True)

    now_et   = datetime.now(_EASTERN)
    filename = now_et.strftime("%Y%m%d_%H%M%S") + f"_{symbol}.json"
    filepath = os.path.join(_store_dir(), filename)

    tb = snapshot.get("toolbox", {})

    # Strip per-candidate readiness/price_level/trigger_prep verbosity — keep status only
    compact_candidates = [
        {
            "tool":             c.get("tool"),
            "score":            c.get("score"),
            "raw_status":       c.get("raw_status"),
            "effective_status": c.get("effective_status"),
        }
        for c in tb.get("tool_candidates", [])
    ]

    compact = {
        "timestamp":    snapshot.get("timestamp"),
        "symbol":       symbol,
        "session":      snapshot.get("session"),
        "qualification": snapshot.get("qualification"),
        "playbook":     snapshot.get("playbook"),
        "risk": {
            "risk_tier":        snapshot.get("risk", {}).get("risk_tier"),
            "trade_allowed":    snapshot.get("risk", {}).get("trade_allowed"),
            "authority_reason": snapshot.get("risk", {}).get("authority_reason"),
            "blocks":           snapshot.get("risk", {}).get("blocks",       []),
            "restrictions":     snapshot.get("risk", {}).get("restrictions", []),
        },
        "toolbox": {
            "preferred_tool":                  tb.get("preferred_tool"),
            "best_available_raw_status":        tb.get("best_available_raw_status"),
            "best_available_effective_status":  tb.get("best_available_effective_status"),
            "tool_candidates":                  compact_candidates,
        },
        "state_transition":  snapshot.get("state_transition"),
        "setup_lifecycle":   snapshot.get("setup_lifecycle"),
        # Phase NA-1 — narrative authority audit trail
        "narrative_authority": snapshot.get("narrative_authority"),
        "protected_swings":    snapshot.get("protected_swings"),
        # Phase AB-1 — narrative brain (observe-only) compact record
        "ai_brain":            (lambda b: {
            "enabled": b.get("enabled"), "authority": b.get("authority"),
            "source": b.get("source"), "input_degraded": b.get("input_degraded"),
            "output": b.get("output"),
        } if isinstance(b, dict) else None)(snapshot.get("ai_brain") or {}),
        # THESIS-PERSIST (2026-07-09) — the canonical Brain thesis was never
        # persisted (only thesis_state was), so every post-hoc audit saw
        # brain_thesis=None and concluded the Brain never converted — a storage
        # artifact, not reality (the 2026-07-09 ECU investigation). Persist the
        # compact thesis (brain_block excluded — ai_brain.output already carries
        # the full record), the candidate source (healthy-LLM check input), and
        # the derived sovereignty verdict computed on the LIVE in-memory
        # snapshot, so replays can measure sovereignty without reconstruction.
        "brain_thesis":        (lambda t: {
            k: t.get(k) for k in (
                "owner", "source", "direction", "forbidden_direction",
                "opportunity", "opportunity_type", "playbook_family",
                "tool_family", "confidence",
            )
        } if isinstance(t, dict) else None)(snapshot.get("brain_thesis")),
        "candidate_thesis_source": (lambda c: c.get("source")
                                    if isinstance(c, dict) else None
                                    )(snapshot.get("candidate_thesis")),
        "brain_sovereignty":   _brain_sovereignty_record(snapshot),
        # TIER-2A (2026-07-10) — ai_divergence / ai_debate no longer produced
        "decision_authority": snapshot.get("decision_authority"),
        "execution_gate":    snapshot.get("execution_gate"),
        "trade_intent":      snapshot.get("trade_intent"),
        "intent_score":      snapshot.get("intent_score"),
        "intent_archive":    snapshot.get("intent_archive"),
        "paper_execution": {
            "status":          snapshot.get("paper_execution", {}).get("status"),
            "reason":          snapshot.get("paper_execution", {}).get("reason"),
            "order_summary":   snapshot.get("paper_execution", {}).get("order_summary"),
            "alpaca_order_id": snapshot.get("paper_execution", {}).get("alpaca_order_id"),
            "trade_id":        snapshot.get("paper_execution", {}).get("trade_id"),
        },
        "position_monitor": {
            "enabled":               snapshot.get("position_monitor", {}).get("enabled"),
            "has_open_position":     snapshot.get("position_monitor", {}).get("has_open_position"),
            "status":                snapshot.get("position_monitor", {}).get("status"),
            "side":                  snapshot.get("position_monitor", {}).get("side"),
            "qty":                   snapshot.get("position_monitor", {}).get("qty"),
            "avg_entry_price":       snapshot.get("position_monitor", {}).get("avg_entry_price"),
            "current_price":         snapshot.get("position_monitor", {}).get("current_price"),
            "stop_reference":        snapshot.get("position_monitor", {}).get("stop_reference"),
            "stop_distance":         snapshot.get("position_monitor", {}).get("stop_distance"),
            "unrealized_pnl":        snapshot.get("position_monitor", {}).get("unrealized_pnl"),
            "linked_trade_id":       snapshot.get("position_monitor", {}).get("linked_trade_id"),
            "exit_already_submitted": snapshot.get("position_monitor", {}).get("exit_already_submitted"),
            "warnings":              snapshot.get("position_monitor", {}).get("warnings", []),
        },
        "stop_enforcer": {
            "enabled":       snapshot.get("stop_enforcer", {}).get("enabled"),
            "stop_evaluated": snapshot.get("stop_enforcer", {}).get("stop_evaluated"),
            "stop_breached": snapshot.get("stop_enforcer", {}).get("stop_breached"),
            "breach_reason": snapshot.get("stop_enforcer", {}).get("breach_reason"),
            "exit_submitted": snapshot.get("stop_enforcer", {}).get("exit_submitted"),
            "exit_order_id": snapshot.get("stop_enforcer", {}).get("exit_order_id"),
            "exit_reason":   snapshot.get("stop_enforcer", {}).get("exit_reason"),
            "action_taken":  snapshot.get("stop_enforcer", {}).get("action_taken"),
            "warnings":      snapshot.get("stop_enforcer", {}).get("warnings", []),
        },
        "experience_summary": {
            "experience_enabled":   snapshot.get("experience_summary", {}).get("experience_enabled"),
            "authority_level":      snapshot.get("experience_summary", {}).get("authority_level"),
            "sample_size":          snapshot.get("experience_summary", {}).get("sample_size"),
            "historical_matches":   snapshot.get("experience_summary", {}).get("historical_matches"),
            "win_rate":             snapshot.get("experience_summary", {}).get("win_rate"),
            "loss_rate":            snapshot.get("experience_summary", {}).get("loss_rate"),
            "average_r":            snapshot.get("experience_summary", {}).get("average_r"),
            "best_session":         snapshot.get("experience_summary", {}).get("best_session"),
            "worst_session":        snapshot.get("experience_summary", {}).get("worst_session"),
            "best_playbook":        snapshot.get("experience_summary", {}).get("best_playbook"),
            "worst_playbook":       snapshot.get("experience_summary", {}).get("worst_playbook"),
            "confidence_modifier":  snapshot.get("experience_summary", {}).get("confidence_modifier", 0),
            "linked_trade_count":   snapshot.get("experience_summary", {}).get("linked_trade_count",  0),   # Phase 3C
            "closed_trade_count":   snapshot.get("experience_summary", {}).get("closed_trade_count",  0),   # Phase 3C
            "open_trade_count":     snapshot.get("experience_summary", {}).get("open_trade_count",    0),   # Phase 3C
            "unlinked_intent_count": snapshot.get("experience_summary", {}).get("unlinked_intent_count", 0), # Phase 3C
            "linkage_quality":      snapshot.get("experience_summary", {}).get("linkage_quality",    "none"), # Phase 3C
            "notes":                snapshot.get("experience_summary", {}).get("notes", []),
        },
        "experience_report": snapshot.get("experience_report"),
        "experience_correlation": {
            "enabled":                         snapshot.get("experience_correlation", {}).get("enabled"),
            "authority_level":                  snapshot.get("experience_correlation", {}).get("authority_level"),
            "sample_size":                      snapshot.get("experience_correlation", {}).get("sample_size"),
            "confidence_modifier":              snapshot.get("experience_correlation", {}).get("confidence_modifier", 0),
            "correlation_confidence":           snapshot.get("experience_correlation", {}).get("correlation_confidence"),
            "strongest_positive_correlations":  snapshot.get("experience_correlation", {}).get("strongest_positive_correlations", []),
            "strongest_negative_correlations":  snapshot.get("experience_correlation", {}).get("strongest_negative_correlations", []),
            "warnings":                         snapshot.get("experience_correlation", {}).get("warnings", []),
        },
        "broker_stop": {
            "enabled":       snapshot.get("broker_stop", {}).get("enabled"),
            "status":        snapshot.get("broker_stop", {}).get("status"),
            "stop_order_id": snapshot.get("broker_stop", {}).get("stop_order_id"),
            "stop_price":    snapshot.get("broker_stop", {}).get("stop_price"),
        },
        "trade_reconciliation": {
            "trade_found":     snapshot.get("trade_reconciliation", {}).get("trade_found"),
            "status":          snapshot.get("trade_reconciliation", {}).get("status"),
            "trade_id":        snapshot.get("trade_reconciliation", {}).get("trade_id"),
            "realized_pnl":    snapshot.get("trade_reconciliation", {}).get("realized_pnl"),
            "realized_r":      snapshot.get("trade_reconciliation", {}).get("realized_r"),
            "holding_minutes": snapshot.get("trade_reconciliation", {}).get("holding_minutes"),
            "entry_price":     snapshot.get("trade_reconciliation", {}).get("entry_price"),
            "exit_price":      snapshot.get("trade_reconciliation", {}).get("exit_price"),
            "close_reason":    snapshot.get("trade_reconciliation", {}).get("close_reason"),
            "journal_updated": snapshot.get("trade_reconciliation", {}).get("journal_updated"),
            "warnings":        snapshot.get("trade_reconciliation", {}).get("warnings", []),
        },
        "paper_activation_plan": {
            "activation_mode":     snapshot.get("paper_activation_plan", {}).get("activation_mode"),
            "armed":               snapshot.get("paper_activation_plan", {}).get("armed"),
            "symbol":              snapshot.get("paper_activation_plan", {}).get("symbol"),
            "max_trades":          snapshot.get("paper_activation_plan", {}).get("max_trades"),
            "risk_dollars":        snapshot.get("paper_activation_plan", {}).get("risk_dollars"),
            "requirements_passed": snapshot.get("paper_activation_plan", {}).get("requirements_passed"),
            "requirements":        snapshot.get("paper_activation_plan", {}).get("requirements", {}),
            "blocking_issues":     snapshot.get("paper_activation_plan", {}).get("blocking_issues", []),
            "reason":              snapshot.get("paper_activation_plan", {}).get("reason"),
        },
        "paper_activation": snapshot.get("paper_activation"),
        "operational_readiness": {
            "ready":           snapshot.get("operational_readiness", {}).get("ready"),
            "score":           snapshot.get("operational_readiness", {}).get("score"),
            "checks":          snapshot.get("operational_readiness", {}).get("checks", {}),
            "warnings":        snapshot.get("operational_readiness", {}).get("warnings", []),
            "blocking_issues": snapshot.get("operational_readiness", {}).get("blocking_issues", []),
        },
        "activation_controller": snapshot.get("activation_controller"),
        "market_regime": {
            "enabled":       snapshot.get("market_regime", {}).get("enabled"),
            "regime_label":  snapshot.get("market_regime", {}).get("regime_label",  "unknown"),
            "regime_family": snapshot.get("market_regime", {}).get("regime_family", "unknown"),
            "confidence":    snapshot.get("market_regime", {}).get("confidence",    0),
            "volatility_state": snapshot.get("market_regime", {}).get("volatility_state", "unknown"),
            "expansion_state":  snapshot.get("market_regime", {}).get("expansion_state",  "unknown"),
            "authority_level":  "observe_only",
            "confidence_modifier": 0,
        },
        "ai_feedback_summary": {
            "enabled":              snapshot.get("ai_feedback_summary", {}).get("enabled"),
            "authority_level":      "observe_only",
            "confidence_modifier":  0,
            "sample_size":          snapshot.get("ai_feedback_summary", {}).get("sample_size", 0),
            "ai_helpful_count":     snapshot.get("ai_feedback_summary", {}).get("ai_helpful_count", 0),
            "ai_harmful_count":     snapshot.get("ai_feedback_summary", {}).get("ai_harmful_count", 0),
            "ai_helpful_rate":      snapshot.get("ai_feedback_summary", {}).get("ai_helpful_rate"),
            "ai_harmful_rate":      snapshot.get("ai_feedback_summary", {}).get("ai_harmful_rate"),
            "agreement_win_rate":   snapshot.get("ai_feedback_summary", {}).get("agreement_win_rate"),
            "disagreement_win_rate": snapshot.get("ai_feedback_summary", {}).get("disagreement_win_rate"),
            "best_ai_condition":    snapshot.get("ai_feedback_summary", {}).get("best_ai_condition"),
            "worst_ai_condition":   snapshot.get("ai_feedback_summary", {}).get("worst_ai_condition"),
        },
        "performance_dashboard": {
            "enabled":             snapshot.get("performance_dashboard", {}).get("enabled"),
            "authority_level":     "observe_only",
            "confidence_modifier": 0,
            "performance_quality": snapshot.get("performance_dashboard", {}).get("performance_quality", "none"),
            "sample_size":         snapshot.get("performance_dashboard", {}).get("sample_size",    0),
            "win_rate":            snapshot.get("performance_dashboard", {}).get("win_rate"),
            "average_r":           snapshot.get("performance_dashboard", {}).get("average_r"),
            "best_regime":         snapshot.get("performance_dashboard", {}).get("best_regime"),
            "worst_regime":        snapshot.get("performance_dashboard", {}).get("worst_regime"),
            "best_playbook":       snapshot.get("performance_dashboard", {}).get("best_playbook"),
            "worst_playbook":      snapshot.get("performance_dashboard", {}).get("worst_playbook"),
            "best_session":        snapshot.get("performance_dashboard", {}).get("best_session"),
            "most_common_failure": snapshot.get("performance_dashboard", {}).get("most_common_failure"),
            "memory_quality":      snapshot.get("performance_dashboard", {}).get("memory_quality",  "none"),
        },
        "memory_search": {
            "enabled":             snapshot.get("memory_search", {}).get("enabled"),
            "authority_level":     "observe_only",
            "confidence_modifier": 0,
            "match_count":         snapshot.get("memory_search", {}).get("match_count",        0),
            "closed_match_count":  snapshot.get("memory_search", {}).get("closed_match_count", 0),
            "best_similarity":     snapshot.get("memory_search", {}).get("best_similarity",    0.0),
            "similar_win_rate":    snapshot.get("memory_search", {}).get("similar_win_rate"),
            "similar_average_r":   snapshot.get("memory_search", {}).get("similar_average_r"),
            "memory_quality":      snapshot.get("memory_search", {}).get("memory_quality",     "none"),
            "notes":               snapshot.get("memory_search", {}).get("notes",              []),
        },
        # TIER-2A (2026-07-10) — ai_discretionary / confidence_fusion retired
        "ai_context": {
            "market_narrative": snapshot.get("ai_context", {}).get("market_narrative"),
            "confidence_score": snapshot.get("ai_context", {}).get("confidence_score"),
            "confidence_tier":  snapshot.get("ai_context", {}).get("confidence_tier"),
            "summary":          snapshot.get("ai_context", {}).get("summary"),
        },

        # ── DECON-3 — A. core context completions ─────────────────────────────
        "volatility_states": {
            tf: (snapshot.get("volatility", {}).get(tf, {}) or {}).get("state")
            for tf in ("15m", "5m", "3m", "1m")
        },
        "structure_alignment": (snapshot.get("structure", {}) or {}).get("alignment"),

        # ── DECON-3 — B/C. decision + authority stack completions ─────────────
        "regime_permissions": (lambda rp: {
            "enabled":                 rp.get("enabled"),
            "allowed":                 rp.get("allowed"),
            "permission_status":       rp.get("permission_status"),
            "risk_multiplier_cap":     rp.get("risk_multiplier_cap"),
            "required_trigger_status": rp.get("required_trigger_status"),
            "min_setup_age_scans":     rp.get("min_setup_age_scans"),
            "management_profile":      rp.get("management_profile"),
            "blocking_reasons":        rp.get("blocking_reasons", []),
        })(snapshot.get("regime_permissions") or {}),
        "rule_governance": (lambda rg: {
            "enabled":     rg.get("enabled"),
            "fired":       rg.get("fired", []),
            "opportunity": rg.get("opportunity"),
            "event_count": len(rg.get("events") or []),
            "warning":     rg.get("warning"),
        })(snapshot.get("rule_governance") or {}),
        "council": (lambda co: {
            "enabled":         co.get("enabled"),
            "authority_level": co.get("authority_level"),
            "votes":           [{"member": m.get("member"), "vote": m.get("vote"),
                                 "confidence": m.get("confidence")}
                                for m in co.get("members") or []],
            "dominant_position":  (co.get("report") or {}).get("dominant_position"),
            "consensus_strength": (co.get("report") or {}).get("consensus_strength"),
            "veto":            co.get("veto"),
        })(snapshot.get("council") or {}),
        "thesis_lifecycle": (lambda tl: {
            "enabled":       tl.get("enabled"),
            "mode":          tl.get("mode"),
            "action":        tl.get("action"),
            "active_thesis": (lambda at: {
                "thesis_id":   at.get("thesis_id"),
                "thesis_type": at.get("thesis_type"),
                "direction":   at.get("direction"),
                "status":      at.get("status"),
                "confidence":  at.get("confidence"),
                "age_scans":   at.get("age_scans"),
            } if at else None)(tl.get("active_thesis")),
        })(snapshot.get("thesis_lifecycle") or {}),
        "thesis_state":       snapshot.get("thesis_state"),
        "position_supremacy": (lambda ps: {
            "mismatch":      ps.get("mismatch"),
            "case":          ps.get("case"),
            "block_entries": ps.get("block_entries"),
            "emergency":     ps.get("emergency"),
            "actions":       ps.get("actions", []),
        })(snapshot.get("position_supremacy") or {}),
        "trade_management": (lambda tm: {
            "action":              tm.get("action"),
            "reason":              tm.get("reason"),
            "details":             tm.get("details"),
            "management_profile":  tm.get("management_profile"),
            "unrealized_r":        tm.get("unrealized_r"),
            "invariant_violation": tm.get("invariant_violation"),
        })(snapshot.get("trade_management") or {}),
        "thesis_monitor": (lambda thm: {
            "would_exit":  thm.get("would_exit"),
            "reason":      thm.get("reason"),
            "r_at_signal": thm.get("r_at_signal"),
            "profile":     thm.get("profile"),
        })(snapshot.get("thesis_monitor") or {}),
        "pending_entry_order": snapshot.get("pending_entry_order"),
        "eod_authority":       snapshot.get("eod_authority"),
        "scar_writer":         snapshot.get("scar_writer"),

        # ── DECON-3 — D. adaptive stack (verbatim; these blocks are small) ────
        "adaptive_policy":           snapshot.get("adaptive_policy"),
        "adaptive_mutation": (lambda m: {
            k: v for k, v in m.items() if k != "mutated_candidate"
        } if isinstance(m, dict) else None)(snapshot.get("adaptive_mutation")),
        "adaptive_live_authority":   snapshot.get("adaptive_live_authority"),
        "adaptive_block":            snapshot.get("adaptive_block"),
        "adaptive_confidence":       snapshot.get("adaptive_confidence"),
        "adaptive_size":             snapshot.get("adaptive_size"),
        "adaptive_live_consumption": snapshot.get("adaptive_live_consumption"),

        # ── DECON-3 — E. commander stack (observe-only verdict, compact) ──────
        "market_commander": (lambda mc: {
            "authority_level": mc.get("authority_level"),
            "source":          mc.get("source"),
            "final_state":     mc.get("final_state"),
            "environment": (lambda e: {
                "family":         e.get("family"),
                "type":           e.get("type"),
                "confidence":     e.get("confidence"),
                "completeness":   e.get("completeness"),
                "conflict_index": e.get("conflict_index"),
            })(mc.get("environment") or {}),
            "participation": (lambda p: {
                "decision":   p.get("decision"),
                "confidence": p.get("confidence"),
                "reason":     p.get("reason"),
                "gates":      [{"name": g.get("name"), "passed": g.get("passed")}
                               for g in (p.get("gates") or [])
                               if isinstance(g, dict)],
            })(mc.get("participation") or {}),
            "contradictions": (mc.get("consistency") or {}).get("contradictions", []),
        })(snapshot.get("market_commander") or {}),

        # ── SUPPRESS-1 — shadow suppression telemetry (observe-only) ─────────
        "suppression": snapshot.get("suppression"),

        # ── META-1 — organ self-observation (observe-only) ───────────────────
        "meta_awareness": snapshot.get("meta_awareness"),

        # ── CAPITAL-1 — capital intelligence (contract/lock/permit only) ─────
        "capital_intelligence": snapshot.get("capital_intelligence"),

        # ── HTF-MEM-1 — higher-timeframe memory (context only) ───────────────
        "htf_memory": snapshot.get("htf_memory"),

        # ── DECON-3 — F. execution stack + unified truth traces ───────────────
        "broker_trace": (snapshot.get("paper_execution", {}) or {}).get(
            "broker_trace") or dict(_NO_BROKER_TRACE),
        "block_trace":     build_block_trace(snapshot),
        "mutation_trace":  build_mutation_trace(snapshot),
        "authority_trace": build_authority_trace(snapshot),
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(compact, f, indent=2, default=str)

    return filepath
