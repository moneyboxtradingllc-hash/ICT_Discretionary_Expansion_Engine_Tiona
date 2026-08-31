"""10:24 CAUSAL SPECIMEN — historical structure + declared counterfactual quote.

STAGE 1. ZERO LUNA CALLS.

WHAT THIS PROVES
----------------
    the 10:23 bar settles
      -> the canonical bullish FVG 29243.00-29251.25 is BORN
      -> a DECLARED fresh executable ask establishes an interaction
      -> the shipped Unit-4 wake interrupts the ordinary deadline
      -> exactly ONE fresh production evaluation happens BECAUSE OF that wake
      -> the payload handed to the Brain is a complete, constructible trade

WHAT THIS DOES NOT PROVE
------------------------
    that the HISTORICAL executable ask entered the zone on 2026-08-21.

The archive preserved real `topstepx_realtime_quote` captures either side of the
event -- 29255.25 at 14:23:34 and 29251.50 at 14:24:51, both fresh under the
5.0s law -- but NONE inside 29243.00-29251.25 after the gap was born at
14:24:00. The 51-second post-birth window is unsampled because scan cadence was
76-78s. That absence is exactly the cadence defect Unit 4 repaired.

    THE 14:24 CANDLE LOW OF 29249.50 IS A TRADED PRICE, NOT AN ASK.

It proves traded-price geometry and authors nothing here. Manufacturing an ask
from it would be the precise substitution EXEC-PRICE-FRESHNESS-1 exists to
forbid, so the controlled ask is set to 29251.25 -- the canonical zone's own
upper boundary, the smallest DECLARED condition satisfying
"fresh executable ask is inside the zone". It is labelled counterfactual
everywhere and is never described as historical.

PROVENANCE, KEPT SPLIT
----------------------
    HISTORICAL      1m bars, FVG birth, zone geometry, contract identity,
                    structural invalidation, whatever objective the real
                    evidence carries
    COUNTERFACTUAL  best_ask 29251.25, and the synthetic companion best_bid
                    required by the QuoteCapture contract -- NOT a historical
                    spread
    OBSERVED        wake, generated evaluation, payload, counters

Nothing in production changed to make this run. The specimen composes shipped
objects: `run_production_scans`, `ProductionLoop`, `ProductionScanCycle`,
`WakeRegistry`, `annotated_timeframe`, `fvg_execution_instances` and the
execution-price freshness authority. `src/replay_validation/` is untouched --
this specimen exists precisely because replay bypasses the Unit-4 seam.
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

# ── FROZEN HISTORICAL FACTS. Evidence, not knobs. ────────────────────────────
CONTRACT = "CON.F.US.MNQ.U26"
TAPE = os.path.join(ROOT, "data", "market_data", "topstepx",
                    "CON_F_US_MNQ_U26.jsonl")
ARCHIVE = os.path.join(ROOT, "data", "ai_brain")

GAP_LOW, GAP_HIGH = 29243.00, 29251.25
GAP_C3_UTC = "2026-08-21T14:23:00+00:00"
GAP_ID = f"FVG:{CONTRACT}:1m:{GAP_C3_UTC}"
#: The 14:23 bar completes at 14:24:00Z. Before that instant it is not settled
#: and the occurrence does not exist -- that is the whole point of PRE_BIRTH.
PRE_BIRTH_LAST_BAR = "2026-08-21T14:22:00+00:00"
POST_BIRTH_LAST_BAR = "2026-08-21T14:23:00+00:00"
BIRTH_INSTANT_UTC = "2026-08-21T14:24:00+00:00"

#: HISTORICAL structural facts the payload is checked against.
EXPECTED_INVALIDATION = 29220.25      # the FVG's own c1 (14:21) bar low
EXPECTED_OBJECTIVE = 29533.75         # Luna's stated draw that session

# ── DECLARED COUNTERFACTUAL. Never historical. ───────────────────────────────
COUNTERFACTUAL_ASK = 29251.25         # the zone's upper boundary, exactly
COUNTERFACTUAL_BID = 29251.00         # synthetic companion; NOT a real spread
OUTSIDE_ASK = 29299.00                # the negative control
QUOTE_PROVENANCE = "COUNTERFACTUAL_FRESH_QUOTE"


# ══ HISTORICAL TAPE ══════════════════════════════════════════════════════════
def historical_bars(last_bar_ts: str, lookback: int = 300) -> list:
    """Completed 1m bars up to and including `last_bar_ts`. Nothing later.

    A bar dated after the cutoff is FUTURE DATA. Leaking one would let the
    specimen discover an occurrence the market had not yet produced, which is
    the one way this experiment could lie to itself.
    """
    out = []
    with open(TAPE, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("contract") and r["contract"] != CONTRACT:
                continue
            ts = str(r.get("timestamp") or "")
            if ts and ts <= last_bar_ts:
                out.append(r)
    out.sort(key=lambda r: str(r.get("timestamp")))
    return out[-lookback:]


def archived_contract() -> str:
    """The contract the Aug-21 tape itself names, read off the bars in use.

    Sourced from the same records the specimen feeds to production rather than
    asserted independently, so the identity under test cannot drift away from
    the identity of the evidence.
    """
    found = set()
    for r in historical_bars(POST_BIRTH_LAST_BAR):
        if r.get("contract"):
            found.add(str(r["contract"]))
    if len(found) != 1:
        raise RuntimeError(f"ambiguous or absent tape contract: {sorted(found)}")
    return found.pop()


# ══ CONTROLLED QUOTE — THROUGH THE REAL AUTHORITY ════════════════════════════
class FrozenQuoteProvider:
    """Shaped exactly like `LiveQuoteProvider`: `capture()` AND `__call__()`.

    Two shipped consumers read it differently and BOTH must be exercised:
        ProductionScanCycle._execution_price()  ->  self.quote_provider()
        admitted_sided_prices(ps)              ->  ps.quote_provider.capture()

    The capture is a genuine `QuoteCapture`, so it traverses the real
    `from_capture -> executable_price` law. No price is injected into
    `WakeRegistry` directly.
    """

    def __init__(self, *, ask: float, bid: float, age_seconds: float = 0.002):
        self.ask, self.bid, self.age = float(ask), float(bid), float(age_seconds)
        self.captures = 0

    def capture(self, volatility_state: str = None):
        from broker.topstepx_slippage import QuoteCapture
        self.captures += 1
        return QuoteCapture(
            captured_at=datetime.now(timezone.utc),
            best_bid=self.bid, best_ask=self.ask, last_trade=None,
            contract_id=CONTRACT, market_data_age_seconds=self.age,
            volatility_state=volatility_state or "")

    def __call__(self):
        return self.capture()

    def has_quote(self) -> bool:
        return True

    def age_seconds(self, now=None):
        return self.age


# ══ INFRASTRUCTURE SUBSTITUTES — never market judgment ═══════════════════════
class SpecimenCandles:
    """Serves the historical tape against a causally advancing clock."""

    def __init__(self):
        self.born = False
        self.contract = type("C", (), {"id": CONTRACT})()
        self.last_quote = {}          # deliberately EMPTY: the wake path must
        self.wake_registry = None     # not read it; Unit 4 removed that source
        self.fetches = 0

    def fetch_1m_candles(self, symbol=None, lookback_bars=300):
        self.fetches += 1
        cutoff = POST_BIRTH_LAST_BAR if self.born else PRE_BIRTH_LAST_BAR
        return historical_bars(cutoff, lookback=lookback_bars or 300)

    def settle_the_1023_bar(self):
        """10:24:00 ET. The bar completes and the pump signals a bar close."""
        self.born = True
        reg = self.wake_registry
        if reg is not None:
            reg.note_bar_closed()


class SpecimenRuntime:
    def health(self):
        return {"last_quote_age": 0.002, "reconnects": 0}


class BrokerReached(RuntimeError):
    """Any call to this is a Stage-1 stop condition."""


class SpecimenSession:
    """Inert identity. Every order-capable method explodes."""

    def __init__(self):
        self.account = type("A", (), {"id": 11111111})()
        self.submit_attempts = 0

    def open_positions(self):
        return []

    def open_orders(self):
        return []

    def place_order(self, *a, **k):
        self.submit_attempts += 1
        raise BrokerReached("broker transmission attempted in Stage 1")

    submit_order = modify_order = cancel_order = place_order


class SpecimenPS:
    """Inert production-session identity. Carries no market judgment."""

    def __init__(self, quote_provider, session):
        self.contract = type("C", (), {"id": CONTRACT})()
        self.quote_provider = quote_provider
        self.session = session                  # capital identity reads this
        self.account_fingerprint = "acct:specimen"
        self.slippage = type("S", (), {
            "sample_status": staticmethod(lambda: {"observations": 0})})()
        self.session_id = ""
        self.authorization_fingerprint = ""
        self.retrieval_telemetry = None


# ══ COGNITION SPY + FAIL-CLOSED EXTERNAL GUARD ═══════════════════════════════
class BrainSpy:
    """Captures what production actually hands the Brain. Trades nothing."""

    def __init__(self):
        self.requests = 0
        self.snapshots = []

    def __call__(self, snapshot, symbol, stance_memory):
        from ai_brain.brain_schema import empty_brain_output
        self.requests += 1
        self.snapshots.append(snapshot)
        out = empty_brain_output()
        out["narrative_direction"] = "neutral"     # deterministic, non-trading
        return out


class ExternalProviderReached(RuntimeError):
    """Stage 1 must be mechanically incapable of an outbound model call."""


@contextlib.contextmanager
def no_external_provider():
    """Fail CLOSED. Not 'the test shouldn't reach it' -- it cannot."""
    from ai_layer import ai_api_adapter as A

    class Detonator:
        def __getattr__(self, name):
            raise ExternalProviderReached(f"outbound provider access: {name}")

        def OpenAI(self, *a, **k):
            raise ExternalProviderReached("OpenAI client constructed")

    prior = getattr(A, "_openai", None)
    A._openai = Detonator()
    try:
        yield
    finally:
        A._openai = prior


