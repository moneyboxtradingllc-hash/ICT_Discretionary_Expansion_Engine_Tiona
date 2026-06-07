"""
Phase 3A/3B/3C — Experience Summary.
Builds the OBSERVE_ONLY experience intelligence block for each scan snapshot.

SAFETY CONSTRAINTS (immutable — never remove or weaken):
  authority_level      = "observe_only"    ← constant, never changes
  confidence_modifier  = 0                 ← always 0, never non-zero

This module NEVER modifies:
  decision_authority, execution_gate, paper_execution,
  position_monitor, stop_enforcer, intent_score, ai_confidence,
  paper_activation, or any downstream execution variable.
"""

from experience_intelligence.experience_query        import (
    load_completed_trades, load_all_intent_records, find_similar_setups,
)
from experience_intelligence.experience_metrics      import compute_metrics
from experience_intelligence.experience_correlation  import (
    build_correlation, correlation_confidence as _corr_confidence,
)
from experience_intelligence.intent_trade_linker     import link_intents_to_trades
from experience_intelligence.linked_outcome_metrics  import compute_linked_metrics

_AUTHORITY   = "observe_only"
_EXP_ENABLED = True


def build_experience_summary(snapshot: dict, symbol: str) -> dict:
    """
    Phase 3A entry point — builds experience intelligence summary.
    Never raises. Returns safe default on any error.
    confidence_modifier is ALWAYS 0.
    """
    try:
        return _build(snapshot, symbol)
    except Exception as exc:
        return _safe_default([f"experience build error: {exc}"])


def _build(snapshot: dict, symbol: str) -> dict:
    completed_trades = load_completed_trades(symbol, days=30)
    all_intents      = load_all_intent_records(symbol, days=30)

    # Phase 3C: run linkage on intents ↔ trades
    links            = link_intents_to_trades(all_intents, completed_trades)
    linked_outcomes  = compute_linked_metrics(links, all_intents, completed_trades)

    linked_count     = sum(1 for lk in links if lk["linked"])
    unlinked_count   = len(all_intents) - linked_count
    linkage_qual     = _linkage_quality(linked_count, len(all_intents))

    # Phase 3A/3C: metrics now enriched with linked outcomes for MFE/MAE
    metrics          = compute_metrics(completed_trades, linked_outcomes)
    similar_setups   = find_similar_setups(snapshot, symbol, days=30)
    historical_matches = len(similar_setups)
    n                = metrics["sample_size"]

    # Phase 3B/3C: correlation with linked outcomes
    corr             = build_correlation(completed_trades, linked_outcomes)
    corr_n           = corr.get("sample_size", 0)
    corr_available   = corr_n > 0
    corr_conf        = _corr_confidence(corr_n) if corr_available else "none"

    notes: list[str] = []
    if n == 0:
        notes.append("Insufficient sample size — awaiting first completed trade")
    elif n < 20:
        notes.append(f"Developing: {n} trade(s) — minimum 20 for rate metrics")
    elif n < 50:
        notes.append(f"Developing: {n} trades — minimum 50 for meaningful statistics")
    else:
        notes.append(f"Meaningful: {n} trades available for pattern analysis")

    if historical_matches > 0:
        notes.append(f"{historical_matches} historically similar setup(s) found this session")

    return {
        "experience_enabled":     _EXP_ENABLED,
        "authority_level":        _AUTHORITY,
        "sample_size":            n,
        "historical_matches":     historical_matches,
        "win_rate":               metrics["win_rate"],
        "loss_rate":              metrics["loss_rate"],
        "average_r":              metrics["average_r"],
        "average_hold_time":      metrics["average_hold_time"],
        "average_mfe":            metrics["average_mfe"],
        "average_mae":            metrics["average_mae"],
        "best_session":           metrics["best_session"],
        "worst_session":          metrics["worst_session"],
        "best_playbook":          metrics["best_playbook"],
        "worst_playbook":         metrics["worst_playbook"],
        "confidence_modifier":    0,               # ALWAYS 0 — OBSERVE_ONLY
        "correlation_available":  corr_available,  # Phase 3B
        "correlation_confidence": corr_conf,       # Phase 3B
        "linked_trade_count":     metrics.get("linked_trade_count",  0),  # Phase 3C
        "closed_trade_count":     metrics.get("closed_trade_count",  0),  # Phase 3C
        "open_trade_count":       metrics.get("open_trade_count",    0),  # Phase 3C
        "unlinked_intent_count":  unlinked_count,                          # Phase 3C
        "linkage_quality":        linkage_qual,                            # Phase 3C
        "notes":                  notes,
    }


def _linkage_quality(linked: int, total: int) -> str:
    if total == 0 or linked == 0:
        return "none"
    ratio = linked / total
    if ratio >= 0.8:
        return "high"
    if ratio >= 0.5:
        return "medium"
    return "low"


def _safe_default(notes: list[str]) -> dict:
    return {
        "experience_enabled":     _EXP_ENABLED,
        "authority_level":        _AUTHORITY,
        "sample_size":            0,
        "historical_matches":     0,
        "win_rate":               None,
        "loss_rate":              None,
        "average_r":              None,
        "average_hold_time":      None,
        "average_mfe":            None,
        "average_mae":            None,
        "best_session":           None,
        "worst_session":          None,
        "best_playbook":          None,
        "worst_playbook":         None,
        "confidence_modifier":    0,
        "correlation_available":  False,   # Phase 3B
        "correlation_confidence": "none",  # Phase 3B
        "linked_trade_count":     0,       # Phase 3C
        "closed_trade_count":     0,       # Phase 3C
        "open_trade_count":       0,       # Phase 3C
        "unlinked_intent_count":  0,       # Phase 3C
        "linkage_quality":        "none",  # Phase 3C
        "notes":                  notes,
    }
