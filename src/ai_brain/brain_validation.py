"""
Phase AI-BRAIN-H1 — LLM Brain hardening: normalize, validate, repair-detect.

Pipeline (observe-only, never raises):
  normalize_output()  — deterministic fixes that must NOT cause fallback:
      * enum synonyms -> valid narrative_phase
      * tool/playbook family coherence vs direction (incoherent -> neutralized)
      * forbidden_direction coherence
      * strip unsupported analog citations
    Returns (normalized, notes[]) where notes record every change.
  needs_repair()      — failures that DO warrant an LLM repair attempt:
      * required narrative field missing/empty
      * dominant_reasoning too shallow (does not address the market story)
    Returns (repair_needed, errors[]).

No authority. No execution. Pure text/dict reasoning.
"""
import re

VALID_PHASES = {"accumulation", "manipulation", "distribution", "reversal",
                "continuation", "exhaustion", "transition", "neutral", "conflicted"}
VALID_DIRECTIONS = {"bullish", "bearish", "conflicted", "neutral"}
NEUTRAL_TOOL_FAMILIES = {"none", "wait", "two_sided_watch", "confirmation_required"}

# Requirement 1 — synonym → valid phase
PHASE_NORMALIZATION = {
    "early_expansion": "continuation",
    "expansion": "continuation",
    "mature_expansion": "continuation",
    "healthy_expansion": "continuation",
    "range_rotation": "accumulation",
    "range": "accumulation",
    "range_bound": "accumulation",
    "consolidation": "accumulation",
    "no_trade": "neutral",
    "no_playbook": "neutral",
    "uncertain": "conflicted",
    "unclear": "conflicted",
    "mixed": "conflicted",
    "chop": "conflicted",
    "rotation": "accumulation",
    "reversal_attempt": "reversal",
    "distribution_in_progress": "distribution",
    "manipulation_to_distribution": "distribution",
}

REQUIRED_NONEMPTY = [
    "narrative_direction", "narrative_phase", "phase_confidence",
    "active_draw", "protected_high_status", "protected_low_status",
    "forbidden_direction", "dominant_reasoning", "invalidation_level",
    "recommended_playbook_family", "recommended_tool_family",
]

# Reasoning-depth: story elements the dominant_reasoning should touch.
_STORY_ELEMENTS = {
    "price":         ("price", "level", "trading", "near", "around"),
    "liq_taken":     ("swept", "sweep", "raid", "taken", "reclaim"),
    "liq_remaining": ("sell-side", "buy-side", "sell side", "buy side", "resting", "remaining", "draw", "target", "liquidity"),
    "delivery":      ("delivery", "bearish", "bullish", "selling", "buying", "momentum"),
    "protected":     ("protected", "high", "low"),
    "phase":         ("manipulation", "distribution", "accumulation", "phase", "exhaustion", "continuation", "transition"),
    "invalidation":  ("invalidat", "reclaim", "above", "below", "breaks", "close"),
}
_MIN_STORY_ELEMENTS = 4
_MIN_REASONING_LEN = 60


# ── Tool/playbook family direction classification ─────────────────────────────

def _family_direction(value) -> str:
    """Return 'bullish' | 'bearish' | 'neutral' | 'mixed' for a tool/playbook family."""
    items = value if isinstance(value, list) else [value]
    toks = [str(i).lower() for i in items if i is not None]
    if not toks:
        return "neutral"
    if any(t in NEUTRAL_TOOL_FAMILIES for t in toks):
        return "neutral"
    bull = any(t.startswith("bullish") for t in toks)
    bear = any(t.startswith("bearish") for t in toks)
    if bull and not bear:
        return "bullish"
    if bear and not bull:
        return "bearish"
    if bull and bear:
        return "mixed"
    return "neutral"   # playbook-family names like "liquidity_sweep_reversal" carry no side


# ── Normalization (deterministic, non-fallback) ───────────────────────────────

