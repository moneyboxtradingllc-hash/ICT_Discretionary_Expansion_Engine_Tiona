"""The brain-on path, exercised end to end without a network call.

We cannot make LLM calls right now, but everything around the call is ours and
must be provably correct before the key goes back in: payload assembly, the
request shape, JSON extraction, schema validation, the repair turn, and the
degraded-fallback contract.

The seam is `ai_layer.ai_api_adapter._openai` — narrative_brain._call_llm builds
its own client from that module attribute, so substituting it exercises the real
code path with a scripted response.

What this pins down:
  - the payload the brain receives carries a real multi-bar window per timeframe
    (the `candles` vs `recent_candles` key mismatch shipped one bar per TF and
    reported nothing in degraded[])
  - structure reaches the LLM as non-directional witness only
  - a well-formed response validates and is consumed
  - a malformed response never becomes a silent success
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ai_brain.brain_input import build_brain_input
from ai_brain.brain_schema import empty_brain_output


# ── a scripted model, standing in for the API ────────────────────────────────
class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]
        self.usage = None


class _Completions:
    def __init__(self, script):
        self._script = script
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Resp(self._script)


class _Chat:
    def __init__(self, script):
        self.completions = _Completions(script)


class _Client:
    def __init__(self, script):
        self.chat = _Chat(script)


class _FakeOpenAI:
    """Mimics the module object narrative_brain imports as `_openai`."""

    def __init__(self, script):
        self._script = script
        self.last_client = None

    def OpenAI(self, **kwargs):  # noqa: N802 - matches the SDK's name
        self.last_client = _Client(self._script)
        return self.last_client


def _valid_brain_json(**overrides) -> str:
    out = empty_brain_output()
    out.update({
        "market_story": "Sell-side raid rejected, price delivering back into premium.",
        "narrative_direction": "bearish",
        "narrative_phase": "distribution",
        "phase_confidence": 72,
        "current_action": "wait_for_retracement",
        "reason": "awaiting retracement into the 5m bearish order block",
        "allowed_direction": "bearish",
    })
    out.update(overrides)
    return json.dumps(out)


@pytest.fixture
def brain_on(monkeypatch):
    monkeypatch.setenv("AI_BRAIN_ENABLED", "true")
    monkeypatch.setenv("AI_BRAIN_LLM", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")

    def _install(script):
        import ai_layer.ai_api_adapter as adapter
        fake = _FakeOpenAI(script)
        monkeypatch.setattr(adapter, "_openai", fake, raising=False)
        monkeypatch.setattr(adapter, "_OPENAI_AVAILABLE", True, raising=False)
        return fake

    return _install


# ── a snapshot shaped like the live one ──────────────────────────────────────
def _tf_block(base, step, n=5):
    candles = []
    for i in range(n):
        o = base + i * step
        c = o + step
        candles.append({"timestamp": f"2026-07-24T13:{40 + i:02d}:00-04:00",
                        "open": o, "high": max(o, c) + 2, "low": min(o, c) - 2,
                        "close": c, "volume": 100})
    return {"recent_candles": candles, "last_candle": candles[-1]}


def _snapshot():
    return {
        "timestamp": "2026-07-24T13:52:00-04:00",
        "session": "afternoon",
        "timeframes": {"15m": _tf_block(28600, -20), "5m": _tf_block(28560, -12),
                       "3m": _tf_block(28540, -8), "1m": _tf_block(28530, -4)},
        "structure": {tf: {"bias": "bullish", "last_swing_high": 28632.0,
                           "last_swing_low": 28427.0, "bos": False, "mss": True}
                      for tf in ("15m", "5m", "3m", "1m")},
        "po3": {"15m": {"phase": "distribution", "manipulation_direction": "bearish",
                        "distribution_direction": "bearish"}},
        "liquidity": {"5m": {"sweep_detected": True, "sweep_direction": "below_low",
                             "reclaim_detected": True,
                             "nearest_buy_side_liquidity": 28632.0,
                             "nearest_sell_side_liquidity": 28427.0}},
        "narrative_authority": {"active_liquidity_draw": {"side": "sell_side",
                                                          "level": 28427.0},
                                "conflict_flags": [], "warnings": []},
        "protected_swings": {"protected_low": {"level": 28427.0, "timeframe": "5m"}},
        "market_regime": {"volatility_state": "stable", "expansion_state": "early_expansion",
                          "regime_label": "range_rotation"},
        "shared_context": {"delivery_state": "bearish_delivery", "delivery_confidence": 70},
        "playbook": {"selected_playbook": "no_playbook", "direction": None},
        "toolbox": {"tool_candidates": []},
    }


class TestThePayloadWeWouldSend:
    def test_every_timeframe_carries_a_real_window(self):
        """The regression: `candles` is not the producer key, `recent_candles` is."""
        bi = build_brain_input(_snapshot(), {})
        for tf in ("15m", "5m", "3m", "1m"):
            assert len(bi["market"]["candles"][tf]["recent"]) == 5, tf

    def test_a_single_bar_window_is_declared_degraded(self):
        """Silent starvation is the failure mode this module exists to prevent."""
        snap = _snapshot()
        for tf in snap["timeframes"].values():
            tf.pop("recent_candles")
        bi = build_brain_input(snap, {})
        assert any(d.startswith("single_bar_only") for d in bi["degraded"])

    def test_structure_reaches_the_model_without_a_direction(self):
        bi = build_brain_input(_snapshot(), {})
        witness = json.dumps(bi["STRUCTURE_WITNESS"])
        assert "bullish" not in witness and "bearish" not in witness
        assert bi["STRUCTURE_WITNESS"]["5m"]["last_swing_high"] == 28632.0


class TestTheCallWeWouldMake:
    def test_a_valid_response_is_parsed_and_returned(self, brain_on):
        fake = brain_on(_valid_brain_json())
        from ai_brain.narrative_brain import _call_llm
        rec = _call_llm(build_brain_input(_snapshot(), {}))
        assert rec["fallback_reason"] is None
        assert rec["ok"] is True
        assert rec["parsed"]["narrative_direction"] == "bearish"

    def test_the_request_carries_system_and_user_roles(self, brain_on):
        fake = brain_on(_valid_brain_json())
        from ai_brain.narrative_brain import _call_llm
        _call_llm(build_brain_input(_snapshot(), {}))
        sent = fake.last_client.chat.completions.calls[0]
        roles = [m["role"] for m in sent["messages"]]
        assert roles == ["system", "user"]
        assert json.loads(sent["messages"][1]["content"])["market"]["current_price"]

    def test_malformed_output_is_never_a_silent_success(self, brain_on):
        brain_on("not json at all")
        from ai_brain.narrative_brain import _call_llm
        rec = _call_llm(build_brain_input(_snapshot(), {}))
        assert rec["ok"] is False
        assert rec["parsed"] is None
        assert rec["fallback_reason"]

    def test_no_api_key_degrades_instead_of_raising(self, brain_on, monkeypatch):
        brain_on(_valid_brain_json())
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from ai_brain.narrative_brain import _call_llm
        rec = _call_llm(build_brain_input(_snapshot(), {}))
        assert rec["ok"] is False
        assert rec["fallback_reason"] == "no_api_key"


class TestBrainOffIsUnchanged:
    def test_disabled_brain_returns_the_observe_only_shell(self, monkeypatch):
        monkeypatch.setenv("AI_BRAIN_ENABLED", "false")
        from ai_brain.narrative_brain import run_narrative_brain
        out = run_narrative_brain(_snapshot(), "MNQ SEP26", None)
        assert out["enabled"] is False
        assert out["authority"] == "observe_only"
        assert out["output"] is None
