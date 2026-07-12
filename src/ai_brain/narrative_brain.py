"""
Phase AB-1 — Narrative Brain orchestrator (the replacement, not a patch).

Pipeline per scan:
  build full two-sided input  →  synthesize narrative  →  validate  →
  persist (input + raw + parsed + consumed/ignored)  →  record own stance.

Synthesis source:
  - AI_BRAIN_LLM=true + key present → external model with the new prompt and
    the 23-field schema; invalid/failed output falls back to deterministic.
  - else → DETERMINISTIC core built on the NA-1 narrative_engine (delivery +
    protected swings + liquidity draw). This is real synthesis, NOT structure
    in costume — it is the same logic the gate already trusts (NA-1).

AUTHORITY: AB-1 is OBSERVE ONLY. Output lands in snapshot["ai_brain"] and
data/ai_brain/. No consumer is wired yet (gate/playbook/toolbox seeding are
later AB phases, gated separately). Rollback: AI_BRAIN_ENABLED=false. Never
raises — any failure yields a degraded, schema-valid witness output.
"""
import json
import os

import logging

from ai_brain.brain_input import build_brain_input
from ai_brain.brain_prompt import (
    BRAIN_SYSTEM_PROMPT, REPAIR_PROMPT_TEMPLATE, NEWS_CONTEXT_ADDENDUM,
    VOLUME_WITNESS_ADDENDUM,
    ADAPTIVE_LEARNING_ADDENDUM, ADAPTIVE_FRICTION_ADDENDUM, MARKET_COMMANDER_ADDENDUM,
)


def _market_commander_mode() -> bool:
    # MARKET COMMANDER B2 — env-gated; default off (no firewall coupling to the
    # market_commander module; just an env check).
    return (os.getenv("MARKET_COMMANDER_MODE", "false") or "").strip().lower() == "true"
# ADAPTIVE-1C/2A/2B — OBSERVE_ONLY adaptive context, friction + interpretation,
# and telemetry injection.
from adaptive_learning.context_formatter import (
    inject_adaptive_context, inject_friction_and_interpretation,
    build_adaptive_telemetry,
)
from ai_brain.brain_schema import (
    empty_brain_output, validate_brain_output, validate_llm_core,
)
from ai_brain.brain_validation import (
    normalize_output, needs_repair, scan_payload_taint, directional_family_gap,
    directional_invalidation_gap, invalidation_side_ok,
)
from ai_brain.brain_persistence import persist_brain_call
from narrative_authority.narrative_engine import build_narrative

_log = logging.getLogger(__name__)
_CONSUMED_FIELDS_AB1 = []   # AB-1 wires no consumers; populated as phases land


def enabled() -> bool:
    return os.getenv("AI_BRAIN_ENABLED", "false").lower().strip() == "true"


def _llm_enabled() -> bool:
    return os.getenv("AI_BRAIN_LLM", "false").lower().strip() == "true"


def _keep_shallow_enabled() -> bool:
    """BRAIN-RELIABILITY-1 (2026-07-09) — when on, a schema-valid LLM read whose
    ONLY residual repair error is reasoning-DEPTH (shallow prose) is KEPT with a
    warning instead of being destroyed by deterministic fallback. The organism
    examination found 12 healthy directional reads nuked to the mechanical
    narrative because their prose covered too few story elements — an authority
    inversion (mechanical replaces AI over style). Empty direction/phase/
    reasoning still falls back (content gaps are real failures). Default off."""
    return os.getenv("BRAIN_KEEP_SHALLOW_REASONING", "false").lower().strip() == "true"


def _invalidation_repair_enabled() -> bool:
    """BRAIN-INVALIDATION-REPAIR (2026-07-10) — gate for the SOFT invalidation
    repair turn. The Brain review measured invalidation_level null on 73% of
    directional reads. One repair round-trip asks the Brain to name the price
    where its own story is wrong. Adoption guards: same direction, hard
    validation passes, gap closed, and the level is on the CORRECT SIDE of
    price (a bearish stop above, bullish below) — a hallucinated level is
    refused and the original read stands. Never falls back. Default off."""
    return os.getenv("BRAIN_INVALIDATION_REPAIR", "off").lower().strip() == "on"


