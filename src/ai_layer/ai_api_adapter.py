"""
AI API Adapter — Phase 1N.1.
Real OpenAI API call with timeout, error handling, and graceful fallback.
No execution, no broker routing, no order placement.

Strategy:
  1. Try OpenAI Responses API (preferred for SDK v2.x)
  2. Fall back to Chat Completions if Responses API unavailable
  3. Fall back to deterministic_internal_ai on any failure
"""

import json
import os
import time

from dotenv import load_dotenv

# Load .env so OPENAI_API_KEY and other vars are available before the first call.
# load_dotenv() does not override vars already set at the OS/shell level.
load_dotenv()

# ── Optional openai import ────────────────────────────────────────────────────
# Handled here so the adapter returns a clean fallback even if the package
# is missing, rather than crashing the trading engine at import time.

try:
    import openai as _openai
    _OPENAI_AVAILABLE = True
except ImportError:
    _openai = None          # type: ignore[assignment]
    _OPENAI_AVAILABLE = False

# ── Environment variable names ────────────────────────────────────────────────

_KEY_ENV      = "OPENAI_API_KEY"
_PROVIDER_ENV = "AI_PROVIDER"
_MODEL_ENV    = "AI_MODEL"
_TIMEOUT_ENV  = "AI_TIMEOUT_SECONDS"

_DEFAULT_PROVIDER = "openai"
_DEFAULT_MODEL    = "gpt-4o-mini"
_DEFAULT_TIMEOUT  = 30   # seconds — gpt-5-mini and similar models need ~20-25s for structured JSON

# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """
You are a professional ICT (Inner Circle Trader) market analyst integrated into a
discretionary trading engine. You receive a structured snapshot of market evidence
and must return a discretionary interpretation as valid JSON.

Output ONLY valid JSON matching this exact schema — no prose, no markdown:
{
  "agreement_with_playbook": <bool>,
  "agreement_with_risk": <bool>,
  "ai_direction": "<bullish|bearish|neutral|conflicted>",
  "ai_confidence": <integer 0-100>,
  "market_story": "<string>",
  "primary_thesis": "<string>",
  "concerns": ["<string>", ...],
  "missing_evidence": ["<string>", ...],
  "invalidation_thesis": "<string>",
  "preferred_scenario": "<string>",
  "alternative_scenario": "<string>"
}

