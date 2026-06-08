"""
Snapshot persistence for the live scan loop.
Saves compact JSON to data/live_snapshots/ — no raw candles, no readiness verbosity.
"""
import os
import json
from datetime import datetime
import pytz

_EASTERN     = pytz.timezone("America/New_York")
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
STORE_DIR = os.path.join(_PROJECT_ROOT, "data", "live_snapshots")


def save_snapshot(snapshot: dict, symbol: str) -> str:
    """
    Persist a compact scan snapshot to data/live_snapshots/.
    Returns the full filepath on success. Raises on I/O failure.
    """
    os.makedirs(STORE_DIR, exist_ok=True)

    now_et   = datetime.now(_EASTERN)
    filename = now_et.strftime("%Y%m%d_%H%M%S") + f"_{symbol}.json"
    filepath = os.path.join(STORE_DIR, filename)

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
        "ai_debate":         snapshot.get("ai_debate"),
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
        "ai_discretionary": snapshot.get("ai_discretionary"),
        "confidence_fusion": snapshot.get("confidence_fusion"),
        "ai_context": {
            "market_narrative": snapshot.get("ai_context", {}).get("market_narrative"),
            "confidence_score": snapshot.get("ai_context", {}).get("confidence_score"),
            "confidence_tier":  snapshot.get("ai_context", {}).get("confidence_tier"),
            "summary":          snapshot.get("ai_context", {}).get("summary"),
        },
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(compact, f, indent=2, default=str)

    return filepath
