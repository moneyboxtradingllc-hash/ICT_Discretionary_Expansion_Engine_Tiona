"""
Phase 5D — Performance Report.
Interprets the dashboard into human-readable qualitative findings.
OBSERVE_ONLY — no decision logic, no execution influence.
"""

_STRENGTH_WR_THRESHOLD  = 60.0
_WEAKNESS_WR_THRESHOLD  = 40.0
_MIN_DIM_SAMPLE         = 3


def build_performance_report(dashboard: dict) -> dict:
    """
    Build qualitative performance report from dashboard dict.
    Never raises.
    """
    try:
        return _build(dashboard or {})
    except Exception:
        return _safe_report()


def _build(d: dict) -> dict:
    closed  = d.get("closed_trades", 0)
    quality = _quality_label(closed)
    wr      = d.get("win_rate")
    avg_r   = d.get("average_r")

    headline: list[str] = []
    strengths: list[str] = []
    weaknesses: list[str] = []
    warnings:   list[str] = list(d.get("warnings") or [])

    if closed == 0:
        headline.append("No closed trades available for analysis.")
        return _report(quality, closed, headline, strengths, weaknesses, warnings)

    # Overall metrics
    if wr is not None and closed >= 5:
        headline.append(f"Win rate of {wr:.1f}% over {closed} closed trades.")
    if avg_r is not None and closed >= 5:
        sign = "+" if avg_r >= 0 else ""
        headline.append(f"Average R of {sign}{avg_r:.2f} per trade.")

    # Best/worst regime
    regime_m = d.get("regime_metrics") or {}
    best_r   = d.get("best_regime")
    worst_r  = d.get("worst_regime")
    if best_r and regime_m.get(best_r):
        rm = regime_m[best_r]
        if rm["win_rate"] >= _STRENGTH_WR_THRESHOLD:
            strengths.append(
                f"Strong in {best_r} regime: {rm['win_rate']:.0f}% WR "
                f"({rm['sample_size']} trades)."
            )
    if worst_r and regime_m.get(worst_r):
        rm = regime_m[worst_r]
        if rm["win_rate"] <= _WEAKNESS_WR_THRESHOLD:
            weaknesses.append(
                f"Weak in {worst_r} regime: {rm['win_rate']:.0f}% WR "
                f"({rm['sample_size']} trades)."
            )

    # Best/worst playbook
    pb_m     = d.get("playbook_metrics") or {}
    best_pb  = d.get("best_playbook")
    worst_pb = d.get("worst_playbook")
    if best_pb and pb_m.get(best_pb):
        pm = pb_m[best_pb]
        if pm["win_rate"] >= _STRENGTH_WR_THRESHOLD:
            strengths.append(
                f"{best_pb} playbook: {pm['win_rate']:.0f}% WR "
                f"({pm['sample_size']} trades)."
            )
    if worst_pb and pb_m.get(worst_pb):
        pm = pb_m[worst_pb]
        if pm["win_rate"] <= _WEAKNESS_WR_THRESHOLD:
            weaknesses.append(
                f"{worst_pb} playbook: {pm['win_rate']:.0f}% WR "
                f"({pm['sample_size']} trades)."
            )

    # Best/worst session
    sess_m   = d.get("session_metrics") or {}
    best_s   = d.get("best_session")
    worst_s  = d.get("worst_session")
    if best_s and sess_m.get(best_s):
        sm = sess_m[best_s]
        if sm["win_rate"] >= _STRENGTH_WR_THRESHOLD:
            strengths.append(
                f"Strong in {best_s} session: {sm['win_rate']:.0f}% WR "
                f"({sm['sample_size']} trades)."
            )
    if worst_s and sess_m.get(worst_s):
        sm = sess_m[worst_s]
        if sm["win_rate"] <= _WEAKNESS_WR_THRESHOLD:
            weaknesses.append(
                f"Weak in {worst_s} session: {sm['win_rate']:.0f}% WR "
                f"({sm['sample_size']} trades)."
            )

    # Most common failure
    failure = d.get("most_common_failure")
    if failure and failure != "unknown":
        weaknesses.append(f"Most common failure pattern: {failure.replace('_', ' ')}.")

    # AI feedback summary
    ai_helpful = d.get("ai_helpful_rate")
    ai_correct = d.get("ai_correct_rate")
    if ai_helpful is not None:
        if ai_helpful >= 60:
            strengths.append(f"AI has been helpful in {ai_helpful:.0f}% of scored trades.")
        elif ai_helpful <= 40:
            weaknesses.append(f"AI has been harmful or neutral in {100 - ai_helpful:.0f}% of scored trades.")

    # Memory quality
    mem_q = d.get("memory_quality", "none")
    if mem_q == "none":
        headline.append("Memory database is empty — no similar historical setups available.")
    elif mem_q in ("thin", "developing"):
        headline.append(f"Memory database is {mem_q} — building historical references.")
    elif mem_q == "useful":
        headline.append("Memory database contains useful historical references.")

    if not headline:
        headline.append(f"{closed} closed trades recorded. Insufficient sample for deep analysis.")

    return _report(quality, closed, headline, strengths, weaknesses, warnings)


def _quality_label(closed: int) -> str:
    if closed == 0:
        return "none"
    if closed < 25:
        return "limited"
    if closed < 100:
        return "developing"
    return "meaningful"


def _report(
    quality: str,
    sample_size: int,
    headline: list[str],
    strengths: list[str],
    weaknesses: list[str],
    warnings: list[str],
) -> dict:
    return {
        "performance_quality": quality,
        "sample_size":         sample_size,
        "headline_findings":   headline,
        "strengths":           strengths,
        "weaknesses":          weaknesses,
        "warnings":            warnings,
    }


def _safe_report() -> dict:
    return {
        "performance_quality": "none",
        "sample_size":         0,
        "headline_findings":   ["Report generation failed."],
        "strengths":           [],
        "weaknesses":          [],
        "warnings":            [],
    }
