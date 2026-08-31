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
import time

from ai_brain import ai_call_ledger as LEDGER
import os

import logging

from ai_brain.brain_input import build_brain_input
from ai_brain.brain_prompt import (
    BRAIN_SYSTEM_PROMPT, REPAIR_PROMPT_TEMPLATE, NEWS_CONTEXT_ADDENDUM,
    VOLUME_WITNESS_ADDENDUM, CANDLE_TEMPORAL_ADDENDUM, EXECUTION_PRICE_ADDENDUM,
    REJECTION_ENTRY_MODE_ADDENDUM, DEALING_RANGE_ADDENDUM,
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
    wrong_side_initial_invalidation,
)
from ai_brain.brain_persistence import persist_brain_call
from narrative_authority.narrative_engine import build_narrative

_log = logging.getLogger(__name__)

# ── call context ─────────────────────────────────────────────────────────────
# Session id and scan number belong on every accounting row, but threading them
# through `_call_llm`'s signature would break every existing test double
# (`lambda bi, repair=None`) and, worse, would make the accounting change the
# call contract. They ride here instead: set once per scan, read at call time.
_CALL_CONTEXT = {"session_id": "", "scan": None, "attempt": 1}


def set_call_context(*, session_id: str = "", scan: object = None,
                     attempt: int = 1) -> None:
    _CALL_CONTEXT.update({"session_id": session_id or "", "scan": scan,
                          "attempt": int(attempt)})


def _purpose_for(repair) -> str:
    """Which of the four call sites this is. Derived from the repair payload so
    the callable signature stays exactly what every test double expects."""
    if not repair:
        return LEDGER.PURPOSE_PRIMARY
    return (repair or {}).get("purpose") or LEDGER.PURPOSE_JSON_REPAIR


def _call_context() -> tuple:
    return (_CALL_CONTEXT.get("session_id", ""), _CALL_CONTEXT.get("scan"),
            _CALL_CONTEXT.get("attempt", 1))
_CONSUMED_FIELDS_AB1 = []   # AB-1 wires no consumers; populated as phases land


def enabled() -> bool:
    return os.getenv("AI_BRAIN_ENABLED", "false").lower().strip() == "true"


def _llm_enabled() -> bool:
    return os.getenv("AI_BRAIN_LLM", "false").lower().strip() == "true"


JSON_MODE_TRUTHY = ("on", "true", "1", "yes")


def _armed_session() -> bool:
    """True when an ARMED production launcher owns this process.

    Set by the launcher, never by a test or a diagnostic, so model resolution
    fails closed only where a real order could follow.
    """
    return os.getenv("PRODUCTION_ARMED_SESSION", "").strip().lower() in ("1", "true", "on", "yes")


def json_mode_enabled() -> bool:
    """Whether the API is asked to ENFORCE JSON (response_format).

    THE single source of truth. The armed-startup guard calls this same
    predicate rather than reading the variable itself, because the two must not
    be able to disagree: the original check accepted only the literal "on", so
    `BRAIN_JSON_MODE=true` would have read as enabled to an operator and to a
    naive guard while leaving the model on prose instruction alone.

    On 2026-08-06 the flag was unset entirely and 2 of 38 live Luna calls came
    back malformed -- an unclosed array, and English number words as bare
    tokens. Neither is possible when the API enforces the grammar.
    """
    return os.getenv("BRAIN_JSON_MODE", "off").lower().strip() in JSON_MODE_TRUTHY


SOVEREIGN_SOURCE = "llm"


def degraded_reason(source: str, output: dict, fallback: str = None) -> "str | None":
    """The explicit reason a call is not sovereign, or None when it is.

    Every non-sovereign source must carry a stated reason. A degraded call with
    no reason makes a legitimate market stand-down look identical to a Brain
    failure -- on 2026-08-06 three schema-valid reads were degraded by
    `recommended_tool_family wrong type: str` and that reason was only
    discoverable by digging into output["warnings"].
    """
    if source == SOVEREIGN_SOURCE and not fallback:
        return None
    if fallback:
        return str(fallback)
    for w in (output or {}).get("warnings") or []:
        if str(w).startswith("schema fallback:"):
            return str(w).replace("schema fallback:", "schema_invalid:").strip()
        return str(w)
    return f"non_sovereign_source:{source}"


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


