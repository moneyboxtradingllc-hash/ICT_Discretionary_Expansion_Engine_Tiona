"""
Phase AB-5B — ECU migration: Brain produces the thesis that the mechanical
layer validates and executes.

`BRAIN_ECU_MODE` (default false) gates the whole migration. When OFF, nothing
here runs and the system is bit-for-bit the pre-AB-5B mechanical-owned pipeline.
When ON:
  - `produce_thesis(snapshot)` runs the Brain (LLM if AI_BRAIN_LLM else the
    deterministic NA core) over the evidence available at qualification time
    (po3 delivery, liquidity, structure-witness) and returns the canonical
    thesis: direction, forbidden_direction, opportunity, playbook_family,
    tool_family, source, confidence.
  - qualification / playbook consume this thesis as the ORIGINATING direction;
    mechanical direction generation becomes witness-only.

The Brain runs as a pre-pass inside build_snapshot BEFORE qualification, so the
intelligence consumers receive Brain output. Never raises — on any failure the
thesis is non-directional and the mechanical witness path resumes (logged).
"""
import os

_STANCE = None   # module-level chronological stance memory for the ECU pre-pass


def ecu_enabled() -> bool:
    return os.getenv("BRAIN_ECU_MODE", "false").lower().strip() == "true"


def _stance():
    global _STANCE
    if _STANCE is None:
        from ai_brain.stance_memory import StanceMemory
        _STANCE = StanceMemory(persist=True)
    return _STANCE


def _family_token(value, direction):
    """Compact a tool/playbook family to a directional token or neutral."""
    items = value if isinstance(value, list) else [value]
    toks = [str(i).lower() for i in items if i]
    if any(t.startswith("bull") for t in toks):
        return "bullish"
    if any(t.startswith("bear") for t in toks):
        return "bearish"
    return direction if direction in ("bullish", "bearish") else "none"


def produce_thesis(snapshot: dict) -> dict:
    """
    Run the Brain pre-pass and return the canonical thesis. Never raises.
    Returns {owner, source, direction, forbidden_direction, opportunity,
             opportunity_type, playbook_family, tool_family, confidence,
             dominant_reasoning}.
    """
    try:
        from ai_brain.narrative_brain import run_narrative_brain, enabled as brain_enabled
        if not brain_enabled():
            return _empty("brain_disabled")
        res = run_narrative_brain(snapshot, snapshot.get("symbol", "QQQ"), _stance())
        o = res.get("output") or {}
        direction = (o.get("narrative_direction") or "neutral").lower()
        opportunity = direction in ("bullish", "bearish")
        return {
            "owner": "ai_brain",
            "source": res.get("source"),
            "direction": direction,
            "forbidden_direction": o.get("forbidden_direction"),
            "opportunity": opportunity,
            "opportunity_type": o.get("narrative_phase"),
            "playbook_family": o.get("recommended_playbook_family"),
            "tool_family": o.get("recommended_tool_family"),
            "confidence": o.get("phase_confidence", 0),
            "dominant_reasoning": o.get("dominant_reasoning", ""),
            # ENTRY-INVARIANT (2026-07-13) — the thesis's own falsification
            # level, previously dropped here (audit: absent from candidate,
            # served thesis, and every funnel organ). Witness value; the
            # entry-eligibility check reads it at the gate.
            "invalidation_level": o.get("invalidation_level"),
            "brain_block": res,
        }
    except Exception as exc:  # noqa: BLE001
        return _empty(f"ecu_error:{exc}")


def _empty(reason: str) -> dict:
    return {"owner": "ai_brain", "source": reason, "direction": "neutral",
            "forbidden_direction": None, "opportunity": False,
            "opportunity_type": None, "playbook_family": None,
            "tool_family": None, "confidence": 0, "dominant_reasoning": "",
            "invalidation_level": None, "brain_block": None}


# ── ENTRY-INVARIANT (2026-07-13) — thesis entry eligibility ───────────────────
# Audit finding (entry_invariant_audit_20260713.json): the Brain's
# invalidation_level was dropped by BOTH thesis projections and consulted by
# NOTHING in the funnel; 37/80 (46%) of directional authorized scans across 22
# sessions rode a thesis with no valid correct-side invalidation, own or
# inherited. The invariant: a directional Brain-owned thesis is ineligible for
# FRESH exposure until it names where it is WRONG. The thesis itself is
# untouched — it stays directional, persistent, lifecycle-visible, and
# repairable next scan; it just cannot author NEW risk while incomplete.
#
# Constitutional boundaries (test-locked):
#   - Neutral / non-sovereign (degraded-source) theses are EXEMPT — the
#     mechanical era's authorization path is untouched.
#   - POSITION SAFETY IS UNCONDITIONAL: this check lives in the entry gate
#     only; stops, position management, reconciliation and EOD never consult
#     it (they never consult the gate at all).
#   - Inheritance is honored: the served ab7_active_thesis carries the active
#     thesis's kept invalidation (breach-retired by the lifecycle), so a
#     continuing thesis whose earlier healthy read named a level stays
#     eligible even when the CURRENT scan's read is null.
# Inert unless BRAIN_INVALIDATION_ENTRY_INVARIANT=on. Fail-open on error.

