"""
Phase 5E — Recommendation Rules.
Deterministic rule set for generating evidence-backed recommendations.
OBSERVE_ONLY — no decision logic, no execution influence.
All rules are transparent. No ML. No hidden weighting.
"""

_MIN_TOTAL_CLOSED      = 25    # minimum closed trades for any recommendation
_MIN_DIM_SAMPLES       = 10    # minimum trades per dimension bucket
_HIGH_WR               = 75.0  # win rate threshold for high severity positive
_STRONG_WR             = 60.0  # win rate threshold for moderate positive
_WEAK_WR               = 40.0  # win rate threshold for moderate negative
_VERY_WEAK_WR          = 30.0  # win rate threshold for high severity negative
_AI_EDGE_THRESHOLD     = 15.0  # min gap between agreement/disagreement WR for AI rec
_AI_HELPFUL_THRESHOLD  = 65.0  # min helpful_rate for positive AI rec
_STATUS                = "human_review_required"


def check_all_rules(context: dict) -> tuple[list[dict], list[str]]:
    """
    Run all recommendation rules against the context.
    Returns (recommendations, notes). Never raises.
    """
    try:
        return _run(context)
    except Exception as exc:
        return [], [f"rule evaluation failed (non-blocking): {exc}"]


def _run(context: dict) -> tuple[list[dict], list[str]]:
    dashboard = context.get("dashboard") or {}
    notes: list[str] = []

    closed = dashboard.get("closed_trades", 0)
    if closed < _MIN_TOTAL_CLOSED:
        notes.append(
            f"Insufficient evidence for recommendations "
            f"({closed} closed trades, need {_MIN_TOTAL_CLOSED}+)."
        )
        return [], notes

    recs: list[dict] = []
    recs.extend(_regime_rules(dashboard))
    recs.extend(_playbook_rules(dashboard))
    recs.extend(_ai_rules(context))
    recs.extend(_memory_rules(context))

    # Sort: high → moderate → low
    recs.sort(key=lambda r: _severity_rank(r.get("severity", "low")), reverse=True)

    if not recs:
        notes.append("No significant patterns detected with current sample size.")

    return recs, notes


# ── Regime Rules ──────────────────────────────────────────────────────────────

def _regime_rules(dashboard: dict) -> list[dict]:
    recs: list[dict] = []
    regime_m   = dashboard.get("regime_metrics")   or {}
    best_r     = dashboard.get("best_regime")
    worst_r    = dashboard.get("worst_regime")

    # Negative: worst regime underperforming
    if worst_r and regime_m.get(worst_r):
        rm = regime_m[worst_r]
        wr = rm["win_rate"]
        n  = rm["sample_size"]
        if n >= _MIN_DIM_SAMPLES and wr <= _WEAK_WR:
            sev = "high" if wr <= _VERY_WEAK_WR else "moderate"
            recs.append(_rec(
                rtype="regime",
                severity=sev,
                finding=f"{worst_r.replace('_', ' ').title()} regime underperforming",
                evidence=f"{wr:.0f}% WR over {n} trades",
                recommendation=f"Consider reducing participation in {worst_r.replace('_',' ')} conditions",
            ))

    # Positive: best regime outperforming
    if best_r and regime_m.get(best_r):
        rm = regime_m[best_r]
        wr = rm["win_rate"]
        n  = rm["sample_size"]
        if n >= _MIN_DIM_SAMPLES and wr >= _STRONG_WR:
            sev = "moderate" if wr >= _HIGH_WR else "low"
            recs.append(_rec(
                rtype="regime",
                severity=sev,
                finding=f"{best_r.replace('_', ' ').title()} regime outperforming",
                evidence=f"{wr:.0f}% WR over {n} trades",
                recommendation=f"Consider prioritizing {best_r.replace('_',' ')} regime setups",
            ))

    return recs


# ── Playbook Rules ────────────────────────────────────────────────────────────