def _invalidation_side_check_enabled() -> bool:
    """BRAIN-INVALIDATION-SIDE-CHECK (2026-07-12) — gate for the INITIAL-read
    side guard (the #9 watch item: repair adoptions were side-checked, initial
    reads were not). When on, a directional read whose numeric
    invalidation_level sits on the WRONG side of a known price has that level
    STRIPPED (recorded in telemetry) — becoming an ordinary invalidation gap
    the existing detector + guarded soft repair already handle. Direction is
    never touched; unknown price never fires; default off = byte-identical."""
    return os.getenv("BRAIN_INVALIDATION_SIDE_CHECK", "off").lower().strip() == "on"


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


#: Snapshot blocks carrying ACCOUNT truth rather than MARKET truth. Market
#: truth is what both authors reason over; account truth meets the organism only
#: at the risk gate, and has no business in a replay archive.
_ACCOUNT_BLOCKS = ("position_monitor", "risk", "broker_stop", "broker_trace",
                   "paper_execution", "trade_reconciliation", "performance_dashboard",
                   "account", "capital", "adaptive_size")


def _archivable_snapshot(snapshot: dict) -> dict:
    """The raw snapshot minus account state, FULLY DETACHED from the live one.

    A shallow copy shared every nested dict and list with the live snapshot, so
    the archive's correctness depended on nothing mutating between building the
    record and serialising it -- a guarantee held by statement ordering rather
    than by the data. Evidence that replay depends on may not rest on where a
    line happens to sit.

    Detaching is done through the JSON round trip the telemetry format uses
    anyway, so anything that could not be archived faithfully is coerced here
    rather than at write time. Never raises: archiving a scan may never be the
    reason a scan fails.
    """
    try:
        if not isinstance(snapshot, dict):
            return {}
        trimmed = {k: v for k, v in snapshot.items() if k not in _ACCOUNT_BLOCKS}
        return json.loads(json.dumps(trimmed, default=str))
    except Exception:  # noqa: BLE001
        try:
            return copy.deepcopy({k: v for k, v in snapshot.items()
                                  if k not in _ACCOUNT_BLOCKS})
        except Exception:  # noqa: BLE001
            return {}


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

def _carries_dealing_range(brain_input: dict) -> bool:
    """Does the payload actually carry a measured dealing range?

    DEALING-RANGE-PAYLOAD-1. Guarded like every other addendum: a clause
    describing an auction the payload cannot show teaches the model to imagine
    one. `high` is the discriminator because an empty block is published as {}.
    Never raises.
    """
    try:
        dr = ((brain_input or {}).get("market") or {}).get("dealing_range") or {}
        return isinstance(dr, dict) and dr.get("high") is not None
    except Exception:  # noqa: BLE001
        return False


def _carries_anchored_rejection_block(brain_input: dict) -> bool:
    """Does the catalog actually carry an anchored rejection block?

    REJECTION-ENTRY-MODE-SEPARATION-1. Guarded like every other addendum: the
    clause explains how to read a specific object, and describing an object the
    payload does not contain teaches the model to imagine one. Never raises.
    """
    try:
        return any(isinstance(t, dict)
                   and t.get("level_type") == "protected_level_rejection_block"
                   for t in ((brain_input or {}).get("authorized_tool_catalog") or []))
    except Exception:  # noqa: BLE001
        return False


def _carries_execution_price(brain_input: dict) -> bool:
    """Does this payload actually carry the execution-price block?

    EXEC-PRICE-FRESHNESS-2. Guarded rather than assumed, exactly as
    `_candles_carry_temporal_status` is: an archive predating
    EXEC-PRICE-FRESHNESS-1 has no such block, and a clause explaining a field the
    model cannot see teaches it to hallucinate one. The clause is attached when
    the block EXISTS -- including when it exists and reports itself unavailable
    or stale, because that state is precisely what the Brain must learn to
    describe rather than repair. Never raises.
    """
    try:
        block = ((brain_input or {}).get("market") or {}).get("execution_price")
        return isinstance(block, dict) and bool(block.get("schema"))
    except Exception:  # noqa: BLE001
        return False


def _candles_carry_temporal_status(brain_input: dict) -> bool:
    """Does this payload actually state settled/forming/unknown per timeframe?

    Guarded rather than assumed: a trimmed archive replayed through this path
    carries no `timeframes`, so the clause explaining the field would describe
    something the model cannot see. Never raises.
    """
    try:
        by_tf = ((brain_input or {}).get("market") or {}).get("candles") or {}
        return any(isinstance(b, dict) and b.get("last_candle_temporal_status")
                   for b in by_tf.values())
    except Exception:  # noqa: BLE001
        return False