def normalize_output(parsed: dict, memory_matches: "list | None" = None) -> tuple:
    """Apply non-fatal coherence fixes. Returns (normalized, notes[]). Never raises."""
    notes = []
    out = dict(parsed or {})
    try:
        # 1. enum synonym normalization
        raw_phase = (out.get("narrative_phase") or "").lower().strip()
        if raw_phase and raw_phase not in VALID_PHASES:
            norm = PHASE_NORMALIZATION.get(raw_phase)
            if norm is None:
                norm = "conflicted"   # unknown phase → safe non-directional
            notes.append({"field": "narrative_phase", "raw": raw_phase,
                          "normalized": norm, "reason": "enum_synonym_or_unknown"})
            out["narrative_phase"] = norm

        direction = (out.get("narrative_direction") or "neutral").lower().strip()
        if direction not in VALID_DIRECTIONS:
            notes.append({"field": "narrative_direction", "raw": direction,
                          "normalized": "conflicted", "reason": "invalid_direction"})
            direction = "conflicted"
            out["narrative_direction"] = direction

        # 2. tool-family coherence vs direction
        tdir = _family_direction(out.get("recommended_tool_family"))
        if direction in ("bullish", "bearish"):
            if tdir != "neutral" and tdir != direction:
                notes.append({"field": "recommended_tool_family",
                              "raw": out.get("recommended_tool_family"),
                              "normalized": ["confirmation_required"],
                              "reason": f"tool_dir={tdir}_contradicts_{direction}"})
                out["recommended_tool_family"] = ["confirmation_required"]
            pdir = _family_direction(out.get("recommended_playbook_family"))
            if pdir != "neutral" and pdir != direction:
                notes.append({"field": "recommended_playbook_family",
                              "raw": out.get("recommended_playbook_family"),
                              "normalized": "confirmation_required",
                              "reason": f"playbook_dir={pdir}_contradicts_{direction}"})
                out["recommended_playbook_family"] = "confirmation_required"
        else:  # conflicted / neutral → families must be a neutral token
            if tdir in ("bullish", "bearish", "mixed"):
                notes.append({"field": "recommended_tool_family",
                              "raw": out.get("recommended_tool_family"),
                              "normalized": ["confirmation_required"],
                              "reason": f"directional_tools_under_{direction}"})
                out["recommended_tool_family"] = ["confirmation_required"]

        # 3. forbidden_direction coherence
        fb = out.get("forbidden_direction")
        fb = fb.lower().strip() if isinstance(fb, str) else fb
        if direction == "bearish" and fb == "bearish":
            notes.append({"field": "forbidden_direction", "raw": "bearish",
                          "normalized": "bullish", "reason": "forbade_own_bearish_direction"})
            out["forbidden_direction"] = "bullish"
        elif direction == "bullish" and fb == "bullish":
            notes.append({"field": "forbidden_direction", "raw": "bullish",
                          "normalized": "bearish", "reason": "forbade_own_bullish_direction"})
            out["forbidden_direction"] = "bearish"

        # 3b. fill deterministically-completable fields (avoid LLM round-trips
        #     for things the system can safely default; these are NOT facts).
        direction = (out.get("narrative_direction") or "neutral").lower()
        if _empty(out.get("recommended_tool_family")):
            out["recommended_tool_family"] = (["confirmation_required"]
                if direction in ("bullish", "bearish") else ["none"])
            notes.append({"field": "recommended_tool_family", "raw": None,
                          "normalized": out["recommended_tool_family"], "reason": "filled_default"})
        if _empty(out.get("recommended_playbook_family")):
            out["recommended_playbook_family"] = (out.get("narrative_phase")
                if direction in ("bullish", "bearish") else "none") or "none"
            notes.append({"field": "recommended_playbook_family", "raw": None,
                          "normalized": out["recommended_playbook_family"], "reason": "filled_default"})
        for fld in ("protected_high_status", "protected_low_status"):
            if _empty(out.get(fld)):
                out[fld] = "none"
                notes.append({"field": fld, "raw": None, "normalized": "none", "reason": "filled_default"})
        if _empty(out.get("active_draw")):
            out["active_draw"] = "none"
            notes.append({"field": "active_draw", "raw": None, "normalized": "none", "reason": "filled_default"})
        if _empty(out.get("forbidden_direction")):
            out["forbidden_direction"] = ({"bullish": "bearish", "bearish": "bullish"}
                                          .get(direction))   # None for conflicted/neutral
            notes.append({"field": "forbidden_direction", "raw": None,
                          "normalized": out["forbidden_direction"], "reason": "filled_default"})

        # 4. strip unsupported analog citations from reasoning
        mm = memory_matches or out.get("memory_matches") or []
        valid_ids = {str((a or {}).get("timestamp")) for a in mm}
        dr = out.get("dominant_reasoning") or ""
        cited = re.findall(r"\b\d{8}T\d{6}\b", dr)
        unsupported = [c for c in cited if c not in valid_ids]
        if unsupported:
            for c in unsupported:
                dr = dr.replace(c, "[unverified-analog]")
            notes.append({"field": "dominant_reasoning", "raw": "cited_ids",
                          "normalized": "stripped", "reason": f"unsupported_analogs:{unsupported}"})
            out["dominant_reasoning"] = dr

        return out, notes
    except Exception as exc:  # noqa: BLE001
        return parsed or {}, [{"field": "_error", "reason": str(exc)}]


# ── Repair detection (warrants an LLM repair attempt) ─────────────────────────

def _empty(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str) and not v.strip():
        return True
    if isinstance(v, (list, dict)) and len(v) == 0:
        return True
    return False