@contextlib.contextmanager
def sandboxed(tmpdir: str):
    """Every env key and every writable evidence root, restored in `finally`.

    A leaked env key is not hypothetical: earlier in this programme a stray
    `TOPSTEPX_ACCOUNT_FINGERPRINT` made an unrelated archive-integrity test
    report a credential leak that did not exist.
    """
    import broker.trade_lineage as TL
    import topstepx_production_session as TOOL

    env = {
        "TOPSTEPX_ACCOUNT_FINGERPRINT": "acct:specimen",
        "TOPSTEPX_ACCOUNT_ID": "11111111",
        "EXECUTION_ENABLED": "false",
        "ALLOW_PAPER_ORDERS": "false",
        "AI_RETRIEVAL_ENABLED": "false",
        "NEWS_LAYER_ENABLED": "false",
        # Match the SHIPPED external production Brain configuration.
        "BRAIN_ECU_MODE": "false",
        "AI_BRAIN_DIR": os.path.join(tmpdir, "ai_brain"),
        "LIVE_SNAPSHOTS_DIR": os.path.join(tmpdir, "live_snapshots"),
        "AI_RETRIEVAL_DIR": os.path.join(tmpdir, "ai_retrieval"),
    }
    prior = {k: os.environ.get(k) for k in env}
    for d in ("ai_brain", "live_snapshots", "ai_retrieval", "store"):
        os.makedirs(os.path.join(tmpdir, d), exist_ok=True)
    os.environ.update(env)
    prior_store, prior_tape = TOOL.STORE_DIR, TL.archive_tape
    TOOL.STORE_DIR = os.path.join(tmpdir, "store")
    TL.archive_tape = lambda **k: {"bar_count": 0, "tape_write_ok": None}
    try:
        yield
    finally:
        TOOL.STORE_DIR, TL.archive_tape = prior_store, prior_tape
        for k, v in prior.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ══ THE RUN ══════════════════════════════════════════════════════════════════