def _call_llm(brain_input: dict, repair: "dict | None" = None) -> dict:
    """
    Real LLM Brain call. Returns a full call record (never raises):
      {parsed, ok, model, prompt, user_content, raw_response, usage,
       fallback_reason}
    parsed is None + fallback_reason set on any failure (no silent success).
    `repair` (optional): {"previous": dict, "errors": [...]} adds a repair turn.
    """
    purpose = _purpose_for(repair)
    session_id, scan, attempt = _call_context()
    user_content = json.dumps(brain_input, default=str)
    # NEWS-1 — append the news-awareness clause ONLY when news_context is present
    # (NEWS_LAYER_ENABLED). Base prompt is unchanged otherwise (regression-safe).
    system_prompt = BRAIN_SYSTEM_PROMPT
    # CONTINUITY-2G — how to read `temporal_status`, appended ONLY when the
    # payload actually carries it. A prompt that describes metadata the payload
    # does not have teaches the model to hallucinate the field; an older archive
    # replayed through this path is therefore left with the base prompt.
    if _candles_carry_temporal_status(brain_input):
        system_prompt = system_prompt + CANDLE_TEMPORAL_ADDENDUM
    # EXEC-PRICE-FRESHNESS-2 — which of the two price fields means "now".
    # Without this the Brain reads `current_price` (a SETTLED close) as the live
    # location, which is the 2026-08-20 11:02:10 defect exactly.
    if _carries_execution_price(brain_input):
        system_prompt = system_prompt + EXECUTION_PRICE_ADDENDUM
    # REJECTION-ENTRY-MODE-SEPARATION-1 — an established block is already the
    # rejection; a second one is confirmation, not a prerequisite.
    if _carries_anchored_rejection_block(brain_input):
        system_prompt = system_prompt + REJECTION_ENTRY_MODE_ADDENDUM
    # DEALING-RANGE-PAYLOAD-1 — where price sits in the auction. Location
    # context; premium is not a short signal and discount is not a long one.
    if _carries_dealing_range(brain_input):
        system_prompt = system_prompt + DEALING_RANGE_ADDENDUM
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
        # Single authority. The old chain fell through AI_MODEL to gpt-4o-mini,
        # so a missing AI_BRAIN_MODEL ran production on a weaker model silently.
        from ai_brain.production_model import resolve_model
        model = resolve_model(armed=_armed_session())
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
        # ── PROMPT CACHING (2026-08-11) ──────────────────────────────────────
        # Measured on 116 live calls: the system prompt is 13,250 chars and
        # BYTE-IDENTICAL across every scan (~3,988 tokens, 37.6% of the
        # prompt); the user payload diverges at character 23. The message
        # order is already [system(static), user(dynamic)], which is exactly
        # the shape caching wants, so NOTHING about what Terra reads changes
        # here -- only a stable key is attached so the identical prefix can be
        # recognised across scans.
        #
        # `prompt_cache_key` deliberately excludes session/scan/timestamp: any
        # of those would give every request a unique key and guarantee a miss.
        # It DOES include the model and a doctrine version, because a changed
        # prefix must not silently reuse an old one.
        cache_key = LEDGER.cache_key(role=LEDGER.PRIMARY, model=model)
        create_kwargs["prompt_cache_key"] = cache_key
        client_request_id = LEDGER.new_client_request_id(
            session_id=session_id, scan=scan, role=LEDGER.PRIMARY,
            purpose=purpose, attempt=attempt)
        # Sent so a request that TIMES OUT still has an identity we own; the
        # server's x-request-id only exists if a response came back.
        create_kwargs["extra_headers"] = {
            LEDGER.CLIENT_REQUEST_HEADER: client_request_id}
        out["client_request_id"] = client_request_id
        out["prompt_cache_key"] = cache_key
        # BRAIN-RELIABILITY-2 (2026-07-09) — structured JSON output eliminates
        # the JSONDecodeError fallback class (malformed JSON destroying healthy
        # reads). The prompt already demands JSON-only output; this makes the
        # API enforce it. Default off = legacy request shape.
        if json_mode_enabled():
            create_kwargs["response_format"] = {"type": "json_object"}
        _started = time.time()
        # `with_raw_response` exposes the HTTP headers, which is the only place
        # OpenAI's `x-request-id` lives. Falls back to the plain call when the
        # SDK (or a test double) does not offer it -- instrumentation may never
        # be the reason a scan loses its brain.
        _raw = None
        try:
            _raw = client.chat.completions.with_raw_response.create(**create_kwargs)
            resp = _raw.parse()
        except AttributeError:
            resp = client.chat.completions.create(**create_kwargs)
        _latency = time.time() - _started
        content = resp.choices[0].message.content or ""
        out["raw_response"] = content
        out["request_id"] = LEDGER.server_request_id(_raw, resp)
        out["response_id"] = getattr(resp, "id", "") or ""
        out["latency_seconds"] = _latency
        try:
            u = getattr(resp, "usage", None)
            if u is not None:
                # Full class breakdown: cached vs uncached input and cache
                # writes are billed differently, and one flat `prompt_tokens`
                # cannot be costed honestly.
                out["usage"] = dict(LEDGER.usage_breakdown(u))
        except Exception:  # noqa: BLE001
            pass
        LEDGER.record(
            session_id=session_id, scan=scan, role=LEDGER.PRIMARY,
            purpose=purpose, attempt=attempt, model_requested=model,
            model_returned=getattr(resp, "model", "") or "",
            client_request_id=client_request_id, request_id=out["request_id"],
            response_id=out["response_id"], usage=getattr(resp, "usage", None),
            ok=True, latency_seconds=_latency, prompt_cache_key=cache_key,
            cache_mode="implicit")
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

        # BUILD-CANONICAL-EXTERNAL-BRAIN-EXECUTION-BRIDGE (2026-08-07).
        # PROD-20260807 proved the deterministic layer already knew every level
        # Terra wanted -- 29452.50 was enumerated on all 23 propose-entry scans
        # -- but the catalog was built AFTER the model call and never shown to
        # it. Terra named levels in prose and a resolver tried to guess which
        # object was meant; it failed on 17 of 23. Publishing the catalog HERE,
        # before the call, lets Terra select an id and removes prose from the
        # execution join entirely.
        try:
            from broker.luna_candidate_producer import (
                authorized_invalidation_catalog, authorized_objective_catalog)
            reference = ((brain_input.get("market") or {}).get("current_price"))
            brain_input["authorized_objectives"] = authorized_objective_catalog(
                snapshot, brain_input, reference)
            brain_input["authorized_invalidations"] =                 authorized_invalidation_catalog(brain_input)
        except Exception:  # noqa: BLE001 -- a catalog failure must not kill the read
            brain_input["authorized_objectives"] = []
            brain_input["authorized_invalidations"] = []

        # COGNITION-ESCALATION-ROUTER-1 (2026-08-24) -- SHADOW ONLY.
        #
        # Placed HERE and nowhere earlier because this is the last point that is
        # still PRE-PROVIDER while both catalogs exist: `authorized_tool_catalog`
        # carries where price stands, `authorized_objectives` carries what stands
        # in front of each target, and `active_path_state` carries who owns the
        # leg. Routing before this point would have to guess at evidence the
        # organism has not built yet.
        #
        # It reads NOTHING a model produced and writes NOTHING the model can see:
        # the verdict goes to a separate sink, never to `brain_input`. The call
        # cannot raise and its return value is discarded, so removing this block
        # entirely would leave the scan byte-identical.
        try:
            from cognition.escalation_router import observe as _shadow_route
            _shadow_route(snapshot=snapshot, brain_input=brain_input,
                          symbol=symbol)
        except Exception:  # noqa: BLE001 -- shadow telemetry may never cost a scan
            pass

        # AB-4 — reason WITH the analogs the SCAN retrieved. Observe-only;
        # never authoritative for execution.
        #
        # ONE SCAN -> ONE RETRIEVAL RESULT. This used to re-query whenever the
        # scan's result carried no analogs, and that second call passed
        # `min_similarity=0.0` -- bypassing the bound MIN_SIMILARITY (0.60) and,
        # because `retrieve_analogs` has no enablement gate of its own, also
        # bypassing AI_RETRIEVAL_ENABLED. Terra could therefore be shown analogs
        # the contract had already rejected, from a corpus the operator believed
        # was switched off, and the telemetry describing "the" retrieval would
        # have described a different query than the one the Brain consumed.
        analogs = []
        try:
            retr = snapshot.get("ai_retrieval") or {}
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
        side_check_flagged, side_check_stripped = False, None   # SIDE-CHECK audit
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
                    rep = _call_llm(brain_input, repair={"purpose": LEDGER.PURPOSE_JSON_REPAIR,
                                                        "previous": parsed,
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
                            "purpose": LEDGER.PURPOSE_FAMILY_REPAIR,
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

                    # ── BRAIN-INVALIDATION-SIDE-CHECK (2026-07-12) ────────────
                    # Initial-read guard (the #9 watch item): a directional read
                    # whose NUMERIC invalidation sits on the wrong side of a
                    # known price is a poisoned stop reference. Strip the level
                    # (recorded below) so it becomes an ordinary invalidation
                    # GAP — the existing detector + guarded repair take over.
                    # Direction untouched; unknown price never fires.
                    side_errors: list = []
                    if _invalidation_side_check_enabled():
                        _wrong, side_errors = wrong_side_initial_invalidation(
                            parsed,
                            (brain_input.get("market") or {}).get("current_price"))
                        if _wrong:
                            side_check_flagged = True
                            side_check_stripped = parsed.get("invalidation_level")
                            parsed = dict(parsed)
                            parsed["invalidation_level"] = None

                    # ── BRAIN-INVALIDATION-REPAIR (2026-07-10) — SOFT turn ────
                    # A directional read that refuses to name where it is WRONG
                    # (invalidation_level null — 73% of directional reads) gets
                    # ONE repair round-trip. Guards: same direction, hard
                    # validation, gap closed, AND the level sits on the correct
                    # side of price — hallucinated stops are refused. The
                    # ORIGINAL read stands on any failure; never falls back.
                    inv_gap, invalidation_errors = directional_invalidation_gap(parsed)
                    if side_errors:
                        # tell the repair turn WHY the level was removed, not
                        # just that it is missing
                        invalidation_errors = side_errors + invalidation_errors
                    if inv_gap and _invalidation_repair_enabled():
                        invalidation_repair_attempted = True
                        irep = _call_llm(brain_input, repair={
                            "purpose": LEDGER.PURPOSE_INVALIDATION_REPAIR,
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
            # BRAIN-INVALIDATION-SIDE-CHECK (2026-07-12) — initial-read guard
            "invalidation_side_check_flagged": side_check_flagged,
            "invalidation_side_check_stripped": side_check_stripped,
            "family_repair_errors": family_errors,
            "family_repair_usage": (llm_call or {}).get("family_repair_usage"),
            # BRAIN-RELIABILITY-1 — shallow prose kept instead of nuking the read
            "shallow_reasoning_kept": shallow_kept,
            "input_degraded": brain_input.get("degraded", []),
            "input_payload": brain_input,
            # RAW-SNAPSHOT-ARCHIVE (2026-08-07) — OBSERVATIONAL ONLY.
            #
            # `input_payload` is what the external Brain saw. The DETERMINISTIC
            # author reads the raw snapshot instead, and that was never
            # preserved -- so no archived session can replay both authors over
            # the same moment. PROD-20260807 has canonical objects but no raw
            # snapshot; the QQQ-era snapshots have the raw snapshot but predate
            # canonical objects. Neither half alone can answer whether the two
            # brains agree.
            #
            # Nothing reads this back. It changes no input, no authority, no
            # timing beyond one dict copy, and no decision.
            "raw_snapshot": _archivable_snapshot(snapshot),
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
            # LUNA-DEGRADED-TELEMETRY (2026-08-06): the reason a call was
            # degraded lived only inside output["warnings"], where a caller
            # reading the block's top level saw source=degraded with
            # fallback_reason=None and nothing else — a Brain-quality failure
            # indistinguishable from a quiet market. Surfaced here so no
            # degraded call is ever reasonless.
            "degraded_reason": degraded_reason(source, output, fallback_reason),
            "normalization_notes": norm_notes,
            "repair_attempted": repaired,
            # BRAIN-FAMILY-REPAIR (2026-07-09) — soft family-repair telemetry
            "family_repair_attempted": family_repair_attempted,
            "family_repair_fixed": family_repair_fixed,
            # BRAIN-INVALIDATION-REPAIR (2026-07-10) — soft repair audit trail
            "invalidation_repair_attempted": invalidation_repair_attempted,
            "invalidation_repair_fixed": invalidation_repair_fixed,
            # BRAIN-INVALIDATION-SIDE-CHECK (2026-07-12) — initial-read guard
            "invalidation_side_check_flagged": side_check_flagged,
            "invalidation_side_check_stripped": side_check_stripped,
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
