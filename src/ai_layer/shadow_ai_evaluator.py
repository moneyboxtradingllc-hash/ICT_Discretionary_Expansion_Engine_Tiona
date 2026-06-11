"""
Phase AI-SHADOW — Fable 5 Shadow AI Evaluator.

GPT-4o-mini remains the live execution AI. Fable 5 (Anthropic) receives the
SAME compact snapshot input, produces a shadow recommendation, and is scored
against outcomes. Evidence before authority: it watches first.

CONSTITUTION (immutable for this phase):
  - Shadow output NEVER enters execution_gate, order_builder, or
    trade_manager. It lives in snapshot["ai_shadow"] and data/ai_shadow/.
  - Any shadow failure (error, timeout, invalid output, missing key) leaves
    live trading completely unaffected.
  - No approval, no blocking, no delay, no execution influence.

Env:
  AI_SHADOW_ENABLED          default false
  AI_SHADOW_MODE             default setups_only   ("setups_only" | "every_scan")
  AI_PROVIDER_SHADOW         default anthropic
  AI_MODEL_SHADOW            default claude-fable-5
  AI_SHADOW_TIMEOUT_SECONDS  default 10
  ANTHROPIC_API_KEY          required for live calls (fails open if absent)

setups_only fires the shadow ONLY when there is something worth a second
opinion: qualification reached candidate-or-better, a setup lifecycle is
active, or the decision is ready/prepare. Dormant scans (both AIs trivially
agree on "nothing here") are skipped — ~70-80% cost reduction with no loss
of decision-relevant evidence. Every submitted trade always has a shadow
stance, because submission requires exactly those states.
"""
import json
import os
import time
from datetime import datetime

import pytz
import requests

from ai_layer.ai_input_builder import build_compact_ai_input

_EASTERN = pytz.timezone("America/New_York")

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

_VALID_STANCES = ("long", "short", "no_trade", "stand_down")

_PROMPT_TEMPLATE = """You are the shadow market evaluator for a paper-trading system on {symbol}.
You see the same data as the live AI. Give YOUR independent read.

Market input (same compact snapshot the live AI receives):
{compact_input}

Respond with STRICT JSON only, no prose, exactly this schema:
{{"stance": "long|short|no_trade|stand_down", "confidence": 0-100,
  "reasons": ["..."], "concerns": ["..."]}}

stance meanings: long/short = directional opportunity now; no_trade = no
opportunity present; stand_down = conditions actively hostile."""


def _enabled() -> bool:
    return os.getenv("AI_SHADOW_ENABLED", "false").lower().strip() == "true"


def _mode() -> str:
    mode = os.getenv("AI_SHADOW_MODE", "setups_only").lower().strip()
    return mode if mode in ("setups_only", "every_scan") else "setups_only"


_ACTIVE_QUAL      = ("candidate", "qualified", "elite")
_ACTIVE_DECISIONS = ("ready_for_execution", "trade_authorized_false",
                     "prepare_long", "prepare_short")


def _should_fire(snapshot: dict) -> bool:
    """setups_only trigger: is there anything worth a second opinion?"""
    qual = (snapshot.get("qualification", {}) or {}).get("status", "")
    if (qual or "").lower() in _ACTIVE_QUAL:
        return True
    if (snapshot.get("setup_lifecycle", {}) or {}).get("active"):
        return True
    decision = ((snapshot.get("decision_authority", {}) or {})
                .get("decision") or "").lower()
    return decision in _ACTIVE_DECISIONS


def _model() -> str:
    return os.getenv("AI_MODEL_SHADOW", "claude-fable-5").strip()


def _timeout() -> float:
    try:
        return float(os.getenv("AI_SHADOW_TIMEOUT_SECONDS", "10"))
    except ValueError:
        return 10.0


def _shadow_dir() -> str:
    return os.getenv("AI_SHADOW_DIR", os.path.join("data", "ai_shadow"))


# ── Anthropic call ────────────────────────────────────────────────────────────