def run_specimen(*, ask: float, tmpdir: str, interval: float = 8.0,
                 settle_after: float = 3.0) -> dict:
    """Drive the SHIPPED loop. Returns observations only."""
    import live_scan.production_scan_cycle as PSC
    import topstepx_production_session as TOOL

    candles = SpecimenCandles()
    quotes = FrozenQuoteProvider(ask=ask, bid=min(COUNTERFACTUAL_BID, ask - 0.25))
    session = SpecimenSession()
    ps, runtime = SpecimenPS(quotes, session), SpecimenRuntime()
    spy = BrainSpy()

    marks, started = [], time.monotonic()
    real_scan_once = None

    def pump():
        """Stands in for the market-data thread. Signals; concludes nothing."""
        time.sleep(settle_after)
        candles.settle_the_1023_bar()

    from broker.topstepx_production_loop import ProductionLoop

    class TimedLoop(ProductionLoop):
        def scan_once(self):
            marks.append(time.monotonic() - started)
            return super().scan_once()

    import broker.topstepx_production_loop as PL
    prior_loop, prior_brain = PL.ProductionLoop, PSC.run_narrative_brain
    PL.ProductionLoop = TimedLoop
    PSC.run_narrative_brain = spy

    threading.Thread(target=pump, daemon=True).start()
    results = []
    try:
        with sandboxed(tmpdir), no_external_provider():
            results = TOOL.run_production_scans(
                ps=ps, runtime=runtime, candles=candles, session=session,
                contract=candles.contract, armed=False, symbol="MNQ",
                mission_id="SPECIMEN-20260821-1024", scans=2,
                interval=interval, until_close=False)
    finally:
        PL.ProductionLoop, PSC.run_narrative_brain = prior_loop, prior_brain

    reg = candles.wake_registry
    return {
        "marks": marks,
        "gap": (marks[1] - marks[0]) if len(marks) > 1 else None,
        "interval": interval,
        # Scan 1 is the ORDINARY initial evaluation; anything beyond it in a
        # 2-scan run is caused by the wake. Reported split, never conflated.
        "evaluations_total": spy.requests,
        "evaluations_caused_by_wake": max(0, spy.requests - 1),
        "snapshots": spy.snapshots,
        "wakes": list(getattr(reg, "wakes", []) or []),
        "armed": len(reg.armed()) if reg is not None else 0,
        "armed_ids": {r[0] for r in reg.armed()} if reg is not None else set(),
        "submit_attempts": session.submit_attempts,
        "results": results,
        "captures": quotes.captures,
    }


