"""
Adaptive Learning — Phase 2B: Aggressive Adaptive Interpretation.

The point of adaptive learning is EXPERIENCE, not a confidence vote. This layer
teaches the Brain to compare the CURRENT setup against historical success/failure
profiles and produce an experience-based read:

  "The current setup resembles prior winners because displacement and delivery
   are stronger than the failed analog cluster."

Cognitive INPUT only — no mechanical authority. Deterministic; no LLM; never
raises.
"""
from __future__ import annotations

# Canonical ICT success / failure condition vocabularies (the profiles the Brain
# reasons against). The CURRENT setup is scored against these.
SUCCESS_CONDITIONS = [
    "strong displacement", "PO3 aligned", "delivery expanding",
    "not lunch session", "clear liquidity draw",
]
FAILURE_CONDITIONS = [
    "weak delivery", "mixed PO3", "lunch session",
    "low magnitude displacement", "repeated stopout after reclaim",
]


def _read_current_profile(snapshot: dict) -> dict:
    """Extract the boolean setup features used for profile matching. All reads are
    defensive; missing evidence degrades to the cautious (failure-leaning) side."""
    sess = (snapshot.get("session") or "").lower()
    is_lunch = "lunch" in sess

    exp = snapshot.get("expansion", {}) or {}
    strong_disp = False
    any_ungated = False
    for e in exp.values():
        if not isinstance(e, dict):
            continue
        if not e.get("magnitude_gated", False):
            any_ungated = True
        if (e.get("state") in ("healthy_expansion", "mature_expansion")
                and not e.get("magnitude_gated", False)):
            strong_disp = True
    low_magnitude = not any_ungated          # everything magnitude-gated → sub-floor

    align = (snapshot.get("po3", {}) or {}).get("alignment")
    po3_aligned = align in ("full_distribution_alignment",
                            "manipulation_to_distribution", "accumulation_building")
    po3_mixed = (align in ("mixed", "no_clear_alignment", None))

    sc = snapshot.get("shared_context", {}) or {}
    delivery = sc.get("delivery_state")
    delivery_expanding = bool(delivery) and delivery not in ("unknown", "neutral") \
        and not sc.get("exhaustion_present", False)

    na = snapshot.get("narrative_authority", {}) or {}
    draw = na.get("active_liquidity_draw") or sc.get("active_liquidity_draw")
    clear_draw = bool(draw)

    return {
        "is_lunch": is_lunch, "strong_disp": strong_disp, "low_magnitude": low_magnitude,
        "po3_aligned": po3_aligned, "po3_mixed": po3_mixed,
        "delivery_expanding": delivery_expanding, "clear_draw": clear_draw,
    }


def _matched_success(p):
    out = []
    if p["strong_disp"]:        out.append("strong displacement")
    if p["po3_aligned"]:        out.append("PO3 aligned")
    if p["delivery_expanding"]: out.append("delivery expanding")
    if not p["is_lunch"]:       out.append("not lunch session")
    if p["clear_draw"]:         out.append("clear liquidity draw")
    return out


def _matched_failure(p, tags):
    out = []
    if not p["delivery_expanding"]:                 out.append("weak delivery")
    if p["po3_mixed"]:                              out.append("mixed PO3")
    if p["is_lunch"]:                              out.append("lunch session")
    if p["low_magnitude"] or not p["strong_disp"]: out.append("low magnitude displacement")
    if "prior_success_requires_stronger_delivery" in tags:
        out.append("repeated stopout after reclaim")
    return out


