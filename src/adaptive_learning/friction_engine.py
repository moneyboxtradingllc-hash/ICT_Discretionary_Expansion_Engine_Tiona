"""
Adaptive Learning — Phase 2A: Adaptive Friction Engine.

Adaptive Learning gives the Brain EXPERIENCE; Adaptive Friction gives it
ACCOUNTABILITY. This engine converts a LearningSignal (historical scar analysis)
into a structured *historical objection* the Brain must answer when the past
disagrees with the present.

It is a RISK-COMMITTEE voice, not an executor. authority_level = observe_only.
Friction may CHALLENGE the Brain; it may not execute, block, alter confidence
mechanically, override risk, change size, or change direction. Deterministic; no
LLM; never raises.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

FRICTION_LABELS = {0: "none", 1: "mild", 2: "meaningful", 3: "severe"}

# Warning tags that constitute a "serious" objection.
SEVERE_TAGS = {
    "negative_historical_expectancy",
    "playbook_underperformed_in_current_regime",
    "prior_success_requires_stronger_delivery",
    "similar_setups_failed_during_lunch",
}

_REBUTTAL_QUESTIONS = [
    "What is history objecting to?",
    "Is the objection valid given current evidence?",
    "What current evidence overrides or confirms the objection?",
    "What would invalidate the current thesis?",
    "Should conviction remain, be mentally downgraded, or be treated as fragile?",
]


@dataclass
class FrictionReport:
    friction_level: int = 0
    friction_label: str = "none"
    historical_objection: str = ""
    objection_strength: int = 0          # 0-100
    objection_reasons: list = field(default_factory=list)
    required_rebuttal: bool = False
    rebuttal_questions: list = field(default_factory=list)
    supportive_memory_summary: str = ""
    conflicting_memory_summary: str = ""
    risk_committee_note: str = ""
    authority_level: str = "observe_only"


def friction_to_dict(report: FrictionReport) -> dict:
    return asdict(report)


# ── helpers ───────────────────────────────────────────────────────────────────

def _sig(signal):
    if signal is None:
        return {"n": 0, "wr": 0.0, "ar": 0.0, "fr": 0.0, "tags": [],
                "sup": [], "conf": [], "pb": None}
    return {
        "n": signal.sample_size, "wr": signal.win_rate, "ar": signal.avg_r,
        "fr": signal.failure_rate, "tags": list(signal.warning_tags),
        "sup": list(signal.supporting_evidence),
        "conf": list(signal.conflicting_evidence),
        "pb": signal.playbook_bias,
    }


def _norm_dir(d):
    if not d:
        return None
    d = str(d).lower()
    if d.startswith(("bull", "long")):
        return "bullish"
    if d.startswith(("bear", "short")):
        return "bearish"
    return None


def _current_direction(snapshot, brain_thesis):
    if brain_thesis:
        d = _norm_dir(brain_thesis.get("direction") if isinstance(brain_thesis, dict) else None)
        if d:
            return d
    na = snapshot.get("narrative_authority", {}) or {}
    pb = snapshot.get("playbook", {}) or {}
    ql = snapshot.get("qualification", {}) or {}
    sc = snapshot.get("shared_context", {}) or {}
    for c in (na.get("narrative_direction"), pb.get("direction"),
              ql.get("direction"), sc.get("delivery_state")):
        d = _norm_dir(c)
        if d:
            return d
    return None


def _classify(s, direction_conflict):
    n, wr, ar, tags = s["n"], s["wr"], s["ar"], s["tags"]
    severe = [t for t in tags if t in SEVERE_TAGS]

    if n == 0:
        return 0, ["no historical analogs to object with"], severe

    # ── Level 3 (severe) ──
    l3 = []
    if wr < 0.30 and n >= 15:
        l3.append(f"win_rate {wr:.0%} over {n} samples (<30%)")
    if ar <= -0.75 and n >= 15:
        l3.append(f"avg_r {ar:+.2f} over {n} samples (<=-0.75R)")
    if len(severe) >= 2:
        l3.append(f"multiple severe warning tags: {severe}")
    if "similar_setups_failed_during_lunch" in tags and "negative_historical_expectancy" in tags:
        l3.append("repeated lunch failure + negative expectancy")
    if direction_conflict:
        l3.append("historical analogs directly conflict with thesis direction")
    if l3:
        return 3, l3, severe

    # ── Level 2 (meaningful) ──
    l2 = []
    if wr < 0.40 and n >= 10:
        l2.append(f"win_rate {wr:.0%} over {n} samples (<40%)")
    if ar < 0 and n >= 10:
        l2.append(f"negative expectancy avg_r {ar:+.2f} over {n} samples")
    if "playbook_underperformed_in_current_regime" in tags:
        l2.append("playbook underperformed in the current regime")
    if "prior_success_requires_stronger_delivery" in tags:
        l2.append("prior success required stronger delivery (high MAE risk)")
    if l2:
        return 2, l2, severe

    # ── Level 1 (mild) ──
    l1 = []
    if n < 10:
        l1.append(f"weak historical sample (n={n})")
    if "insufficient_sample_size" in tags:
        l1.append("insufficient sample size")
    if "mixed_historical_outcomes" in tags:
        l1.append("mixed historical outcomes")
    if severe:
        l1.append(f"warning tag present: {severe}")
    if l1:
        return 1, l1, severe

    return 0, ["sufficient support, positive expectancy, no serious warnings"], severe


def _objection_strength(level, s, severe):
    base = {0: 5, 1: 30, 2: 60, 3: 85}[level]
    if level >= 2:
        base += len(severe) * 4
        if s["wr"] < 0.5:
            base += int((0.5 - s["wr"]) * 40)
    return max(0, min(100, base))


# ── public API ────────────────────────────────────────────────────────────────

def build_friction_report(learning_signal, current_snapshot,
                          brain_thesis=None) -> FrictionReport:
    """Convert a LearningSignal into a historical objection. Never raises."""
    try:
        s = _sig(learning_signal)
        snap = current_snapshot or {}
        direction = _current_direction(snap, brain_thesis)
        # A direction conflict = a thesis direction exists and most same-direction
        # historical analogs FAILED in this context (failure-dominant cluster).
        direction_conflict = bool(direction) and s["n"] >= 10 and s["fr"] >= 0.65

        level, reasons, severe = _classify(s, direction_conflict)
        label = FRICTION_LABELS[level]
        strength = _objection_strength(level, s, severe)
        required = level >= 2

        if level == 0:
            objection = ("No material historical objection — comparable setups "
                         "showed acceptable outcomes." if s["n"]
                         else "No historical analogs available to object with.")
        else:
            objection = (f"History objects (level {level}/{label}): {s['n']} "
                         f"comparable setups, {s['wr']:.0%} win, avg {s['ar']:+.2f}R. "
                         + "; ".join(reasons[:3]))

        sup = (f"{len(s['sup'])} supportive analog(s)"
               + (": " + "; ".join(s["sup"][:2]) if s["sup"] else ""))
        conf = (f"{len(s['conf'])} conflicting analog(s)"
                + (": " + "; ".join(s["conf"][:2]) if s["conf"] else ""))

        committee = {
            0: "Committee: clear — no material objection.",
            1: "Committee: minor caution noted; proceed with awareness.",
            2: "Committee: meaningful objection — rebuttal required before conviction.",
            3: "Committee: thesis contested — treat as fragile unless current "
               "evidence materially differs from the failed analog cluster.",
        }[level]

        return FrictionReport(
            friction_level=level,
            friction_label=label,
            historical_objection=objection,
            objection_strength=strength,
            objection_reasons=reasons,
            required_rebuttal=required,
            rebuttal_questions=(_REBUTTAL_QUESTIONS if required else []),
            supportive_memory_summary=sup,
            conflicting_memory_summary=conf,
            risk_committee_note=committee,
            authority_level="observe_only",
        )
    except Exception as exc:  # noqa: BLE001
        return FrictionReport(historical_objection=f"friction_error:{type(exc).__name__}",
                              risk_committee_note="Committee: error — no objection formed.")