# ══ STAGE 2 — ONE FROZEN LUNA DECISION ═══════════════════════════════════════
class BrainGate:
    """Only the WAKE-CAUSED evaluation may reach the real Luna.

    Stage 1 measured the real loop making two evaluations: an ordinary
    pre-birth scan, then the one the interaction causes. Spending the single
    authorized call on the first would answer a question about a market state
    that has no trade in it.

        #1   deterministic non-trading response, zero outbound
        #2   ONE delegation to the UNCHANGED production Brain
        #3+  hard failure
    """

    def __init__(self, real):
        self.real = real
        self.n = 0
        self.snapshots = []
        self.brain_block = None

    def __call__(self, snapshot, symbol, stance_memory):
        from ai_brain.brain_schema import empty_brain_output
        self.n += 1
        self.snapshots.append(snapshot)
        if self.n == 1:
            out = empty_brain_output()
            out["narrative_direction"] = "neutral"
            return out
        if self.n == 2:
            self.brain_block = self.real(snapshot, symbol, stance_memory)
            return self.brain_block
        raise RuntimeError(f"cognition invocation #{self.n}: one call was authorized")


@contextlib.contextmanager
def one_outbound_call_only():
    """A mechanical cap, not a promise. The second attempt raises.

    The Brain builds its own client per call, so counting constructions counts
    outbound requests -- including any internal repair attempt, which is
    therefore blocked and reported rather than silently spent.
    """
    from ai_layer import ai_api_adapter as A
    real = A._openai
    state = {"calls": 0, "blocked": 0}

    class Capped:
        def __getattr__(self, name):
            return getattr(real, name)

        def OpenAI(self, *a, **k):
            state["calls"] += 1
            if state["calls"] > 1:
                state["blocked"] += 1
                raise ExternalProviderReached(
                    f"outbound call #{state['calls']} blocked: one was authorized")
            return real.OpenAI(*a, **k)

    A._openai = Capped()
    try:
        yield state
    finally:
        A._openai = real


