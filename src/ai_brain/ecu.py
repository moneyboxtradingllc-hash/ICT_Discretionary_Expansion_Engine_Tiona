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
# Inert unless BRAIN_INVALIDATION_ENTRY_INVARIANT=on.
#
# ENTRY-INVARIANT-HARDENING (2026-07-13): an entry-authority check must not
# infer permission from uncertainty. The system must PROVE all three —
# numeric invalidation, KNOWN finite numeric price, strict correct side
# (equality invalid) — or fresh exposure is denied. Two audited defects fixed:
#   1. the exception arm returned eligible=True (fail-open) — now fail-CLOSED
#      for FRESH EXPOSURE ONLY (never a bot halt, never position management);
#   2. unknown price accepted a numeric invalidation via the repair-adoption
#      helper's unknown-px semantics (correct THERE, wrong HERE) — the
#      invariant now performs its own strict finite-number side check.
# Also hardened: NaN/inf rejected; booleans masquerading as numbers rejected.
# The structured record {eligible, code, reason, ...} rides the gate output
# as `entry_invariant` (persisted verbatim by the snapshot store).

ENTRY_INVARIANT_CODES = (
    "off", "non_directional", "non_sovereign_source", "valid",
    "missing_invalidation", "non_numeric_invalidation",
    "missing_current_price", "non_numeric_current_price",
    "wrong_side_invalidation", "invariant_evaluation_error",
)


def entry_invariant_enabled() -> bool:
    return (os.getenv("BRAIN_INVALIDATION_ENTRY_INVARIANT", "off")
            .lower().strip() == "on")


def _finite(v) -> bool:
    """True only for real finite numbers. Booleans are ints in Python and NaN/
    inf compare in surprising ways — neither may qualify as price or level."""
    import math
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v))


def _gate_price(snapshot: dict):
    ez = (snapshot.get("trade_intent") or {}).get("entry_zone") or {}
    if ez.get("current_price") is not None:
        return ez.get("current_price")
    tf = (snapshot.get("timeframes") or {}).get("1m") or {}
    return (tf.get("last_candle") or {}).get("close")


def _inv_record(eligible, code, reason, direction=None, source=None,
                invalidation_level=None, current_price=None) -> dict:
    return {"eligible": bool(eligible), "code": code, "reason": reason,
            "direction": direction, "source": source,
            "invalidation_level": invalidation_level,
            "current_price": current_price}


def thesis_entry_eligible(snapshot: dict) -> dict:
    """Structured entry-eligibility record for the Brain thesis:
    {eligible, code, reason, direction, source, invalidation_level,
    current_price}. Never raises. FAIL-CLOSED for fresh exposure: an internal
    error or unverifiable side denies NEW entry (code names the failure
    class). Position management never consults this — it never consults the
    gate at all."""
    if not entry_invariant_enabled():
        return _inv_record(True, "off", "entry invariant off")
    try:
        bt = snapshot.get("brain_thesis") or {}
        direction = str(bt.get("direction") or "neutral").lower().strip()
        source = str(bt.get("source") or "").lower().strip()
        inv = bt.get("invalidation_level")
        px = _gate_price(snapshot)
        base = dict(direction=direction, source=source,
                    invalidation_level=inv, current_price=px)

        if direction not in ("bullish", "bearish"):
            return _inv_record(True, "non_directional",
                               "no directional brain thesis", **base)
        if source not in ("llm", "ab7_active_thesis"):
            return _inv_record(True, "non_sovereign_source",
                               f"non-sovereign thesis source "
                               f"({source or 'none'}) — mechanical era rules",
                               **base)
        if inv is None:
            return _inv_record(False, "missing_invalidation",
                               f"{direction} thesis names no invalidation — "
                               "fresh exposure ineligible until the thesis "
                               "names where it is wrong (ENTRY-INVARIANT)",
                               **base)
        if not _finite(inv):
            return _inv_record(False, "non_numeric_invalidation",
                               f"{direction} thesis invalidation {inv!r} is "
                               "not a finite number (ENTRY-INVARIANT)", **base)
        if px is None:
            return _inv_record(False, "missing_current_price",
                               f"{direction} thesis invalidation {inv} cannot "
                               "be side-verified — current price unavailable; "
                               "permission is never inferred from uncertainty "
                               "(ENTRY-INVARIANT)", **base)
        if not _finite(px):
            return _inv_record(False, "non_numeric_current_price",
                               f"{direction} thesis invalidation {inv} cannot "
                               f"be side-verified — current price {px!r} is "
                               "not a finite number (ENTRY-INVARIANT)", **base)
        side_ok = inv > px if direction == "bearish" else inv < px
        if not side_ok:   # strict: equality is invalid
            return _inv_record(False, "wrong_side_invalidation",
                               f"{direction} thesis with invalidation {inv} "
                               f"on the wrong side of price {px} — a bearish "
                               "thesis dies strictly ABOVE price, a bullish "
                               "one strictly BELOW (ENTRY-INVARIANT)", **base)
        return _inv_record(True, "valid", "thesis invalidation valid", **base)
    except Exception as exc:  # noqa: BLE001
        # HARDENED: an entry-authority check that cannot evaluate must DENY
        # fresh exposure — never authorize from uncertainty. This is not a
        # halt: positions/stops/EOD run independently of the gate.
        return _inv_record(False, "invariant_evaluation_error",
                           f"entry invariant evaluation error — fresh "
                           f"exposure denied (fail-closed): {exc}")


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