Rules:
- Do NOT recommend specific trade entries or exits
- Do NOT override the Risk Governor decision
- Focus on market structure, liquidity sweeps, PO3 phase, and expansion context
- Be specific about price levels when discussing the invalidation thesis
- agreement_with_risk=true means you agree with the risk verdict, not that you advocate trading
- Keep all string fields concise (1-3 sentences)
""".strip()


# ── Config accessor ───────────────────────────────────────────────────────────

def get_ai_config() -> dict:
    """Return current AI configuration from environment variables."""
    return {
        "provider":        os.getenv(_PROVIDER_ENV, _DEFAULT_PROVIDER),
        "model":           os.getenv(_MODEL_ENV,    _DEFAULT_MODEL),
        "timeout":         int(os.getenv(_TIMEOUT_ENV, str(_DEFAULT_TIMEOUT))),
        "api_key_present": bool(os.getenv(_KEY_ENV)),
    }


# ── Result builders ───────────────────────────────────────────────────────────

def _fallback(reason: str, latency_ms: int | None = None) -> dict:
    return {
        "fallback_required": True,
        "fallback_reason":   reason,
        "response":          None,
        "latency_ms":        latency_ms,
        "model_used":        None,
    }


def _success(response: dict, latency_ms: int, model_used: str) -> dict:
    return {
        "fallback_required": False,
        "fallback_reason":   None,
        "response":          response,
        "latency_ms":        latency_ms,
        "model_used":        model_used,
    }


# ── JSON extraction ───────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict | None:
    """
    Extract the first valid JSON object from a model response string.
    Handles: clean JSON, markdown code blocks, JSON embedded in prose.
    """
    if not text:
        return None

    text = text.strip()

    # 1 — Direct parse (JSON mode response or clean output)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2 — Strip markdown code fence if present
    for fence in ("```json", "```"):
        if fence in text:
            start = text.find(fence) + len(fence)
            end   = text.find("```", start)
            if end > start:
                try:
                    return json.loads(text[start:end].strip())
                except json.JSONDecodeError:
                    pass

    # 3 — Extract first { ... } block from prose
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    return None


# ── API call implementations ──────────────────────────────────────────────────

def _call_responses_api(client, model: str, compact_input: dict, timeout: float) -> str:
    """
    OpenAI Responses API — preferred for SDK v2.x.
    Uses client.responses.create() with instructions + input pattern.
    Timeout passed per-call to override any client-level default.
    """
    resp = client.responses.create(
        model=model,
        instructions=_SYSTEM_PROMPT,
        input=json.dumps(compact_input, indent=2, default=str),
        timeout=timeout,
    )
    # output_text is a convenience property in SDK v2.x
    if hasattr(resp, "output_text") and resp.output_text:
        return resp.output_text
    # Fallback traversal for alternate response shapes
    if hasattr(resp, "output") and resp.output:
        first = resp.output[0]
        if hasattr(first, "content") and first.content:
            item = first.content[0]
            if hasattr(item, "text"):
                return item.text or ""
    return ""


def _call_chat_completions(client, model: str, compact_input: dict, timeout: float) -> str:
    """
    OpenAI Chat Completions — universally supported across all SDK versions.
    Used when the Responses API is not available.
    Timeout passed per-call to override any client-level default.
    temperature is omitted — some models (e.g. gpt-5-mini) only accept the default value.
    """
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": json.dumps(compact_input, indent=2, default=str)},
        ],
        timeout=timeout,
    )
    return resp.choices[0].message.content or ""


def _get_content(client, model: str, compact_input: dict, timeout: float) -> str:
    """
    Chat Completions is the primary path — reliable timeout behavior across all SDK versions.
    Responses API is attempted as an upgrade if Chat Completions raises AttributeError
    (which would only happen in unusual SDK configurations).

    Note: The Responses API uses SSE streaming by default which can make the SDK-level
    timeout unreliable (the timeout applies per-chunk, not to the full response duration).
    Per the Phase 1N.1 directive: "If Responses API causes issues, use the safest
    supported OpenAI SDK method available."
    """
    try:
        return _call_chat_completions(client, model, compact_input, timeout)
    except AttributeError:
        # client.chat not available (unusual) — fall back to Responses API
        return _call_responses_api(client, model, compact_input, timeout)


# ── Public entry point ────────────────────────────────────────────────────────

def call_external_ai(compact_input: dict) -> dict:
    """
    Attempt an external OpenAI API call with the compact snapshot input.

    Returns:
      fallback_required : bool  — True if caller should use deterministic AI
      fallback_reason   : str   — why fallback was triggered (or None)
      response          : dict  — parsed AI response (or None on failure)
      latency_ms        : int   — round-trip latency in milliseconds (or None)
      model_used        : str   — actual model used (or None on failure)
    """
    if not _OPENAI_AVAILABLE:
        return _fallback("openai_package_not_installed")

    cfg = get_ai_config()

    if not cfg["api_key_present"]:
        return _fallback("OPENAI_API_KEY missing")

    api_key = os.getenv(_KEY_ENV)
    model   = cfg["model"]
    timeout = cfg["timeout"]

    t0 = time.monotonic()
    try:
        # max_retries=0 so the configured timeout fires on the first attempt only
        # (SDK default is 2 retries, which multiplies apparent latency by 3)
        client  = _openai.OpenAI(api_key=api_key, timeout=float(timeout), max_retries=0)
        content = _get_content(client, model, compact_input, float(timeout))
        latency_ms = round((time.monotonic() - t0) * 1000)

        if not content:
            return _fallback("empty_response", latency_ms)

        parsed = _extract_json(content)
        if parsed is None:
            return _fallback("response_parse_failed", latency_ms)

        return _success(parsed, latency_ms, model_used=model)

    except _openai.APITimeoutError:
        return _fallback("timeout",               round((time.monotonic() - t0) * 1000))
    except _openai.AuthenticationError:
        return _fallback("authentication_failed", round((time.monotonic() - t0) * 1000))
    except _openai.RateLimitError:
        return _fallback("rate_limit",            round((time.monotonic() - t0) * 1000))
    except _openai.APIConnectionError:
        return _fallback("connection_error",      round((time.monotonic() - t0) * 1000))
    except _openai.APIStatusError as exc:
        # Include a short excerpt of the error body for diagnosability
        body = getattr(exc, "body", None) or {}
        err_msg = body.get("message", str(exc))[:120] if isinstance(body, dict) else str(exc)[:120]
        reason = f"api_error:{exc.status_code} — {err_msg}"
        return _fallback(reason, round((time.monotonic() - t0) * 1000))
    except _openai.OpenAIError as exc:
        return _fallback(f"openai:{type(exc).__name__}", round((time.monotonic() - t0) * 1000))
    except Exception as exc:
        return _fallback(f"error:{type(exc).__name__}", round((time.monotonic() - t0) * 1000))