def run_stage2(tmpdir: str, *, interval: float = 8.0, settle_after: float = 3.0) -> dict:
    """The frozen specimen, with exactly one real Luna decision. STOPS on drift."""
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))

    from ai_brain.production_model import PRODUCTION_MODEL, resolve_model
    resolved = resolve_model(armed=False)
    if resolved != PRODUCTION_MODEL:
        raise RuntimeError(f"MODEL DRIFT: resolved {resolved!r}, "
                           f"expected {PRODUCTION_MODEL!r} -- refusing to call")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("no OPENAI_API_KEY -- refusing to call")

    import broker.topstepx_production_loop as PL
    import live_scan.production_scan_cycle as PSC
    import topstepx_production_session as TOOL
    from broker.topstepx_production_loop import ProductionLoop

    candles = SpecimenCandles()
    quotes = FrozenQuoteProvider(ask=COUNTERFACTUAL_ASK, bid=COUNTERFACTUAL_BID)
    session = SpecimenSession()
    ps, runtime = SpecimenPS(quotes, session), SpecimenRuntime()

    marks, started = [], time.monotonic()
    gate = BrainGate(PSC.run_narrative_brain)

    class TimedLoop(ProductionLoop):
        def scan_once(self):
            marks.append(time.monotonic() - started)
            return super().scan_once()

    def pump():
        time.sleep(settle_after)
        candles.settle_the_1023_bar()

    prior_loop, prior_brain = PL.ProductionLoop, PSC.run_narrative_brain
    PL.ProductionLoop, PSC.run_narrative_brain = TimedLoop, gate
    threading.Thread(target=pump, daemon=True).start()
    results, outbound = [], {}
    try:
        with sandboxed(tmpdir), one_outbound_call_only() as outbound:
            results = TOOL.run_production_scans(
                ps=ps, runtime=runtime, candles=candles, session=session,
                contract=candles.contract, armed=False, symbol="MNQ",
                mission_id="SPECIMEN-20260821-1024-STAGE2", scans=2,
                interval=interval, until_close=False)
    finally:
        PL.ProductionLoop, PSC.run_narrative_brain = prior_loop, prior_brain

    reg = candles.wake_registry
    return {
        "model": resolved,
        "outbound_calls": outbound.get("calls", 0),
        "outbound_blocked": outbound.get("blocked", 0),
        "cognition_invocations": gate.n,
        "brain_block": gate.brain_block,
        "snapshots": gate.snapshots,
        "marks": marks,
        "gap": (marks[1] - marks[0]) if len(marks) > 1 else None,
        "interval": interval,
        "wakes": list(getattr(reg, "wakes", []) or []),
        "armed_ids": {r[0] for r in reg.armed()} if reg is not None else set(),
        "submit_attempts": session.submit_attempts,
        "results": results,
    }


# ══ STAGE 3 — HISTORICAL STANCE CONTINUITY ═══════════════════════════════════
PRIOR_STANCE_ARTIFACT = "20260821_102351_MNQ.json"     # the real 10:23:51 scan


def archived_prior_stance() -> dict:
    """Luna's ACTUAL immediately-preceding thesis, read from the archive.

    The archive is authority. Nothing here hand-writes "bearish"/"stand_down"
    because we happen to know them -- the values are whatever the artifact says,
    and they are fed through the SAME `stance_memory.record(ts, output)` contract
    production uses, not assigned into private fields.
    """
    path = os.path.join(ARCHIVE, PRIOR_STANCE_ARTIFACT)
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    out = d.get("parsed_output") or {}
    ts = (d.get("raw_snapshot") or {}).get("timestamp") or d.get("timestamp") or ""
    return {"path": path, "timestamp": ts, "model": d.get("llm_model"),
            "output": out,
            "narrative_direction": out.get("narrative_direction"),
            "current_action": out.get("current_action"),
            "preferred_tools": out.get("preferred_tools")}