def _playbook_rules(dashboard: dict) -> list[dict]:
    recs: list[dict] = []
    pb_m       = dashboard.get("playbook_metrics") or {}
    best_pb    = dashboard.get("best_playbook")
    worst_pb   = dashboard.get("worst_playbook")

    # Positive: best playbook
    if best_pb and pb_m.get(best_pb):
        pm = pb_m[best_pb]
        wr = pm["win_rate"]
        n  = pm["sample_size"]
        if n >= _MIN_DIM_SAMPLES and wr >= _STRONG_WR:
            sev = "moderate" if wr >= _HIGH_WR else "low"
            pb_label = best_pb.replace("_", " ").title()
            recs.append(_rec(
                rtype="playbook",
                severity=sev,
                finding=f"{pb_label} is the strongest playbook",
                evidence=f"{wr:.0f}% WR over {n} trades",
                recommendation=f"Consider prioritizing {pb_label} when multiple setups qualify",
            ))

    # Negative: worst playbook
    if worst_pb and pb_m.get(worst_pb):
        pm = pb_m[worst_pb]
        wr = pm["win_rate"]
        n  = pm["sample_size"]
        if n >= _MIN_DIM_SAMPLES and wr <= _WEAK_WR:
            sev = "high" if wr <= _VERY_WEAK_WR else "moderate"
            pb_label = worst_pb.replace("_", " ").title()
            recs.append(_rec(
                rtype="playbook",
                severity=sev,
                finding=f"{pb_label} is the weakest playbook",
                evidence=f"{wr:.0f}% WR over {n} trades",
                recommendation=f"Consider reviewing {pb_label} setup criteria",
            ))

    return recs


# ── AI Rules ──────────────────────────────────────────────────────────────────

def _ai_rules(context: dict) -> list[dict]:
    recs: list[dict] = []
    ai_fb   = context.get("ai_feedback") or {}
    dash    = context.get("dashboard")   or {}

    agree_wr  = ai_fb.get("agreement_win_rate")
    disagr_wr = ai_fb.get("disagreement_win_rate")
    helpful   = dash.get("ai_helpful_rate") or ai_fb.get("ai_helpful_rate")
    sample    = ai_fb.get("sample_size", 0)

    if sample < _MIN_DIM_SAMPLES:
        return recs

    # AI agreement vs disagreement edge
    if agree_wr is not None and disagr_wr is not None:
        gap = agree_wr - disagr_wr
        if abs(gap) >= _AI_EDGE_THRESHOLD:
            if gap > 0:
                recs.append(_rec(
                    rtype="ai",
                    severity="low",
                    finding="AI agreement outperforms disagreement",
                    evidence=f"{agree_wr:.0f}% WR (agree) vs {disagr_wr:.0f}% WR (disagree)",
                    recommendation="Consider shadow-testing AI agreement filters",
                ))
            else:
                recs.append(_rec(
                    rtype="ai",
                    severity="low",
                    finding="AI disagreement outperforms agreement",
                    evidence=f"{disagr_wr:.0f}% WR (disagree) vs {agree_wr:.0f}% WR (agree)",
                    recommendation="Review AI discretionary layer calibration",
                ))

    # High AI helpful rate
    if helpful is not None and helpful >= _AI_HELPFUL_THRESHOLD:
        recs.append(_rec(
            rtype="ai",
            severity="low",
            finding="AI has been consistently helpful",
            evidence=f"AI helpful in {helpful:.0f}% of scored trades",
            recommendation="AI feedback layer is performing well; continue monitoring",
        ))

    return recs


# ── Memory Rules ──────────────────────────────────────────────────────────────

def _memory_rules(context: dict) -> list[dict]:
    recs: list[dict] = []
    ms = context.get("memory_search") or {}

    quality  = ms.get("memory_quality", "none")
    wr       = ms.get("similar_win_rate")
    n        = ms.get("closed_match_count", 0)

    if quality == "useful" and n >= _MIN_DIM_SAMPLES:
        if wr is not None:
            recs.append(_rec(
                rtype="memory",
                severity="low",
                finding="Memory database contains useful historical references",
                evidence=f"{wr:.0f}% WR over {n} similar closed setups",
                recommendation="Consider future memory-confidence experiments when sample matures",
            ))
        else:
            recs.append(_rec(
                rtype="memory",
                severity="low",
                finding="Memory database has reached useful volume",
                evidence=f"{n} closed similar setups available",
                recommendation="Memory layer ready for deeper analysis",
            ))

    return recs


# ── Helpers ───────────────────────────────────────────────────────────────────

def _rec(
    rtype: str,
    severity: str,
    finding: str,
    evidence: str,
    recommendation: str,
) -> dict:
    return {
        "type":              rtype,
        "severity":          severity,
        "finding":           finding,
        "evidence":          evidence,
        "recommendation":    recommendation,
        "status":            _STATUS,
        "authority_level":   "observe_only",
        "confidence_modifier": 0,
    }


def _severity_rank(severity: str) -> int:
    return {"high": 3, "moderate": 2, "low": 1}.get(severity, 0)