def _call_anthropic(prompt: str) -> tuple:
    """Returns (text, error). Never raises."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None, "ANTHROPIC_API_KEY not configured"
    try:
        resp = requests.post(
            _ANTHROPIC_URL,
            headers={
                "x-api-key":         api_key,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json={
                "model":      _model(),
                "max_tokens": 500,
                "messages":   [{"role": "user", "content": prompt}],
            },
            timeout=_timeout(),
        )
        if resp.status_code != 200:
            return None, f"http {resp.status_code}: {resp.text[:120]}"
        data = resp.json()
        parts = data.get("content") or []
        text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
        return text, None
    except requests.Timeout:
        return None, f"timeout after {_timeout()}s"
    except Exception as exc:  # noqa: BLE001
        return None, f"request error: {exc}"


# ── Normalization ─────────────────────────────────────────────────────────────

def _normalize(raw_text: str) -> tuple:
    """Parse + normalize the model response. Returns (result, error)."""
    try:
        text = raw_text.strip()
        # tolerate fenced output
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            return None, "no JSON object in response"
        parsed = json.loads(text[start:end + 1])

        stance = str(parsed.get("stance", "")).lower().strip().replace("-", "_")
        aliases = {"flat": "no_trade", "none": "no_trade", "neutral": "no_trade",
                   "avoid": "stand_down", "hostile": "stand_down",
                   "buy": "long", "sell": "short", "bullish": "long",
                   "bearish": "short"}
        stance = aliases.get(stance, stance)
        if stance not in _VALID_STANCES:
            return None, f"invalid stance '{stance}'"

        confidence = max(0, min(100, int(float(parsed.get("confidence", 0)))))
        reasons  = [str(r)[:160] for r in (parsed.get("reasons") or [])][:4]
        concerns = [str(c)[:160] for c in (parsed.get("concerns") or [])][:4]
        return {"stance": stance, "confidence": confidence,
                "reasons": reasons, "concerns": concerns}, None
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        return None, f"invalid output: {exc}"


def _live_stance(snapshot: dict) -> str:
    """The live AI's effective stance, mapped to shadow vocabulary."""
    debate = (snapshot.get("ai_debate", {}) or {}).get("final_verdict", {}) or {}
    stance = (debate.get("recommended_stance") or "stand_down").lower()
    return {"prepare_long": "long", "prepare_short": "short",
            "bullish_bias": "long", "bearish_bias": "short",
            "monitor": "no_trade"}.get(stance, "stand_down")


# ── Persistence ───────────────────────────────────────────────────────────────

def _persist(result: dict, symbol: str) -> None:
    """Append to data/ai_shadow/YYYYMMDD_<SYMBOL>_shadow.json. Never raises."""
    try:
        sdir = _shadow_dir()
        os.makedirs(sdir, exist_ok=True)
        date_str = datetime.now(_EASTERN).strftime("%Y%m%d")
        path = os.path.join(sdir, f"{date_str}_{symbol}_shadow.json")
        try:
            with open(path, encoding="utf-8") as f:
                entries = json.load(f).get("evaluations", [])
        except (OSError, json.JSONDecodeError):
            entries = []
        entries.append(result)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"evaluations": entries}, f, indent=1)
    except OSError:
        pass


# ── Public entry point ────────────────────────────────────────────────────────

def evaluate_shadow_ai(snapshot: dict, symbol: str) -> dict:
    """
    Run the Fable 5 shadow evaluation on the same input the live AI sees.
    OBSERVE ONLY. Never raises; failure never affects live trading.
    """
    if not _enabled():
        return {"enabled": False, "success": False, "stance": None,
                "agrees_with_live": None}
    if _mode() == "setups_only" and not _should_fire(snapshot or {}):
        # Dormant scan — no setup, no decision pressure, no second opinion
        # needed. Not persisted (skips are noise, not evidence).
        return {"enabled": True, "skipped": True, "success": False,
                "stance": None, "agrees_with_live": None,
                "reason": "setups_only: no active setup or decision"}
    try:
        return _evaluate(snapshot or {}, symbol)
    except Exception as exc:  # noqa: BLE001
        return {"enabled": True, "success": False, "stance": None,
                "agrees_with_live": None, "error": f"shadow error: {exc}",
                "provider": "Fable5"}


