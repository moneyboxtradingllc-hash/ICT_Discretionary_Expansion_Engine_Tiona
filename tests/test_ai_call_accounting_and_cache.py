"""Per-request AI accounting, prompt-cache structure, and no-extra-billing.

The 2026-08-10 usage audit could account for 116 of 175 dashboard requests. The
gap was not a mystery of the market -- it was three missing facts:

  * the shadow adjudicator wrote NOTHING durable (module-memory only)
  * a per-SCAN artifact cannot represent a scan that made 2-4 requests
  * no request carried an id, so no local row could be matched to a dashboard
    line, or quoted to support after a timeout

Everything here is offline. NO TEST MAY CONTACT OPENAI: every client is a stub,
and one test asserts by construction that instrumentation cannot add a call.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from ai_brain import ai_call_ledger as L                 # noqa: E402
from ai_brain import narrative_brain as nb               # noqa: E402


# ── stub venue ────────────────────────────────────────────────────────────────
class _Usage:
    def __init__(self, prompt=1000, cached=0, completion=100, reasoning=None,
                 cache_write=0):
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = prompt + completion
        self.prompt_tokens_details = type(
            "P", (), {"cached_tokens": cached, "cache_write_tokens": cache_write})()
        self.completion_tokens_details = type(
            "C", (), {"reasoning_tokens": reasoning})()


class _Resp:
    def __init__(self, content='{"narrative_direction": "bearish"}', usage=None,
                 model="gpt-5.6-terra"):
        self.choices = [type("Ch", (), {"message": type("M", (), {"content": content})()})()]
        self.usage = usage
        self.id = "resp_abc123"
        self.model = model


class _Raw:
    """Mimics `with_raw_response`: exposes headers, parses to the response."""

    def __init__(self, resp, headers=None):
        self._resp = resp
        self.headers = headers if headers is not None else {"x-request-id": "req_srv_1"}

    def parse(self):
        return self._resp


class StubCompletions:
    def __init__(self, resp=None, raise_with=None, support_raw=True):
        self.resp = resp or _Resp(usage=_Usage())
        self.raise_with = raise_with
        self.calls = []
        self._support_raw = support_raw
        if support_raw:
            outer = self

            class _WRR:
                def create(self, **kw):
                    outer.calls.append(kw)
                    if outer.raise_with:
                        raise outer.raise_with
                    return _Raw(outer.resp)
            self.with_raw_response = _WRR()

    def create(self, **kw):
        self.calls.append(kw)
        if self.raise_with:
            raise self.raise_with
        return self.resp


def stub_module(completions):
    chat = type("Chat", (), {"completions": completions})()
    client = type("Client", (), {"__init__": lambda self, **kw: setattr(self, "chat", chat)})
    return type("Mod", (), {"OpenAI": client})


@pytest.fixture
def ledger_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_BRAIN_DIR", str(tmp_path))
    return str(tmp_path)


@pytest.fixture
def brain(monkeypatch):
    import ai_layer.ai_api_adapter as adapter
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("AI_BRAIN_MODEL", "gpt-5.6-terra")
    monkeypatch.setattr(adapter, "_OPENAI_AVAILABLE", True)

    def install(completions):
        monkeypatch.setattr(adapter, "_openai", stub_module(completions))
        return completions
    return install


def rows(session=""):
    return L.load(session)


# ══════════════════════════════════════════════════════════════════════════════
class TestCacheStructure:
    """Phase 4/5: caching must not change what the model reads."""

    def test_1_the_stable_prefix_is_byte_identical_across_scans(self, brain, ledger_dir):
        c = brain(StubCompletions())
        nb._call_llm({"timestamp": "t1", "market": {"current_price": 1}})
        nb._call_llm({"timestamp": "t2", "market": {"current_price": 2}})
        a, b = c.calls[0]["messages"][0], c.calls[1]["messages"][0]
        assert a["role"] == b["role"] == "system"
        assert a["content"] == b["content"], "the cacheable prefix drifted"

    def test_2_the_dynamic_suffix_changes_without_touching_the_prefix(self, brain,
                                                                     ledger_dir):
        c = brain(StubCompletions())
        nb._call_llm({"timestamp": "t1"})
        nb._call_llm({"timestamp": "t2"})
        assert c.calls[0]["messages"][1] != c.calls[1]["messages"][1]
        assert c.calls[0]["messages"][0] == c.calls[1]["messages"][0]

    def test_3_primary_sends_a_stable_cache_key(self, brain, ledger_dir):
        c = brain(StubCompletions())
        nb._call_llm({"timestamp": "t1"})
        nb._call_llm({"timestamp": "t2"})
        keys = {k["prompt_cache_key"] for k in c.calls}
        assert len(keys) == 1, "a per-scan key guarantees a cache miss"
        key = keys.pop()
        assert key.startswith("expbot-primary-")
        assert L.PROMPT_DOCTRINE_VERSION in key

    def test_the_key_excludes_session_scan_and_time(self, brain, ledger_dir):
        c = brain(StubCompletions())
        nb.set_call_context(session_id="PROD-A", scan=1)
        nb._call_llm({"timestamp": "t1"})
        nb.set_call_context(session_id="PROD-B", scan=99)
        nb._call_llm({"timestamp": "t2"})
        nb.set_call_context()
        assert c.calls[0]["prompt_cache_key"] == c.calls[1]["prompt_cache_key"]

    def test_4_shadow_uses_a_different_key_from_primary(self):
        assert L.cache_key(role=L.PRIMARY, model="m") != \
            L.cache_key(role=L.SHADOW, model="m")

    def test_the_key_changes_when_the_doctrine_version_changes(self):
        a = L.cache_key(role=L.PRIMARY, model="m", doctrine_version="1")
        b = L.cache_key(role=L.PRIMARY, model="m", doctrine_version="2")
        assert a != b, "a changed prefix must not reuse an old cache"

    def test_5_the_stable_prefix_precedes_all_dynamic_content(self, brain, ledger_dir):
        """The breakpoint is the system/user boundary: message 0 is fully
        static, message 1 is fully per-scan."""
        c = brain(StubCompletions())
        nb._call_llm({"timestamp": "t", "market": {"current_price": 9}})
        msgs = c.calls[0]["messages"]
        assert msgs[0]["role"] == "system" and msgs[1]["role"] == "user"
        assert "current_price" not in msgs[0]["content"]
        assert json.loads(msgs[1]["content"])["market"]["current_price"] == 9

    def test_semantics_are_unchanged_by_the_cache_work(self, brain, ledger_dir):
        """Phase 5: the rendered prompt still carries the same instructions and
        the same market facts, in the same authority order."""
        from ai_brain.brain_prompt import BRAIN_SYSTEM_PROMPT
        c = brain(StubCompletions())
        payload = {"timestamp": "t", "market": {"current_price": 42},
                   "liquidity": {"active_draw": {"level": 7}}}
        nb._call_llm(payload)
        msgs = c.calls[0]["messages"]
        assert msgs[0]["content"] == BRAIN_SYSTEM_PROMPT
        assert json.loads(msgs[1]["content"]) == payload


class TestDurableAccounting:
    """Phases 6-8."""

    def test_6_7_8_a_primary_call_writes_exactly_one_row(self, brain, ledger_dir):
        brain(StubCompletions(_Resp(usage=_Usage(prompt=9000, cached=4000,
                                                 completion=500, reasoning=120,
                                                 cache_write=256))))
        nb.set_call_context(session_id="PROD-X", scan=7)
        nb._call_llm({"timestamp": "t"})
        nb.set_call_context()
        r = rows("PROD-X")
        assert len(r) == 1
        row = r[0]
        assert row["brain_role"] == L.PRIMARY
        assert row["call_purpose"] == L.PURPOSE_PRIMARY
        assert row["session_id"] == "PROD-X" and row["scan"] == 7
        assert row["prompt_tokens"] == 9000
        assert row["cached_tokens"] == 4000
        assert row["uncached_input_tokens"] == 5000
        assert row["cache_write_tokens"] == 256
        assert row["completion_tokens"] == 500
        assert row["reasoning_tokens"] == 120
        assert row["request_id"] == "req_srv_1"
        assert row["response_id"] == "resp_abc123"
        assert row["client_request_id"].startswith("PROD-X-s7-primary-")
        assert row["ok"] is True
        assert row["prompt_cache_key"]
        assert row["latency_seconds"] is not None

    def test_9_the_server_request_id_is_persisted(self, brain, ledger_dir):
        brain(StubCompletions())
        nb.set_call_context(session_id="S9", scan=1)
        nb._call_llm({"timestamp": "t"})
        nb.set_call_context()
        assert rows("S9")[0]["request_id"] == "req_srv_1"

    def test_10_client_request_ids_are_unique(self, brain, ledger_dir):
        c = brain(StubCompletions())
        nb.set_call_context(session_id="S10", scan=1)
        for _ in range(5):
            nb._call_llm({"timestamp": "t"})
        nb.set_call_context()
        ids = [k["extra_headers"][L.CLIENT_REQUEST_HEADER] for k in c.calls]
        assert len(set(ids)) == 5

    def test_the_client_id_is_sent_as_a_header(self, brain, ledger_dir):
        c = brain(StubCompletions())
        nb._call_llm({"timestamp": "t"})
        assert L.CLIENT_REQUEST_HEADER in c.calls[0]["extra_headers"]

    def test_13_a_repair_is_classified_separately(self, brain, ledger_dir):
        """Purpose is derived from the repair dict, not from a new kwarg.

        `_call_llm`'s signature is a contract every existing test double
        depends on (`lambda bi, repair=None`), so the purpose rides the repair
        payload the callers already build.
        """
        assert nb._purpose_for(None) == L.PURPOSE_PRIMARY
        assert nb._purpose_for({}) == L.PURPOSE_PRIMARY, "empty is not a repair"
        assert nb._purpose_for({"previous": {}, "errors": []}) ==             L.PURPOSE_JSON_REPAIR, "an unlabelled repair is the JSON repair"
        assert nb._purpose_for({"purpose": L.PURPOSE_FAMILY_REPAIR}) ==             L.PURPOSE_FAMILY_REPAIR
        assert nb._purpose_for({"purpose": L.PURPOSE_INVALIDATION_REPAIR}) ==             L.PURPOSE_INVALIDATION_REPAIR

    def test_13b_the_repair_template_defect_is_fixed(self, brain, ledger_dir):
        """Was a PIN of a live defect; now a regression guard.

        `REPAIR_PROMPT_TEMPLATE` embedded a literal JSON example with
        unescaped braces, so `str.format()` raised KeyError before any request
        left the process -- every repair path was inert. Fixed under
        REPAIR-PATH-RESTORATION; this proves a repair call now reaches
        transport and is billed as a repair, not as a primary.
        """
        c = brain(StubCompletions())
        nb.set_call_context(session_id="S13B", scan=3)
        out = nb._call_llm({"timestamp": "t"},
                           repair={"purpose": L.PURPOSE_FAMILY_REPAIR,
                                   "previous": {}, "errors": ["e"]})
        nb.set_call_context()
        assert out["fallback_reason"] is None or "KeyError" not in str(
            out["fallback_reason"])
        assert len(c.calls) == 1, "the repair must reach transport exactly once"
        assert rows("S13B")[0]["call_purpose"] == L.PURPOSE_FAMILY_REPAIR


class TestNoDuplicateBilling:
    """Phase 9/16: instrumentation must never add a request."""

    def test_20_a_normal_scan_invokes_the_model_exactly_once(self, brain,
                                                             ledger_dir):
        c = brain(StubCompletions())
        nb._call_llm({"timestamp": "t"})
        assert len(c.calls) == 1

    def test_16_recording_does_not_trigger_another_call(self, brain, ledger_dir):
        c = brain(StubCompletions())
        nb.set_call_context(session_id="S16", scan=1)
        nb._call_llm({"timestamp": "t"})
        nb.set_call_context()
        assert len(c.calls) == 1 and len(rows("S16")) == 1

    def test_an_unwritable_ledger_does_not_retry_or_raise(self, brain, tmp_path,
                                                          monkeypatch):
        blocked = tmp_path / "occupied"
        blocked.write_text("not a directory")
        monkeypatch.setenv("AI_BRAIN_DIR", str(blocked))
        c = brain(StubCompletions())
        out = nb._call_llm({"timestamp": "t"})
        assert len(c.calls) == 1, "a ledger failure caused a second request"
        assert out["raw_response"] is not None

    def test_the_raw_response_fallback_does_not_double_call(self, brain,
                                                            ledger_dir):
        """A client without `with_raw_response` must be called once, not twice."""
        c = brain(StubCompletions(support_raw=False))
        nb._call_llm({"timestamp": "t"})
        assert len(c.calls) == 1

    def test_max_retries_is_still_zero(self):
        src = open(os.path.join(ROOT, "src", "ai_brain", "narrative_brain.py"),
                   encoding="utf-8").read()
        assert "max_retries=0" in src, "the SDK must never retry silently"

    def test_no_test_in_this_module_can_reach_openai(self):
        """Every client here is a stub: nothing imports the real SDK."""
        import ast
        tree = ast.parse(open(__file__, encoding="utf-8").read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert "openai" not in imported
        assert "httpx" not in imported and "requests" not in imported


class TestUsageBreakdown:

    @pytest.mark.parametrize("usage,expect", [
        (_Usage(prompt=1000, cached=0), {"cached_tokens": 0,
                                         "uncached_input_tokens": 1000}),
        (_Usage(prompt=1000, cached=750), {"cached_tokens": 750,
                                           "uncached_input_tokens": 250}),
    ])
    def test_input_is_split_into_billable_classes(self, usage, expect):
        out = L.usage_breakdown(usage)
        for k, v in expect.items():
            assert out[k] == v

    def test_reasoning_is_reported_but_not_re_added(self):
        out = L.usage_breakdown(_Usage(prompt=100, completion=50, reasoning=30))
        assert out["reasoning_tokens"] == 30
        assert out["completion_tokens"] == 50, "reasoning double-counted"

    def test_a_missing_usage_object_is_zeros_not_a_crash(self):
        out = L.usage_breakdown(None)
        assert out["prompt_tokens"] == 0 and out["total_tokens"] == 0


class TestSummary:
    """Phase 10: the operator can cost this without guessing."""

    def test_roles_purposes_and_cache_ratio(self, ledger_dir):
        for role, purpose, cached in ((L.PRIMARY, L.PURPOSE_PRIMARY, 400),
                                      (L.PRIMARY, L.PURPOSE_FAMILY_REPAIR, 0),
                                      (L.SHADOW, L.PURPOSE_ADJUDICATION, 100)):
            L.record(session_id="SUM", role=role, purpose=purpose,
                     usage=_Usage(prompt=1000, cached=cached, completion=100))
        s = L.summarize(L.load("SUM"))
        assert s["requests_total"] == 3
        assert s["requests_primary"] == 2 and s["requests_shadow"] == 1
        assert s["requests_repair"] == 1
        assert s["input_tokens_total"] == 3000
        assert s["cached_input_tokens"] == 500
        assert s["uncached_input_tokens"] == 2500
        assert s["cache_hit_requests"] == 2 and s["cache_miss_requests"] == 1
        assert s["cache_hit_ratio_by_tokens"] == round(500 / 3000, 4)

    def test_a_failed_row_is_counted_as_failed(self, ledger_dir):
        L.record(session_id="F", role=L.SHADOW, ok=False,
                 fallback_reason="timeout")
        assert L.summarize(L.load("F"))["requests_failed"] == 1


class TestPrimaryOnlyBaseline:
    """XXII: shadow OFF for the baseline sessions. Zero shadow model calls.

    Not a deletion -- the shadow architecture and its v7 ledger stay intact.
    The point is a clean measurement of the repaired primary organism without
    a second brain as an uncontrolled variable.
    """

    def test_34_primary_only_mode_makes_zero_shadow_calls(self, monkeypatch,
                                                          ledger_dir):
        from ai_brain import two_brain as TB
        monkeypatch.setenv("TWO_BRAIN_MODE", "off")

        called = []
        monkeypatch.setattr(TB, "accounted_adjudicator",
                            lambda *a, **k: called.append(1))
        observer = TB.ShadowObserver(adjudicator=TB.accounted_adjudicator)
        out = observer.observe(
            snapshot={}, brain_input={"market": {"current_price": 100.0}},
            deterministic_thesis={"narrative_direction": "bearish"},
            objective_catalog=[], invalidation_catalog=[], snapshot_id="s1")
        assert called == [], "a shadow model call was made in primary-only mode"
        assert not L.load("SHADOW-OFF")

    def test_the_scan_cycle_skips_shadow_entirely_when_mode_is_off(self,
                                                                  monkeypatch):
        from live_scan.production_scan_cycle import ProductionScanCycle
        monkeypatch.setenv("TWO_BRAIN_MODE", "off")
        cycle = ProductionScanCycle.__new__(ProductionScanCycle)
        assert cycle._two_brain_shadow({"timestamp": "t"}) is None

    def test_35_the_shadow_architecture_is_retained_not_deleted(self):
        from ai_brain import two_brain as TB
        for name in ("ShadowObserver", "accounted_adjudicator",
                     "shadow_adjudication_cap", "ADJUDICATION_ACCOUNTING",
                     "SHADOW"):
            assert hasattr(TB, name), name
        assert hasattr(TB.ShadowObserver(), "budget"), "v7 budget telemetry lost"

    def test_shadow_budget_reports_zero_when_unused(self):
        from ai_brain.two_brain import ShadowObserver
        b = ShadowObserver().budget()
        assert b["shadow_calls_used"] == 0
        assert b["shadow_tokens_used"] == 0
        assert b["shadow_calls_allowed"] >= 0