def reasoning_depth_ok(text: str) -> tuple:
    """(ok, covered_elements). Shallow = label-only / too few story elements."""
    t = (text or "").lower()
    if len(t) < _MIN_REASONING_LEN:
        return False, []
    covered = [name for name, kws in _STORY_ELEMENTS.items() if any(k in t for k in kws)]
    return (len(covered) >= _MIN_STORY_ELEMENTS), covered


# Fields that only the LLM can meaningfully produce — the rest are filled by
# normalize_output() so they never trigger a repair/fallback.
_REPAIR_REQUIRED = ("narrative_direction", "narrative_phase", "dominant_reasoning")


def needs_repair(parsed: dict) -> tuple:
    """
    (repair_needed, errors[]). After normalize_output() has filled the
    deterministically-completable fields, the ONLY genuine repair triggers are:
    a missing direction/phase, or shallow dominant_reasoning (label-only). These
    require real LLM content and cannot be safely defaulted.
    """
    errors = []
    out = parsed or {}
    for f in _REPAIR_REQUIRED:
        if _empty(out.get(f)):
            errors.append(f"empty:{f}")
    if not _empty(out.get("dominant_reasoning")):
        ok, covered = reasoning_depth_ok(out.get("dominant_reasoning", ""))
        if not ok:
            errors.append(f"shallow_reasoning:covered={covered}")
    return (len(errors) > 0), errors


# ── BRAIN-FAMILY-REPAIR (2026-07-09): directional read without a family ───────
# The 2026-07-09 sovereignty audit found the LLM emitted a bullish/bearish
# narrative_direction with recommended_playbook_family='none' on 60 of 80
# directional scans — violating the AB-5C prompt mandate and blocking Brain
# sovereignty (sovereign_conversion requires a real family). This detector names
# that gap so narrative_brain can run a SOFT repair turn (keep the original LLM
# output if the repair fails — a stubborn 'none' must never nuke a healthy
# directional read into deterministic fallback).

def directional_family_gap(parsed: dict) -> tuple:
    """(gap: bool, errors[]). True when narrative_direction is bullish/bearish
    but the playbook/tool family is a neutral token or empty. Never raises."""
    errors = []
    try:
        out = parsed or {}
        direction = (out.get("narrative_direction") or "neutral").lower().strip()
        if direction not in ("bullish", "bearish"):
            return False, []
        pb = str(out.get("recommended_playbook_family") or "").lower().strip()
        if not pb or pb in NEUTRAL_TOOL_FAMILIES:
            errors.append(
                f"directional_without_playbook_family: narrative_direction="
                f"{direction} but recommended_playbook_family={pb or 'empty'!r} — "
                "a directional narrative MUST name one of the six canonical "
                "playbooks (AB-5C)")
        tf = out.get("recommended_tool_family")
        toks = [str(t).lower().strip() for t in (tf if isinstance(tf, list) else [tf])
                if t is not None]
        if not toks or all(t in NEUTRAL_TOOL_FAMILIES for t in toks):
            errors.append(
                f"directional_without_tool_family: narrative_direction="
                f"{direction} but recommended_tool_family={toks or 'empty'} — "
                "a directional narrative MUST name a concrete tool family (AB-5C)")
        return (len(errors) > 0), errors
    except Exception as exc:  # noqa: BLE001
        return False, [f"family_gap_error:{exc}"]


# ── AI-BRAIN-H2: prompt-input taint guard ─────────────────────────────────────
import json as _json

# Forbidden structure-direction terms that must never reach the LLM prompt
# OUTSIDE the explicitly-labeled STRUCTURE_WITNESS block.
_TAINT_TERMS = (
    "directional_bias", "market_bias", "narrative_bias",
    "bullish_bias", "bearish_bias", "bias_only", "structure_summary",
)


def scan_payload_taint(payload: dict) -> tuple:
    """
    (clean: bool, contamination_paths: list). Serializes the LLM payload MINUS
    the STRUCTURE_WITNESS block and scans for forbidden structure-direction
    keys/terms. STRUCTURE_WITNESS is allowed (it is explicitly labeled witness
    and carries no directional fields). Never raises.
    """
    try:
        scan = dict(payload or {})
        scan.pop("STRUCTURE_WITNESS", None)   # labeled witness is exempt
        blob = _json.dumps(scan, default=str).lower()
        hits = [t for t in _TAINT_TERMS if t in blob]
        # also catch a raw structure 'bias' key anywhere outside the witness block
        if '"bias"' in blob:
            hits.append("unlabeled_bias_key")
        return (len(hits) == 0), hits
    except Exception as exc:  # noqa: BLE001
        return False, [f"taint_scan_error:{exc}"]