class BirthGatedQuotes(FrozenQuoteProvider):
    """The controlled quote does not exist until the 10:23 bar settles.

    Stage 2 constructed the quote before the loop began, so the ordinary
    pre-birth scan also saw 29251.25. A differential proved that structurally
    inert -- all nine snapshot blocks identical -- but the intended causal
    timeline is quote-arrives-at-birth, and Stage 3 makes the specimen match the
    experiment it claims to be.
    """

    def __init__(self, candles, **kw):
        super().__init__(**kw)
        self.candles = candles

    def capture(self, volatility_state: str = None):
        if not self.candles.born:
            raise RuntimeError("no executable quote before the bar settles")
        return super().capture(volatility_state)

    def __call__(self):
        return self.capture()

    def has_quote(self) -> bool:
        return bool(self.candles.born)


class StanceAwareGate(BrainGate):
    """As `BrainGate`, and records the stance history seen at each invocation."""

    def __init__(self, real, *, live: bool):
        super().__init__(real)
        self.live = live
        self.stance_seen = []

    def __call__(self, snapshot, symbol, stance_memory):
        from ai_brain.brain_schema import empty_brain_output
        self.n += 1
        self.snapshots.append(snapshot)
        self.stance_seen.append(
            stance_memory.history_summary() if stance_memory else {"available": False})
        if self.n == 1:
            # Deterministic and NON-RECORDING: production would call
            # `stance_memory.record` here, which would append a neutral entry on
            # top of the seeded historical one. The stub must leave the seeded
            # stance exactly as the archive wrote it.
            out = empty_brain_output()
            out["narrative_direction"] = "neutral"
            return out
        if self.n == 2:
            if not self.live:
                out = empty_brain_output()
                out["narrative_direction"] = "neutral"
                return out
            self.brain_block = self.real(snapshot, symbol, stance_memory)
            return self.brain_block
        raise RuntimeError(f"cognition invocation #{self.n}: one call was authorized")


def run_stage3(tmpdir: str, *, live: bool, interval: float = 8.0,
               settle_after: float = 3.0) -> dict:
    """Stage 2, frozen, with ONE substantive change: historical prior stance.

    `live=False` is the zero-call precheck. `live=True` spends the one call.
    """
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))

    import broker.topstepx_production_loop as PL
    import live_scan.production_scan_cycle as PSC
    import topstepx_production_session as TOOL
    from broker.topstepx_production_loop import ProductionLoop

    if live:
        from ai_brain.production_model import PRODUCTION_MODEL, resolve_model
        resolved = resolve_model(armed=False)
        if resolved != PRODUCTION_MODEL:
            raise RuntimeError(f"MODEL DRIFT: {resolved!r} != {PRODUCTION_MODEL!r}")
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("no OPENAI_API_KEY -- refusing to call")
    else:
        resolved = None

    prior = archived_prior_stance()
    candles = SpecimenCandles()
    quotes = BirthGatedQuotes(candles, ask=COUNTERFACTUAL_ASK, bid=COUNTERFACTUAL_BID)
    session = SpecimenSession()
    ps, runtime = SpecimenPS(quotes, session), SpecimenRuntime()

    marks, started, seeded = [], time.monotonic(), {}
    gate = StanceAwareGate(PSC.run_narrative_brain, live=live)

    class SeededLoop(ProductionLoop):
        def __init__(self, **kw):
            super().__init__(**kw)
            # THE ONE SUBSTANTIVE CHANGE, through the production contract.
            self.cycle.stance_memory.record(prior["timestamp"], prior["output"])
            seeded["at_seed"] = self.cycle.stance_memory.history_summary()

        def scan_once(self):
            marks.append(time.monotonic() - started)
            return super().scan_once()

    def pump():
        time.sleep(settle_after)
        candles.settle_the_1023_bar()      # bar settles AND the quote appears

    prior_loop, prior_brain = PL.ProductionLoop, PSC.run_narrative_brain
    PL.ProductionLoop, PSC.run_narrative_brain = SeededLoop, gate
    threading.Thread(target=pump, daemon=True).start()
    results, outbound = [], {}
    try:
        cap = one_outbound_call_only() if live else contextlib.nullcontext({})
        with sandboxed(tmpdir), cap as outbound:
            results = TOOL.run_production_scans(
                ps=ps, runtime=runtime, candles=candles, session=session,
                contract=candles.contract, armed=False, symbol="MNQ",
                mission_id="SPECIMEN-20260821-1024-STAGE3", scans=2,
                interval=interval, until_close=False)
    finally:
        PL.ProductionLoop, PSC.run_narrative_brain = prior_loop, prior_brain

    reg = candles.wake_registry
    return {
        "live": live,
        "model": resolved,
        "prior_stance": prior,
        "stance_at_seed": seeded.get("at_seed"),
        "stance_seen": gate.stance_seen,
        "outbound_calls": (outbound or {}).get("calls", 0),
        "outbound_blocked": (outbound or {}).get("blocked", 0),
        "cognition_invocations": gate.n,
        "brain_block": gate.brain_block,
        "snapshots": gate.snapshots,
        "marks": marks,
        "gap": (marks[1] - marks[0]) if len(marks) > 1 else None,
        "interval": interval,
        "wakes": list(getattr(reg, "wakes", []) or []),
        "armed_ids": {r[0] for r in reg.armed()} if reg is not None else set(),
        "submit_attempts": session.submit_attempts,
        "results": results,
    }