def _evaluate(snapshot: dict, symbol: str) -> dict:
    started = time.monotonic()

    compact = build_compact_ai_input(snapshot)
    prompt  = _PROMPT_TEMPLATE.format(
        symbol=symbol,
        compact_input=json.dumps(compact, default=str)[:6000],
    )

    raw, err = _call_anthropic(prompt)
    latency_ms = int((time.monotonic() - started) * 1000)

    live = _live_stance(snapshot)

    if err is not None:
        result = {
            "enabled": True, "provider": "Fable5", "model": _model(),
            "success": False, "error": err, "latency_ms": latency_ms,
            "stance": None, "confidence": None, "reasons": [], "concerns": [],
            "live_stance": live, "agrees_with_live": None,
            "timestamp": datetime.now(_EASTERN).strftime("%Y%m%dT%H%M%S"),
            "symbol": symbol,
        }
        _persist(result, symbol)
        return result

    normalized, err = _normalize(raw)
    if err is not None:
        result = {
            "enabled": True, "provider": "Fable5", "model": _model(),
            "success": False, "error": err, "latency_ms": latency_ms,
            "raw_excerpt": (raw or "")[:200],
            "stance": None, "confidence": None, "reasons": [], "concerns": [],
            "live_stance": live, "agrees_with_live": None,
            "timestamp": datetime.now(_EASTERN).strftime("%Y%m%dT%H%M%S"),
            "symbol": symbol,
        }
        _persist(result, symbol)
        return result

    agrees = normalized["stance"] == live

    result = {
        "enabled": True, "provider": "Fable5", "model": _model(),
        "success": True, "error": None, "latency_ms": latency_ms,
        "stance": normalized["stance"], "confidence": normalized["confidence"],
        "reasons": normalized["reasons"], "concerns": normalized["concerns"],
        "live_stance": live, "agrees_with_live": agrees,
        "timestamp": datetime.now(_EASTERN).strftime("%Y%m%dT%H%M%S"),
        "symbol": symbol,
    }
    _persist(result, symbol)
    return result


# ── Evidence: shadow vs outcomes ──────────────────────────────────────────────

def score_shadow_vs_outcomes(symbol: str, days: int = 30) -> dict:
    """
    Join journal trades (with ai_shadow_at_entry) against realized outcomes:
      avoided_loss_R   — losses where shadow said no_trade/stand_down/opposite
      missed_winner_R  — winners where shadow disagreed
      agreement counts
    OBSERVE ONLY. Never raises.
    """
    try:
        from paper_execution.trade_journal import _search_recent_files
        agreed = disagreed = 0
        avoided_loss_R = missed_winner_R = 0.0
        details = []
        for _, _, trades in _search_recent_files(symbol, days=days):
            for t in trades:
                shadow = t.get("ai_shadow_at_entry")
                r      = t.get("realized_r")
                if not shadow or r is None:
                    continue
                agrees = bool(shadow.get("agrees_with_live"))
                if agrees:
                    agreed += 1
                else:
                    disagreed += 1
                    if r < 0:
                        avoided_loss_R += abs(r)
                    elif r > 0:
                        missed_winner_R += r
                details.append({
                    "trade_id": t.get("trade_id"), "realized_r": r,
                    "live": shadow.get("live_stance"),
                    "shadow": shadow.get("stance"), "agrees": agrees,
                })
        return {
            "trades_scored":    agreed + disagreed,
            "agreed":           agreed,
            "disagreed":        disagreed,
            "avoided_loss_R":   round(avoided_loss_R, 4),
            "missed_winner_R":  round(missed_winner_R, 4),
            "net_shadow_value_R": round(avoided_loss_R - missed_winner_R, 4),
            "details":          details[-20:],
            "note": "observe-only — Fable 5 earns influence through this ledger",
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": f"shadow scoring error: {exc}"}