def build_adaptive_interpretation(learning_signal, friction_report,
                                  current_snapshot: dict) -> dict:
    """Experience-based comparison of the current setup vs historical profiles.
    Cognitive input only. Never raises."""
    try:
        snap = current_snapshot or {}
        n = getattr(learning_signal, "sample_size", 0) if learning_signal else 0
        wr = getattr(learning_signal, "win_rate", 0.0) if learning_signal else 0.0
        ar = getattr(learning_signal, "avg_r", 0.0) if learning_signal else 0.0
        tags = list(getattr(learning_signal, "warning_tags", []) or []) if learning_signal else []
        pb = getattr(learning_signal, "playbook_bias", None) if learning_signal else None
        flevel = getattr(friction_report, "friction_level", 0) if friction_report else 0

        regime = (snap.get("market_regime", {}) or {}).get("regime_label") or "unknown"
        session = (snap.get("session") or "unknown")
        playbook = pb or (snap.get("playbook", {}) or {}).get("selected_playbook") or "unknown"
        setup_family = f"{playbook}/{regime}/{session}"

        p = _read_current_profile(snap)
        matched_success = _matched_success(p)
        matched_failure = _matched_failure(p, tags)
        matches_success = len(matched_success) >= 3
        matches_failure = len(matched_failure) >= 3

        # ── interpretation bias ──
        if n == 0:
            bias = "insufficient_history"
        elif flevel == 3:
            bias = "historically_opposed"
        elif flevel in (1, 2):
            bias = "historically_conflicted"
        elif wr >= 0.55 or ar > 0:
            bias = "historically_supportive"
        else:
            bias = "historically_conflicted"

        # ── confidence posture ──
        if bias == "insufficient_history":
            posture = "stable"
        elif flevel == 3:
            posture = "challenged"
        elif bias == "historically_supportive" and matches_success and not matches_failure:
            posture = "reinforced"
        elif flevel in (1, 2) or matches_failure:
            posture = "fragile"
        else:
            posture = "stable"

        # ── experience-based read ──
        if bias == "insufficient_history":
            read = "Insufficient historical sample to form an experience-based read."
        elif matches_success and not matches_failure:
            read = ("The current setup resembles prior WINNERS — present strengths ("
                    + ", ".join(matched_success) + ") are stronger than the failed "
                    "analog cluster, so the prior failure pattern may not apply.")
        elif matches_failure and not matches_success:
            read = ("The current setup resembles prior LOSERS — historical failures "
                    "clustered around (" + ", ".join(matched_failure) + ") in the same "
                    f"{setup_family} family, and the current setup shares them.")
        else:
            read = ("Mixed resemblance: current setup shows winner traits ("
                    + (", ".join(matched_success) or "none") + ") and loser traits ("
                    + (", ".join(matched_failure) or "none") + ") — outcome is contingent.")

        # ── fragility flags ──
        fragility = []
        if matches_failure:
            fragility.append("matches_failure_profile")
        if p["is_lunch"]:
            fragility.append("lunch_session")
        if p["low_magnitude"] or not p["strong_disp"]:
            fragility.append("magnitude_gated_displacement")
        if p["po3_mixed"]:
            fragility.append("mixed_po3")
        if not p["delivery_expanding"]:
            fragility.append("weak_delivery")
        if "prior_success_requires_stronger_delivery" in tags:
            fragility.append("high_mae_history")
        if ar < 0 and n > 0:
            fragility.append("negative_expectancy")

        return {
            "historical_setup_family": setup_family,
            "historical_success_conditions": SUCCESS_CONDITIONS,
            "historical_failure_conditions": FAILURE_CONDITIONS,
            "current_matches_success_profile": matches_success,
            "current_matches_failure_profile": matches_failure,
            "matched_success_conditions": matched_success,
            "matched_failure_conditions": matched_failure,
            "experience_based_read": read,
            "interpretation_bias": bias,
            "confidence_posture": posture,
            "fragility_flags": fragility,
            "authority_level": "observe_only",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "historical_setup_family": "unknown",
            "historical_success_conditions": SUCCESS_CONDITIONS,
            "historical_failure_conditions": FAILURE_CONDITIONS,
            "current_matches_success_profile": False,
            "current_matches_failure_profile": False,
            "experience_based_read": f"interpretation_error:{type(exc).__name__}",
            "interpretation_bias": "insufficient_history",
            "confidence_posture": "stable",
            "fragility_flags": [],
            "authority_level": "observe_only",
        }
