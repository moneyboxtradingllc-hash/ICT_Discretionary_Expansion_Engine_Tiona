"""
Phase AB-4 — Wrapper vs Brain divergence logging (observe-only).

Both AI paths observe identical market conditions every scan:
  - legacy wrapper: ai_discretionary (ai_direction / ai_confidence) + debate
  - new brain:      ai_brain.output (narrative_direction / phase_confidence)

This module compares them, classifies disagreement, and persists a divergence
record for AB-4 evaluation. It changes NOTHING about trading — pure measurement.
Never raises.
"""
import json
import os
from datetime import datetime

import pytz

_EASTERN = pytz.timezone("America/New_York")


def _dir() -> str:
    return os.path.join(os.getenv("AI_BRAIN_DIR", os.path.join("data", "ai_brain")),
                        "divergence")


def _norm(d) -> str:
    d = (d or "neutral")
    return d.lower() if isinstance(d, str) else "neutral"


def compute_divergence(snapshot: dict, symbol: str, persist: bool = True) -> dict:
    """Compare wrapper vs brain conclusions. Observe-only. Never raises."""
    try:
        wrapper = snapshot.get("ai_discretionary", {}) or {}
        debate  = (snapshot.get("ai_debate", {}) or {}).get("final_verdict", {}) or {}
        brain_blk = snapshot.get("ai_brain", {}) or {}
        brain = (brain_blk.get("output") or {}) if brain_blk.get("enabled") else {}

        if not brain:
            return {"enabled": False, "reason": "ai_brain disabled or empty"}

        w_dir  = _norm(wrapper.get("ai_direction"))
        w_conf = int(wrapper.get("ai_confidence") or 0)
        b_dir  = _norm(brain.get("narrative_direction"))
        b_conf = int(brain.get("phase_confidence") or 0)

        classes = []
        if w_dir != b_dir:
            classes.append("direction_disagreement")
        if abs(w_conf - b_conf) >= 20:
            classes.append("confidence_disagreement")
        # narrative: wrapper market_story vs brain narrative_phase/story
        w_narr = _norm(wrapper.get("market_story"))[:1]   # presence proxy
        if (brain.get("narrative_phase") and
                brain.get("narrative_phase") not in (wrapper.get("market_story") or "")):
            classes.append("narrative_disagreement")
        # playbook family
        w_stance = _norm(debate.get("recommended_stance"))
        b_action = _norm(brain.get("current_action"))
        if w_stance.replace("prepare_", "") != b_action.replace("prepare_", "").replace("avoid_", "") \
                and "direction_disagreement" not in classes:
            classes.append("playbook_disagreement")
        # liquidity (brain has a draw read, wrapper has none)
        if brain.get("active_draw"):
            classes.append("liquidity_disagreement") if not wrapper else None

        diverged = bool(classes)
        result = {
            "enabled": True,
            "diverged": diverged,
            "classes": [c for c in classes if c],
            "wrapper_direction": w_dir,
            "wrapper_confidence": w_conf,
            "brain_direction": b_dir,
            "brain_confidence": b_conf,
            "wrapper_reasoning": (wrapper.get("market_story") or "")[:200],
            "brain_reasoning": (brain.get("dominant_reasoning") or brain.get("reason") or "")[:200],
            "brain_direction_provenance": brain.get("direction_provenance", {}),
            "brain_analogs_used": len(brain.get("memory_matches", []) or []),
        }
        if persist and diverged:
            result["log_path"] = _persist(snapshot, symbol, result)
        return result
    except Exception as exc:  # noqa: BLE001
        return {"enabled": True, "diverged": False, "error": f"divergence error: {exc}"}


def _persist(snapshot, symbol, result) -> "str | None":
    try:
        d = _dir()
        os.makedirs(d, exist_ok=True)
        ts = (snapshot.get("timestamp") or
              datetime.now(_EASTERN).strftime("%Y%m%dT%H%M%S")).replace(":", "").replace("+", "_")
        path = os.path.join(d, f"divergence_{symbol}_{ts}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, default=str)
        return path
    except Exception:  # noqa: BLE001
        return None