def entry_invariant_enabled() -> bool:
    return (os.getenv("BRAIN_INVALIDATION_ENTRY_INVARIANT", "off")
            .lower().strip() == "on")


def _gate_price(snapshot: dict):
    ez = (snapshot.get("trade_intent") or {}).get("entry_zone") or {}
    if ez.get("current_price") is not None:
        return ez.get("current_price")
    tf = (snapshot.get("timeframes") or {}).get("1m") or {}
    return (tf.get("last_candle") or {}).get("close")


def thesis_entry_eligible(snapshot: dict) -> tuple:
    """(eligible: bool, reason: str). Gate-side entry eligibility for the
    Brain thesis. Never raises; fails OPEN (a broken check must not halt
    trading — it gets fixed, not obeyed)."""
    try:
        if not entry_invariant_enabled():
            return True, "entry invariant off"
        bt = snapshot.get("brain_thesis") or {}
        direction = (bt.get("direction") or "neutral").lower()
        if direction not in ("bullish", "bearish"):
            return True, "no directional brain thesis"
        source = str(bt.get("source") or "")
        if source not in ("llm", "ab7_active_thesis"):
            return True, f"non-sovereign thesis source ({source or 'none'})"
        inv = bt.get("invalidation_level")
        from ai_brain.brain_validation import invalidation_side_ok
        px = _gate_price(snapshot)
        if (isinstance(inv, (int, float)) and not isinstance(inv, bool)
                and invalidation_side_ok(direction, inv, px)):
            return True, "thesis invalidation valid"
        return False, (
            f"{direction} thesis without a valid correct-side invalidation "
            f"(level={inv!r}, px={px}) — fresh exposure ineligible until the "
            "thesis names where it is wrong (ENTRY-INVARIANT)")
    except Exception as exc:  # noqa: BLE001
        return True, f"entry invariant error (fail-open): {exc}"


# ── AI-AUTH-2 — Brain opportunity sovereignty ─────────────────────────────────
# THE single definition of "the healthy Brain authored a complete conversion".
# Consumed by qualification (conf-tier demotion + conversion floor) and by the
# risk governor (its duplicated legacy conf-tier hard block). One owner.
#
# Sovereignty requires ALL of:
#   1. a brain_thesis produced by the HEALTHY LLM path (source == "llm";
#      every degraded source — llm_failed_fallback, deterministic,
#      contaminated_input, degraded, ecu_error, brain_disabled — fails closed
#      and restores full legacy mechanical authority, byte-for-byte)
#   2. a directional opportunity (direction bullish/bearish, opportunity True)
#   3. a structural conversion: a real playbook or tool family (hedge tokens
#      like "none"/"confirmation_required" are NOT conversions)
#
# 2026-07-07 calibration truth: the 10:59 bullish read (playbook_family=
# "continuation") IS sovereign; the 11:14 read (families all "none") is NOT —
# the Brain never converted it, and sovereignty must not manufacture
# conversions the Brain didn't make.

_NON_FAMILIES = {"", "none", "unknown", "confirmation_required", "n/a", "null"}


def _family_present(value) -> bool:
    items = value if isinstance(value, list) else [value]
    return any(
        str(i).lower().strip() not in _NON_FAMILIES
        for i in items if i is not None
    )


def healthy_directional_thesis(snapshot: dict) -> tuple:
    """FINAL-SHOT — (healthy_directional: bool, detail: str).

    THE single owner of Brain-health semantics, shared by sovereign_conversion
    (which additionally requires a family) and the playbook classifier's
    directional-discovery path (which does not). True only when the HEALTHY
    LLM path authored a directional opportunity; every degraded source
    (llm_failed_fallback, deterministic, contaminated_input, degraded,
    ecu_error, brain_disabled) fails CLOSED. Never raises.
    """
    try:
        thesis = snapshot.get("brain_thesis")
        if not isinstance(thesis, dict):
            return False, "no_brain_thesis"
        source = thesis.get("source")
        if source == "ab7_active_thesis":
            # lifecycle-stabilized shape carries no raw Brain source — read the
            # scan's own candidate to confirm the LLM is actually healthy NOW
            cand = snapshot.get("candidate_thesis")
            source = cand.get("source") if isinstance(cand, dict) else None
        if source != "llm":
            return False, f"source={source}"
        direction = thesis.get("direction")
        if direction not in ("bullish", "bearish") or not thesis.get("opportunity"):
            return False, f"no_directional_opportunity({direction})"
        return True, f"healthy_directional:{direction}"
    except Exception as exc:  # noqa: BLE001
        return False, f"health_check_error:{exc}"


def sovereign_conversion(snapshot: dict) -> tuple:
    """(sovereign: bool, detail: str). Never raises; fails CLOSED (False)."""
    ok, detail = healthy_directional_thesis(snapshot)
    if not ok:
        return False, detail
    thesis = snapshot.get("brain_thesis") or {}
    if not (_family_present(thesis.get("playbook_family"))
            or _family_present(thesis.get("tool_family"))):
        return False, "no_family_conversion"
    return True, (f"llm_conversion:{thesis.get('direction')}:"
                  f"{thesis.get('playbook_family')}")
