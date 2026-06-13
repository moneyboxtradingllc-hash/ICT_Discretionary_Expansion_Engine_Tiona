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

from ai_brain.brain_input import build_brain_input
from ai_brain.brain_prompt import BRAIN_SYSTEM_PROMPT
from ai_brain.brain_schema import empty_brain_output, validate_brain_output
from ai_brain.brain_persistence import persist_brain_call
from narrative_authority.narrative_engine import build_narrative

_CONSUMED_FIELDS_AB1 = []   # AB-1 wires no consumers; populated as phases land


def enabled() -> bool:
    return os.getenv("AI_BRAIN_ENABLED", "false").lower().strip() == "true"


def _llm_enabled() -> bool:
    return os.getenv("AI_BRAIN_LLM", "false").lower().strip() == "true"


# ── Deterministic synthesis core (NA-1 engine → 23-field schema) ──────────────

def _deterministic(snapshot: dict, brain_input: dict) -> dict:
    na = build_narrative(snapshot, snapshot.get("protected_swings", {}) or {})
    out = empty_brain_output()
    direction = na.get("narrative_direction", "neutral")
    deliv = brain_input.get("delivery", {})
    liq = brain_input.get("liquidity", {})
    ps = brain_input.get("protected_swings", {})
    draw = (liq.get("active_draw") or {})
    inv = brain_input.get("playbook_toolbox", {})
    fav = direction if direction in ("bullish", "bearish") else None

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
        "memory_matches": [],   # real retrieval is a later AB phase
        "current_action": ("avoid_" + na["forbidden_trade_direction"]
                           if na.get("forbidden_trade_direction") else
                           ("prepare_" + direction if fav else "stand_down")),
        "reason": "; ".join(na.get("reasons", [])) or "deterministic NA synthesis",
        "must_not_do": ([f"do not trade {na['forbidden_trade_direction']}"]
                        if na.get("forbidden_trade_direction") else []),
    })
    return out


# ── LLM path ──────────────────────────────────────────────────────────────────

def _call_llm(brain_input: dict) -> tuple:
    """(parsed|None, source, error). Never raises."""
    try:
        from ai_layer.ai_api_adapter import _openai, _OPENAI_AVAILABLE  # type: ignore
    except Exception:
        return None, "deterministic", "adapter_unavailable"
    if not _OPENAI_AVAILABLE or not os.getenv("OPENAI_API_KEY"):
        return None, "deterministic", "no_llm"
    try:
        model = os.getenv("AI_BRAIN_MODEL", os.getenv("AI_MODEL", "gpt-4o-mini"))
        timeout = float(os.getenv("AI_BRAIN_TIMEOUT_SECONDS", "25"))
        client = _openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"),
                                timeout=timeout, max_retries=0)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": BRAIN_SYSTEM_PROMPT},
                      {"role": "user", "content": json.dumps(brain_input, default=str)}],
            timeout=timeout,
        )
        content = resp.choices[0].message.content or ""
        start, end = content.find("{"), content.rfind("}")
        if start < 0 or end < 0:
            return None, "deterministic", "no_json"
        parsed = json.loads(content[start:end + 1])
        ok, reason = validate_brain_output(parsed)
        if not ok:
            return None, "deterministic", f"invalid_schema:{reason}"
        return parsed, "llm", None
    except Exception as exc:  # noqa: BLE001
        return None, "deterministic", f"llm_error:{type(exc).__name__}"


# ── Public entry point ────────────────────────────────────────────────────────

def run_narrative_brain(snapshot: dict, symbol: str, stance_memory) -> dict:
    """Observe-only brain pass. Returns the brain block for snapshot['ai_brain'].
    Never raises."""
    if not enabled():
        return {"enabled": False, "authority": "observe_only", "output": None}
    try:
        history = stance_memory.history_summary() if stance_memory else {"available": False}
        brain_input = build_brain_input(snapshot, history)

        parsed, source, err = (None, "deterministic", None)
        if _llm_enabled():
            parsed, source, err = _call_llm(brain_input)
        output = parsed if (parsed is not None) else _deterministic(snapshot, brain_input)

        ok, vreason = validate_brain_output(output)
        if not ok:   # deterministic core must always be valid; guard anyway
            output = empty_brain_output()
            output["warnings"] = [f"schema fallback: {vreason}"]
            source = "degraded"

        if stance_memory:
            stance_memory.record(snapshot.get("timestamp", ""), output)

        record = {
            "timestamp": snapshot.get("timestamp"),
            "symbol": symbol,
            "source": source,
            "llm_error": err,
            "input_degraded": brain_input.get("degraded", []),
            "input_payload": brain_input,
            "raw_response": parsed,
            "parsed_output": output,
            "fields_consumed": list(_CONSUMED_FIELDS_AB1),   # [] in AB-1 — observe only
            "fields_persisted_not_yet_consumed": [k for k in output
                                                  if k not in _CONSUMED_FIELDS_AB1],
        }
        persisted_path = persist_brain_call(symbol, record)

        return {
            "enabled": True,
            "authority": "observe_only",
            "source": source,
            "input_degraded": brain_input.get("degraded", []),
            "output": output,
            "persisted": persisted_path,
        }
    except Exception as exc:  # noqa: BLE001
        out = empty_brain_output()
        out["warnings"] = [f"brain error (observe-only, non-blocking): {exc}"]
        return {"enabled": True, "authority": "observe_only",
                "source": "degraded", "output": out}