def _family_repair_enabled() -> bool:
    """BRAIN-FAMILY-REPAIR (2026-07-09) — gate for the SOFT family-repair turn.
    When on, a bullish/bearish narrative whose playbook/tool family is 'none'
    (an AB-5C mandate violation seen on 60/80 directional scans) gets ONE repair
    round-trip asking the LLM to name the concrete family its own story implies.
    The repair may never flip direction and its failure keeps the original
    output — it can only ADD a family, never degrade the read. Default off."""
    return os.getenv("BRAIN_FAMILY_REPAIR", "off").lower().strip() == "on"


# ── Deterministic synthesis core (NA-1 engine → 23-field schema) ──────────────

def _split_analogs(analogs: list, direction: str) -> tuple:
    """AB-4 — partition retrieved analogs into supporting vs conflicting the
    brain's direction (by analog narrative_direction / delivery_direction)."""
    support, conflict = [], []
    for a in analogs or []:
        ad = (a.get("narrative_direction") or a.get("delivery_direction") or "").lower()
        if direction in ("bullish", "bearish") and ad in ("bullish", "bearish"):
            (support if ad == direction else conflict).append(a)
        else:
            support.append(a)   # non-directional analog = neutral context
    return support, conflict


def _deterministic(snapshot: dict, brain_input: dict, analogs: list) -> dict:
    na = build_narrative(snapshot, snapshot.get("protected_swings", {}) or {})
    out = empty_brain_output()
    direction = na.get("narrative_direction", "neutral")
    deliv = brain_input.get("delivery", {})
    liq = brain_input.get("liquidity", {})
    ps = brain_input.get("protected_swings", {})
    draw = (liq.get("active_draw") or {})
    inv = brain_input.get("playbook_toolbox", {})
    fav = direction if direction in ("bullish", "bearish") else None

    # AB-4 — reason WITH retrieval, don't just archive it.
    support, conflict = _split_analogs(analogs, direction)
    analog_note = ""
    if analogs:
        wins = sum(1 for a in support if a.get("outcome") == "win")
        losses = sum(1 for a in support if a.get("outcome") == "loss")
        analog_note = (f" {len(analogs)} analog(s): {len(support)} support / "
                       f"{len(conflict)} conflict; support outcomes {wins}W/{losses}L.")

    # AB-4 — direction provenance (NA synthesis is delivery/liquidity/protected-led)
    na_src = na.get("lenses", {}) or {}
    structure_derived = (na_src.get("ai", {}).get("direction") is None
                         and na_src.get("delivery", {}).get("direction") is None
                         and direction in ("bullish", "bearish"))
    provenance = {
        "source": ("delivery_protected" if na_src.get("delivery", {}).get("direction")
                   else ("ai_brain" if na_src.get("ai", {}).get("direction")
                         else "fallback_none")),
        "structure_derived": bool(structure_derived),
        "retrieval_used": bool(analogs),
    }

    out.update({
        "market_story": (f"{na.get('narrative_phase','transition')} phase; "
                         f"delivery {deliv.get('state')}@{deliv.get('confidence')}; "
                         f"narrative {direction}."),
        "narrative_direction": direction,
        "narrative_phase":     na.get("narrative_phase", "transition"),
        "phase_confidence":    na.get("narrative_confidence", 0),
        "delivery_interpretation": f"{deliv.get('state')} (conf {deliv.get('confidence')}), "
                                   f"PO3 {deliv.get('po3_alignment')}",
        "liquidity_interpretation": (f"draw {draw.get('side')}@{draw.get('level')}"
                                     if draw else "no active draw"),
        "protected_high_interpretation": (
            f"{ps.get('protected_high_status')} "
            f"({(ps.get('protected_high') or {}).get('level')})"),
        "protected_low_interpretation": (
            f"{ps.get('protected_low_status')} "
            f"({(ps.get('protected_low') or {}).get('level')})"),
        "active_draw": (f"{draw.get('side')}@{draw.get('level')}" if draw else ""),
        "allowed_direction": na.get("allowed_trade_direction", "any"),
        "forbidden_direction": na.get("forbidden_trade_direction"),
        "preferred_trade_family": (na.get("narrative_phase") or ""),
        "preferred_playbooks": [inv.get("active_playbook")] if inv.get("active_playbook") not in (None, "no_playbook") else [],
        "preferred_tools": [t["tool"] for t in inv.get(fav, [])] if fav else [],
        "invalidation_level": na.get("invalidation_level"),
        "thesis_health": (brain_input.get("position", {}).get("thesis_health") or "n/a"),
        "contradiction_flags": na.get("conflict_flags", []),
        "warnings": na.get("warnings", []),
        "confidence_by_component": {
            "delivery": int(deliv.get("confidence") or 0),
            "liquidity": 60 if draw else 0,
            "structure": 40,
        },
        "memory_matches": analogs or [],          # AB-4 — retrieval wired in
        "current_action": ("avoid_" + na["forbidden_trade_direction"]
                           if na.get("forbidden_trade_direction") else
                           ("prepare_" + direction if fav else "stand_down")),
        "reason": ("; ".join(na.get("reasons", [])) or "deterministic NA synthesis") + analog_note,
        "must_not_do": ([f"do not trade {na['forbidden_trade_direction']}"]
                        if na.get("forbidden_trade_direction") else []),
        # AB-4 — expanded package
        "protected_high_status": ps.get("protected_high_status", "none"),
        "protected_low_status":  ps.get("protected_low_status", "none"),
        "dominant_reasoning": ((na.get("reasons") or ["deterministic NA synthesis"])[0]) + analog_note,
        "supporting_analogs": support,
        "conflicting_analogs": conflict,
        "recommended_playbook_family": (na.get("narrative_phase") or ""),
        "recommended_tool_family": [t["tool"] for t in inv.get(fav, [])] if fav else [],
        "direction_provenance": provenance,
    })
    return out