def constructibility(snapshot: dict) -> dict:
    """What production would ACTUALLY give Luna. Built by the same function."""
    from ai_brain.brain_input import build_brain_input
    bi = build_brain_input(snapshot, {}) or {}
    catalog = bi.get("authorized_tool_catalog") or []
    ep = ((bi.get("market") or {}).get("execution_price")) or {}

    def locate(o, value, path="", depth=0, out=None):
        """WHERE a number lives, not merely THAT it appears.

        A bare "is 29533.75 somewhere in this payload" boolean can pass for the
        wrong reason -- a coincidental candle price would satisfy it. Naming the
        field is what distinguishes an available structural fact from a
        numerical accident.
        """
        if out is None:
            out = []
        if depth > 9:
            return out
        if isinstance(o, dict):
            for k, v in o.items():
                locate(v, value, f"{path}.{k}", depth + 1, out)
        elif isinstance(o, list):
            for i, v in enumerate(o[:80]):
                locate(v, value, f"{path}[{i}]", depth + 1, out)
        else:
            if _close(o, value):
                out.append(path)
        return out

    exact = [t for t in catalog if str(t.get("occurrence_id") or "") == GAP_ID]
    inv_paths = locate(bi, EXPECTED_INVALIDATION)
    obj_paths = locate(bi, EXPECTED_OBJECTIVE)
    #: Named structural fields, as opposed to raw candle-series members.
    named = lambda ps: [p for p in ps if "candles" not in p and "path[" not in p]
    return {
        "brain_input": bi,
        "catalog_size": len(catalog),
        "exact_occurrence_available": bool(exact),
        "exact_occurrence": exact[0] if exact else None,
        "tool_family": (exact[0].get("tool_family") if exact else None),
        "zone_correct": bool(exact) and _close(exact[0].get("zone_low"), GAP_LOW)
                        and _close(exact[0].get("zone_high"), GAP_HIGH),
        "invalidation_available": bool(inv_paths),
        "invalidation_paths": inv_paths[:6],
        "invalidation_named_structurally": bool(named(inv_paths)),
        "objective_available": bool(obj_paths),
        "objective_paths": obj_paths[:6],
        "objective_named_structurally": bool(named(obj_paths)),
        "fresh_entry_price_available": bool(ep.get("fresh"))
                                       and _close(ep.get("best_ask"), COUNTERFACTUAL_ASK),
        "execution_price": ep,
    }


def _close(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return False
