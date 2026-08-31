"""LUNA-LIVE-BRAIN — production Brain health for the TopstepX Combine smoke.

Proves that `gpt-5.6-luna` can serve as the sovereign author of a trade thesis
BEFORE any execution path is armed. It deliberately exercises the REAL
production code path — `narrative_brain._call_llm`, then the real validators —
rather than a parallel test path. A health check that proves a different code
path than the one that trades has proven nothing.

What "healthy" means here is narrow and specific:

  reachable            the model answers at all
  structured           it honors JSON mode (BRAIN_JSON_MODE)
  schema-valid         `validate_llm_core` accepts it
  normalizable         `normalize_output` produces a usable thesis
  correctly signed     a directional read carries an invalidation on the
                       correct side of price
  legally familied     a directional read names a real playbook/tool family
  sovereign-sourced    the thesis came from the live LLM, not a fallback

The last one is the one that matters most for safety. A deterministic fallback
can look like a perfectly good thesis; it simply was not authored by the model
the operator authorized. `brain_source` is therefore checked explicitly and a
fallback is a FAIL, never a degraded pass.

COST: this module makes at most ONE model call. It is a gate, not a study.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from ai_brain.model_pricing import PRICING, PRODUCTION_MODEL, cost_from_usage

REQUIRED_MODEL = PRODUCTION_MODEL

# Kept as a read-through view of the central table so existing callers keep
# working, without becoming a second place pricing can drift.
LUNA_PRICING = PRICING[PRODUCTION_MODEL]


def calculate_cost(usage: dict, pricing: dict = None) -> dict:
    """Dollar cost from real usage, via the single central pricing table."""
    return cost_from_usage(usage, PRODUCTION_MODEL)


def _probe_payload() -> dict:
    """A minimal but STRUCTURALLY REAL brain_input.

    Shaped like the live payload (same top-level keys the prompt expects) so the
    model is asked the question it will actually be asked, with an unambiguous
    bullish setup so a healthy model produces a directional read whose
    invalidation side can be checked. This is a wiring probe, not a market
    opinion — nothing here is used to author a trade.
    """
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session": "health_probe",
        "degraded": ["health_probe_payload"],
        "market": {"current_price": 20000.0,
                   "candles": {"5m": {"last_close": 20000.0, "last_high": 20005.0,
                                      "last_low": 19980.0, "body": 15.0}},
                   "volatility_state": "expansion", "expansion_state": "expanding"},
        "delivery": {"state": "bullish_delivery", "confidence": 70,
                     "continuation_intact": True},
        "liquidity": {"note": "prior session low swept at 19975, reclaimed"},
        "protected_levels": {"protected_low": 19975.0, "protected_high": 20050.0},
        "structure_note": "displacement up from the sweep; higher low holding",
    }


def run_health_check(model: str = None, *, call_llm=None) -> dict:
    """One live call through the production Brain path, fully validated.

    `call_llm` is injectable so tests exercise every verdict branch without
    spending a cent; production passes None and gets the real path.
    """
    from ai_brain.brain_schema import validate_llm_core
    from ai_brain.brain_validation import (
        directional_family_gap, normalize_output, wrong_side_initial_invalidation,
    )

    model = model or os.getenv("AI_BRAIN_MODEL", REQUIRED_MODEL)
    checks: dict = {}
    out: dict = {"model_requested": model, "generated_at": datetime.now(timezone.utc).isoformat()}

    checks["api_key_present"] = bool((os.getenv("OPENAI_API_KEY") or "").strip())
    if not checks["api_key_present"]:
        return _verdict(out, checks, "no OPENAI_API_KEY in the environment")

    # The authorized model for this mission is Luna and only Luna. A misconfigured
    # AI_BRAIN_MODEL must not silently route the smoke through another model.
    checks["model_is_authorized"] = (model == REQUIRED_MODEL)
    if not checks["model_is_authorized"]:
        return _verdict(out, checks,
                        f"AI_BRAIN_MODEL is {model!r}; this mission authorizes only {REQUIRED_MODEL!r}")

    if call_llm is None:
        from ai_brain.narrative_brain import _call_llm as call_llm  # noqa: SLF001

    prev_model = os.environ.get("AI_BRAIN_MODEL")
    os.environ["AI_BRAIN_MODEL"] = model
    started = time.time()
    try:
        res = call_llm(_probe_payload())
    except Exception as exc:  # noqa: BLE001
        return _verdict(out, checks, f"live call raised {type(exc).__name__}")
    finally:
        if prev_model is None:
            os.environ.pop("AI_BRAIN_MODEL", None)
        else:
            os.environ["AI_BRAIN_MODEL"] = prev_model
    out["latency_ms"] = int((time.time() - started) * 1000)

    checks["reachable"] = bool(res.get("raw_response")) or bool(res.get("parsed"))
    checks["no_fallback"] = not bool(res.get("fallback_reason"))
    if res.get("fallback_reason"):
        out["fallback_reason"] = str(res["fallback_reason"])[:200]
    checks["structured_output"] = bool(res.get("ok"))
    parsed = res.get("parsed")

    out["usage"] = calculate_cost(res.get("usage") or {})
    out["model_used"] = res.get("model")

    if not parsed:
        return _verdict(out, checks, out.get("fallback_reason") or "no parsed thesis returned")

    ok_core, why = validate_llm_core(parsed)
    checks["schema_valid"] = bool(ok_core)
    if not ok_core:
        out["schema_error"] = str(why)[:200]
        return _verdict(out, checks, f"schema rejected: {why}")

    normalized, _ = normalize_output(parsed)
    direction = str(normalized.get("narrative_direction") or "").lower()
    out["direction"] = direction
    checks["normalized"] = isinstance(normalized, dict) and bool(normalized)

    directional = direction in ("bullish", "bearish")
    out["directional"] = directional
    if directional:
        gap, notes = directional_family_gap(normalized)
        # directional_family_gap returns True when a family is MISSING.
        checks["legal_family"] = not gap
        if gap:
            out["family_error"] = str(notes)[:200]
        wrong, wnotes = wrong_side_initial_invalidation(
            normalized, _probe_payload()["market"]["current_price"])
        checks["correct_side_invalidation"] = not wrong
        if wrong:
            out["invalidation_error"] = str(wnotes)[:200]
        out["invalidation_level"] = normalized.get("invalidation_level")
    else:
        # A non-directional read is a legitimate answer, not a failure. It simply
        # cannot authorize a trade — which the smoke gate enforces separately.
        checks["legal_family"] = True
        checks["correct_side_invalidation"] = True

    checks["sovereign_source"] = bool(res.get("ok")) and not res.get("fallback_reason")
    return _verdict(out, checks, None)


def _verdict(out: dict, checks: dict, blocker) -> dict:
    out["checks"] = checks
    out["blocker"] = blocker
    out["verdict"] = "PASS" if (blocker is None and all(checks.values())) else "FAIL"
    return out