# ── LLM path ──────────────────────────────────────────────────────────────────

def _call_llm(brain_input: dict, repair: "dict | None" = None) -> dict:
    """
    Real LLM Brain call. Returns a full call record (never raises):
      {parsed, ok, model, prompt, user_content, raw_response, usage,
       fallback_reason}
    parsed is None + fallback_reason set on any failure (no silent success).
    `repair` (optional): {"previous": dict, "errors": [...]} adds a repair turn.
    """
    user_content = json.dumps(brain_input, default=str)
    # NEWS-1 — append the news-awareness clause ONLY when news_context is present
    # (NEWS_LAYER_ENABLED). Base prompt is unchanged otherwise (regression-safe).
    system_prompt = BRAIN_SYSTEM_PROMPT
    if isinstance(brain_input.get("news_context"), dict):
        system_prompt = system_prompt + NEWS_CONTEXT_ADDENDUM
    # VOLUME-WITNESS — participation clause ONLY when the payload carries the
    # block (VOLUME_WITNESS=on). Non-directional conviction evidence.
    if isinstance(brain_input.get("volume_witness"), dict):
        system_prompt = system_prompt + VOLUME_WITNESS_ADDENDUM
    # ADAPTIVE-1C — append the OBSERVE_ONLY cognitive boundary when adaptive
    # context is present (always once wired). Recommendation only; never applied.
    if isinstance(brain_input.get("adaptive_learning_context"), dict):
        system_prompt = system_prompt + ADAPTIVE_LEARNING_ADDENDUM
    # ADAPTIVE-2A/2B — friction/interpretation rebuttal directive when present.
    if isinstance(brain_input.get("adaptive_friction_report"), dict):
        system_prompt = system_prompt + ADAPTIVE_FRICTION_ADDENDUM
    # MARKET COMMANDER B2 — environment-first sequential reasoning (gated).
    if _market_commander_mode():
        system_prompt = system_prompt + MARKET_COMMANDER_ADDENDUM
    out = {"parsed": None, "ok": False, "model": None, "prompt": system_prompt,
           "user_content": user_content, "raw_response": None, "usage": None,
           "fallback_reason": None, "is_repair": bool(repair)}
    try:
        from ai_layer.ai_api_adapter import _openai, _OPENAI_AVAILABLE  # type: ignore
    except Exception:
        out["fallback_reason"] = "adapter_import_failed"
        return out
    if not _OPENAI_AVAILABLE:
        out["fallback_reason"] = "openai_package_unavailable"
        return out
    if not os.getenv("OPENAI_API_KEY"):
        out["fallback_reason"] = "no_api_key"
        return out
    try:
        model = os.getenv("AI_BRAIN_MODEL", os.getenv("AI_MODEL", "gpt-4o-mini"))
        out["model"] = model
        timeout = float(os.getenv("AI_BRAIN_TIMEOUT_SECONDS", "25"))
        client = _openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"),
                                timeout=timeout, max_retries=0)
        messages = [{"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}]
        if repair:
            messages.append({"role": "user", "content": REPAIR_PROMPT_TEMPLATE.format(
                errors="\n".join(str(e) for e in repair.get("errors", [])),
                previous=json.dumps(repair.get("previous", {}), default=str))})
        create_kwargs = {"model": model, "messages": messages, "timeout": timeout}
        # BRAIN-RELIABILITY-2 (2026-07-09) — structured JSON output eliminates
        # the JSONDecodeError fallback class (malformed JSON destroying healthy
        # reads). The prompt already demands JSON-only output; this makes the
        # API enforce it. Default off = legacy request shape.
        if os.getenv("BRAIN_JSON_MODE", "off").lower().strip() == "on":
            create_kwargs["response_format"] = {"type": "json_object"}
        resp = client.chat.completions.create(**create_kwargs)
        content = resp.choices[0].message.content or ""
        out["raw_response"] = content
        try:
            u = getattr(resp, "usage", None)
            if u is not None:
                out["usage"] = {"prompt_tokens": getattr(u, "prompt_tokens", None),
                                "completion_tokens": getattr(u, "completion_tokens", None),
                                "total_tokens": getattr(u, "total_tokens", None)}
        except Exception:  # noqa: BLE001
            pass
        start, end = content.find("{"), content.rfind("}")
        if start < 0 or end < 0:
            out["fallback_reason"] = "no_json_in_response"
            return out
        parsed = json.loads(content[start:end + 1])
        ok, reason = validate_llm_core(parsed)   # lenient: LLM produces narrative fields only
        if not ok:
            out["fallback_reason"] = f"invalid_schema:{reason}"
            return out
        out["parsed"], out["ok"] = parsed, True
        return out
    except Exception as exc:  # noqa: BLE001
        out["fallback_reason"] = f"llm_error:{type(exc).__name__}:{exc}"
        return out


# ── Public entry point ────────────────────────────────────────────────────────

def run_narrative_brain(snapshot: dict, symbol: str, stance_memory) -> dict:
    """Observe-only brain pass. Returns the brain block for snapshot['ai_brain'].
    Never raises."""
    if not enabled():
        return {"enabled": False, "authority": "observe_only", "output": None}
    try:
        history = stance_memory.history_summary() if stance_memory else {"available": False}
        brain_input = build_brain_input(snapshot, history)

        # AB-4 — retrieve historical analogs and reason WITH them. Prefer the
        # analogs already computed in the scan (snapshot["ai_retrieval"]); else
        # retrieve now. Observe-only; never authoritative for execution.
        analogs = []
        try:
            retr = snapshot.get("ai_retrieval") or {}
            if not retr.get("analogs"):
                from ai_retrieval.retrieval import retrieve_analogs
                # k-NN semantics: nearest authoritative analogs; similarity score
                # is carried for downstream judgment (observe-only).
                retr = retrieve_analogs(snapshot, k=5, authoritative_only=True,
                                        min_similarity=0.0, persist_log=False)
            analogs = retr.get("analogs", []) or []
            brain_input["memory_retrieval"] = {"count": len(analogs), "analogs": analogs}
        except Exception:  # noqa: BLE001
            analogs = []

        # ── ADAPTIVE-1C — OBSERVE_ONLY: distill analogs into an adaptive-learning
        # context the Brain can SEE (recommendation only). Hard-locked: nothing
        # here is applied to confidence/qualification/risk/execution. Always sets
        # brain_input["adaptive_learning_context"] (neutral when no analogs).
        adaptive_signal = inject_adaptive_context(brain_input, analogs, snapshot)

        # ── ADAPT-LOOP-3 — Brain self-accuracy context (DESCRIPTIVE_ONLY).
        # Gated BRAIN_ACCURACY_CONTEXT (default off): attaches the Brain's OWN
        # graded directional track record (replay-built table) inside
        # adaptive_learning_context so it reasons knowing how its calls resolve.
        # Inherits the ADAPTIVE_LEARNING cognitive boundary; never raises.
        from adaptive_learning.brain_accuracy import attach_accuracy_context
        attach_accuracy_context(brain_input, symbol)

        # ── ADAPTIVE-2A/2B — Adaptive Friction + Interpretation (OBSERVE_ONLY).
        # History's objection + experience-based read are attached to the payload
        # so the Brain can rebut them. No authority: influences NO decision,
        # confidence, risk, direction, or permission.
        adaptive_friction, adaptive_interp = inject_friction_and_interpretation(
            brain_input, adaptive_signal, snapshot)

        # ── ADAPTIVE-3 — Adaptive Policy context (OBSERVE_ONLY / DEFENSIVE_ONLY).
        # The performance-table policy report for this candidate, attached so the
        # Brain can SEE expectancy grades + defensive recommendations. Prefer the
        # snapshot's post-toolbox report; during the ECU pre-pass (before toolbox)
        # derive an environment-level view from the dims already known. Nothing
        # here is applied to confidence/qualification/risk/execution. Never raises.
        try:
            _policy = snapshot.get("adaptive_policy")
            if not isinstance(_policy, dict):
                from adaptive_learning.adaptive_policy_engine import (
                    generate_adaptive_policy_report)
                _regime = snapshot.get("market_regime", {}) or {}
                # MEM-DECAY-1: context view only — must NOT advance scar
                # state (the snapshot_builder policy pass owns persistence).
                _policy = generate_adaptive_policy_report(decay_persist=False, candidate={
                    "symbol":     symbol or snapshot.get("symbol"),
                    "playbook":   (snapshot.get("playbook", {}) or {}).get("selected_playbook"),
                    "tool":       (snapshot.get("toolbox", {}) or {}).get("preferred_tool"),
                    "session":    snapshot.get("session"),
                    "regime":     _regime.get("regime_family"),
                    "volatility": _regime.get("volatility_state"),
                })
            brain_input["adaptive_policy_context"] = _policy
        except Exception:  # noqa: BLE001
            pass

        # ── ADAPTIVE-4 — Bounded Mutation context (SHADOW / DEFENSIVE_ONLY).
        # The mutation the policy WOULD apply (confidence penalty / size halving /
        # soft veto) so the Brain can SEE that history is reducing conviction.
        # Observability only — computed, never enforced. Boosts ignored. Never
        # raises. Prefer the snapshot's mutation; else compute over brain-time dims.
        try:
            _mutation = snapshot.get("adaptive_mutation")
            if not isinstance(_mutation, dict):
                from adaptive_learning.adaptive_mutation_engine import mutate_candidate
                _q = snapshot.get("qualification", {}) or {}
                _mutation = mutate_candidate(
                    {
                        "confidence":           (snapshot.get("ai_context", {}) or {}).get("confidence_score"),
                        "qty":                  None,
                        "playbook":             (snapshot.get("playbook", {}) or {}).get("selected_playbook"),
                        "tool":                 (snapshot.get("toolbox", {}) or {}).get("preferred_tool"),
                        "qualification_status": _q.get("status"),
                        "direction":            _q.get("direction"),
                    },
                    brain_input.get("adaptive_policy_context") or _policy,
                )
            brain_input["adaptive_mutation_context"] = _mutation
        except Exception:  # noqa: BLE001
            pass

        # ── ADAPTIVE-5 — Live Mutation Authority context (LIVE / DEFENSIVE_ONLY).
        # The final defensive overlay the Brain must SEE (final confidence, soft
        # block, applied rules, authority level). The Brain may NOT override it.
        # Observability only here; downstream layers own consumption. Never raises.
        try:
            from adaptive_learning.adaptive_live_authority import (
                apply_adaptive_live_authority)
            _live = snapshot.get("adaptive_live_authority")
            if not isinstance(_live, dict):
                _live = apply_adaptive_live_authority({
                    "adaptive_policy":   brain_input.get("adaptive_policy_context"),
                    "adaptive_mutation": brain_input.get("adaptive_mutation_context"),
                })
            brain_input["adaptive_live_authority_context"] = _live
        except Exception:  # noqa: BLE001
            pass

        # ── AI-BRAIN-H1: LLM path with normalize → repair → explicit fallback ─
        llm_call = None
        ai_market_commander = None   # MARKET COMMANDER B2 (observe-only side output)
        source, fallback_reason = "deterministic", None
        norm_notes, repair_errors, repaired = [], [], False
        family_repair_attempted, family_repair_fixed, family_errors = False, False, []
        invalidation_repair_attempted, invalidation_repair_fixed = False, False
        invalidation_errors: list = []
        shallow_kept = False   # BRAIN-RELIABILITY-1 audit flag
        taint_clean, taint_paths = scan_payload_taint(brain_input)
        if _llm_enabled() and not taint_clean:
            # AI-BRAIN-H2 — contaminated input: do NOT call the LLM.
            source, fallback_reason = "contaminated_input", f"taint:{taint_paths}"
            _log.warning("AI_BRAIN_LLM payload contaminated (%s) — no LLM call, "
                         "deterministic fallback at %s", taint_paths, snapshot.get("timestamp"))
            output = _deterministic(snapshot, brain_input, analogs)
            output.setdefault("warnings", []).append(f"contaminated_input: {taint_paths}")
        elif _llm_enabled():
            llm_call = _call_llm(brain_input)
            if not llm_call["ok"]:
                source = "llm_failed_fallback"
                fallback_reason = llm_call["fallback_reason"]
                _log.warning("AI_BRAIN_LLM call failed (%s) — explicit "
                             "deterministic fallback at %s",
                             fallback_reason, snapshot.get("timestamp"))
                output = _deterministic(snapshot, brain_input, analogs)
                output.setdefault("warnings", []).append(f"llm_fallback: {fallback_reason}")
            else:
                parsed = llm_call["parsed"]
                # 1) deterministic normalization (enum/tool/forbidden/citations)
                parsed, norm_notes = normalize_output(parsed, analogs)
                # 2) repair-detection (completeness + reasoning depth)
                need, repair_errors = needs_repair(parsed)
                if need:
                    repaired = True
                    rep = _call_llm(brain_input, repair={"previous": parsed,
                                                         "errors": repair_errors})
                    if rep["ok"]:
                        llm_call["repair_usage"] = rep.get("usage")
                        llm_call["repair_raw"] = rep.get("raw_response")
                        parsed, more_notes = normalize_output(rep["parsed"], analogs)
                        norm_notes += more_notes
                        need, repair_errors = needs_repair(parsed)
                    else:
                        repair_errors.append(f"repair_call_failed:{rep['fallback_reason']}")
                # ── BRAIN-RELIABILITY-1 (2026-07-09) — style must not beat AI ──
                # If the ONLY residual errors are shallow_reasoning (prose depth)
                # and the read carries a real direction, phase, and non-empty
                # reasoning, KEEP the LLM output with a warning. Content gaps
                # (empty direction/phase/reasoning) still fall back.
                if need and _keep_shallow_enabled():
                    only_style = bool(repair_errors) and all(
                        str(e).startswith("shallow_reasoning")
                        for e in repair_errors)
                    if (only_style
                            and (parsed.get("narrative_direction") or "").lower()
                            in ("bullish", "bearish", "conflicted", "neutral")
                            and (parsed.get("narrative_phase") or "").strip()
                            and (parsed.get("dominant_reasoning") or "").strip()):
                        need = False
                        shallow_kept = True
                        parsed.setdefault("warnings", []).append(
                            f"shallow_reasoning_kept: {repair_errors}")
                if need:
                    # repair did not fix it → EXPLICIT fallback (logged)
                    source = "llm_failed_fallback"
                    fallback_reason = f"repair_incomplete:{repair_errors}"
                    _log.warning("AI_BRAIN_LLM repair incomplete (%s) — explicit "
                                 "deterministic fallback at %s",
                                 repair_errors, snapshot.get("timestamp"))
                    output = _deterministic(snapshot, brain_input, analogs)
                    output.setdefault("warnings", []).append(f"llm_fallback: {fallback_reason}")
                else:
                    source = "llm"
                    # ── BRAIN-FAMILY-REPAIR (2026-07-09) — SOFT repair turn ────
                    # A directional read whose family is 'none' violates the
                    # AB-5C mandate and blocks sovereignty. One repair attempt
                    # asks the LLM to name the family its own story implies.
                    # Guards: the repaired output must keep the SAME direction
                    # (no flip smuggled through), still pass hard validation,
                    # and actually close the gap — otherwise the ORIGINAL
                    # output stands. Never falls back, never fabricates.
                    fam_gap, family_errors = directional_family_gap(parsed)
                    if fam_gap and _family_repair_enabled():
                        family_repair_attempted = True
                        frep = _call_llm(brain_input, repair={
                            "previous": parsed, "errors": family_errors})
                        if frep["ok"]:
                            cand, cand_notes = normalize_output(frep["parsed"], analogs)
                            still_hard, _ = needs_repair(cand)
                            still_gap, _ = directional_family_gap(cand)
                            same_dir = (cand.get("narrative_direction")
                                        == parsed.get("narrative_direction"))
                            if not still_hard and not still_gap and same_dir:
                                parsed = cand
                                norm_notes += cand_notes
                                family_repair_fixed = True
                                llm_call["family_repair_usage"] = frep.get("usage")

                    # ── BRAIN-INVALIDATION-REPAIR (2026-07-10) — SOFT turn ────
                    # A directional read that refuses to name where it is WRONG
                    # (invalidation_level null — 73% of directional reads) gets
                    # ONE repair round-trip. Guards: same direction, hard
                    # validation, gap closed, AND the level sits on the correct
                    # side of price — hallucinated stops are refused. The
                    # ORIGINAL read stands on any failure; never falls back.
                    inv_gap, invalidation_errors = directional_invalidation_gap(parsed)
                    if inv_gap and _invalidation_repair_enabled():
                        invalidation_repair_attempted = True
                        irep = _call_llm(brain_input, repair={
                            "previous": parsed, "errors": invalidation_errors})
                        if irep["ok"]:
                            cand, cand_notes = normalize_output(irep["parsed"], analogs)
                            still_hard, _ = needs_repair(cand)
                            still_gap, _ = directional_invalidation_gap(cand)
                            same_dir = (cand.get("narrative_direction")
                                        == parsed.get("narrative_direction"))
                            side_ok = invalidation_side_ok(
                                cand.get("narrative_direction"),
                                cand.get("invalidation_level"),
                                (brain_input.get("market") or {}).get("current_price"))
                            if (not still_hard and not still_gap
                                    and same_dir and side_ok):
                                parsed = cand
                                norm_notes += cand_notes
                                invalidation_repair_fixed = True
                                llm_call["invalidation_repair_usage"] = irep.get("usage")
                    # MARKET COMMANDER B2 — capture the Brain-authored matrix from
                    # the RAW parse (observe-only side output; validated/coerced by
                    # market_commander, never consumed as authority here).
                    if _market_commander_mode():
                        _raw = (llm_call or {}).get("parsed") or {}
                        if isinstance(_raw.get("market_commander"), dict):
                            ai_market_commander = _raw["market_commander"]
                    output = empty_brain_output()
                    output.update(parsed)
                    direction = output.get("narrative_direction", "neutral")
                    support, conflict = _split_analogs(analogs, direction)
                    output["memory_matches"] = analogs
                    output["supporting_analogs"] = support
                    output["conflicting_analogs"] = conflict
                    output["direction_provenance"] = {
                        "source": "ai_brain", "structure_derived": False,
                        "retrieval_used": bool(analogs)}
                    if norm_notes:
                        output.setdefault("warnings", []).append(
                            f"normalized:{len(norm_notes)} field(s)")
        else:
            output = _deterministic(snapshot, brain_input, analogs)

        ok, vreason = validate_brain_output(output)
        if not ok:   # output must always be schema-valid; guard anyway
            output = empty_brain_output()
            output["warnings"] = [f"schema fallback: {vreason}"]
            source = "degraded"

        if stance_memory:
            stance_memory.record(snapshot.get("timestamp", ""), output)

        # ADAPTIVE-1C — telemetry: RECOMMENDED vs APPLIED kept separate; applied is
        # hard-locked 0, final_confidence == base_confidence (no behavioural change).
        base_confidence = int(output.get("phase_confidence", 0) or 0)
        adaptive_telemetry = build_adaptive_telemetry(
            base_confidence, adaptive_signal,
            friction=adaptive_friction, interpretation=adaptive_interp, output=output)

        record = {
            "timestamp": snapshot.get("timestamp"),
            "symbol": symbol,
            "source": source,
            "llm_enabled": _llm_enabled(),
            "llm_model": (llm_call or {}).get("model"),
            "llm_prompt": (llm_call or {}).get("prompt"),
            "llm_user_content": (llm_call or {}).get("user_content"),
            "llm_raw_response": (llm_call or {}).get("raw_response"),
            "llm_usage": (llm_call or {}).get("usage"),
            "fallback_reason": fallback_reason,
            # AI-BRAIN-H1 hardening audit trail
            "normalization_notes": norm_notes,
            "repair_attempted": repaired,
            "repair_errors": repair_errors,
            "repair_usage": (llm_call or {}).get("repair_usage"),
            # BRAIN-FAMILY-REPAIR (2026-07-09) — soft family-repair audit trail
            "family_repair_attempted": family_repair_attempted,
            "family_repair_fixed": family_repair_fixed,
            # BRAIN-INVALIDATION-REPAIR (2026-07-10) — soft repair audit trail
            "invalidation_repair_attempted": invalidation_repair_attempted,
            "invalidation_repair_fixed": invalidation_repair_fixed,
            "family_repair_errors": family_errors,
            "family_repair_usage": (llm_call or {}).get("family_repair_usage"),
            # BRAIN-RELIABILITY-1 — shallow prose kept instead of nuking the read
            "shallow_reasoning_kept": shallow_kept,
            "input_degraded": brain_input.get("degraded", []),
            "input_payload": brain_input,
            "adaptive_telemetry": adaptive_telemetry,   # ADAPTIVE-1C (observe_only)
            "ai_market_commander": ai_market_commander, # MARKET COMMANDER B2 (observe_only)
            "parsed_output": output,
            "fields_consumed": list(_CONSUMED_FIELDS_AB1),   # [] — observe only
            "fields_persisted_not_yet_consumed": [k for k in output
                                                  if k not in _CONSUMED_FIELDS_AB1],
        }
        persisted_path = persist_brain_call(symbol, record)

        return {
            "enabled": True,
            "authority": "observe_only",
            "source": source,                                   # llm | deterministic | llm_failed_fallback | degraded
            "llm_enabled": _llm_enabled(),
            "llm_model": (llm_call or {}).get("model"),
            "llm_usage": (llm_call or {}).get("usage"),
            "fallback_reason": fallback_reason,
            "normalization_notes": norm_notes,
            "repair_attempted": repaired,
            # BRAIN-FAMILY-REPAIR (2026-07-09) — soft family-repair telemetry
            "family_repair_attempted": family_repair_attempted,
            "family_repair_fixed": family_repair_fixed,
            # BRAIN-INVALIDATION-REPAIR (2026-07-10) — soft repair audit trail
            "invalidation_repair_attempted": invalidation_repair_attempted,
            "invalidation_repair_fixed": invalidation_repair_fixed,
            # BRAIN-RELIABILITY-1 — shallow prose kept instead of nuking the read
            "shallow_reasoning_kept": shallow_kept,
            "input_degraded": brain_input.get("degraded", []),
            "output": output,
            "adaptive_telemetry": adaptive_telemetry,   # ADAPTIVE-1C (observe_only)
            "ai_market_commander": ai_market_commander, # MARKET COMMANDER B2 (observe_only)
            "persisted": persisted_path,
        }
    except Exception as exc:  # noqa: BLE001
        out = empty_brain_output()
        out["warnings"] = [f"brain error (observe-only, non-blocking): {exc}"]
        return {"enabled": True, "authority": "observe_only",
                "source": "degraded", "output": out}
