"""One production scan, driven through the authoritative pipeline.

`run_scan_loop` is a 1300-line process function: it owns its own provider, its
own startup authority, its own printing and an unbounded `while` loop. The
TopstepX production launcher cannot call it — it needs ONE scan at a time,
against the shared market runtime, with the result handed back rather than
printed.

So this class holds the same stateful engines `run_scan_loop` holds and calls
the same functions in the same order:

    build_timeframes -> htf_engine.update -> track_capital -> build_snapshot
    -> analyze_transition -> setup_tracker -> shared context + council
    -> retrieve_for_snapshot -> canonical Brain thesis

It builds NO snapshot of its own. Every field comes from `build_snapshot`, so a
production candidate is authored from exactly the evidence the scan loop would
have produced — a hand-rolled "simplified" payload would silently change the
organism being validated.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from ai_brain.brain_input import build_brain_input
from ai_brain.narrative_brain import run_narrative_brain
from ai_brain.stance_memory import StanceMemory
from data_feed import candle_continuity as CONT
from data_feed.timeframe_builder import build_timeframes
from market_data.snapshot_builder import build_snapshot

SOURCE_LLM = "llm"


#: ACTIVE-PATH-STATE-1 — ledger health that permits authoritative derivation.
from market_data.occurrence_ledger import HEALTHY as _OL_HEALTHY


class ScanCycleError(RuntimeError):
    """The scan could not be completed. Never a partial snapshot."""


class ProductionScanCycle:
    """The scan-loop pipeline, one iteration at a time, state preserved."""

    def __init__(self, symbol: str = "MNQ", *, account_provider=None,
                 capital_identity: dict = None, session_id: str = "",
                 contract_id: str = "", quote_provider=None) -> None:
        # Supplies the REAL pinned Topstep account. Without it capital metrics
        # have no equity and contribute nothing — which is correct, and far
        # better than the retired fallback that read an Alpaca balance.
        self.account_provider = account_provider
        # EXEC-PRICE-FRESHNESS-1 (2026-08-20). Supplies the FRESH executable
        # quote. Without it the scan publishes a block that says so, and
        # candidate economics refuse rather than fall back to a settled close —
        # the substitution that priced a 66.00-point stop off 29404.25 while
        # the market was trading 29423.25-29457.25.
        self.quote_provider = quote_provider
        # Binds capital history to THIS account. Without it a foreign
        # peak (an Alpaca $100k balance) drives drawdown on a $50k Combine.
        self.capital_identity = capital_identity
        from adaptive_learning.meta_awareness_engine import MetaAwarenessEngine
        from ai_brain.thesis_lifecycle import ThesisLifecycleEngine
        from market_data.htf_memory_engine import HtfMemoryEngine
        from narrative_authority.protected_swings import ProtectedSwingTracker
        from setup_lifecycle.setup_tracker import SetupTracker
        from state.market_memory import MarketMemory
        from structure.po3_alignment_manager import Po3StabilityManager
        from structure.session_po3 import SessionPo3Authority
        from volatility.expansion_stability import ExpansionStabilityManager

        self.symbol = symbol
        self.memory = MarketMemory(max_snapshots=20)
        self.meta_engine = MetaAwarenessEngine(symbol=symbol)
        self.htf_engine = HtfMemoryEngine(symbol=symbol)
        self.setup_tracker = SetupTracker()
        self.swing_tracker = ProtectedSwingTracker()
        self.stance_memory = StanceMemory()
        self.thesis_engine = ThesisLifecycleEngine(symbol=symbol)
        self.po3_stability = Po3StabilityManager()
        self.session_po3 = SessionPo3Authority()
        # LUNA-LIQUIDITY-SCOPE-TRUTH-1: last scan's ESTABLISHED session
        # range, so a sweep is judged against a boundary that PREDATES
        # it. Judging an event against a range the event itself helped
        # extend would let it create its own yardstick.
        self._prior_po3_range = None
        self._prior_po3_session_date = None
        self.expansion_stability = ExpansionStabilityManager()

        self.previous_snapshot = None
        self.previous_qual_state = None
        self.bars_in_state = 0
        self.scan_count = 0
        # Carried forward between scans exactly as the loop carries them.
        self.prev_experience_summary = None
        self.prev_memory_search = None
        self.prev_dashboard = None

        # ADD-PER-SCAN-MEMORY-RETRIEVAL-TELEMETRY (2026-08-07). Evidence, not
        # memory: written under the session archive root, never into the
        # retrieval corpus.
        from ai_retrieval.retrieval_telemetry import RetrievalTelemetrySession
        self.retrieval_telemetry = RetrievalTelemetrySession(
            session_id or "UNSCOPED", instrument=symbol, contract=contract_id)

        # LIQUIDITY-SWEEP-EPISODE-IDENTITY-1 — THE SOLE PRODUCTION WRITER of the
        # observed-occurrence ledger. `sweep_detected` is a two-candle predicate:
        # it answers "is the CURRENT bar a sweep" truthfully and then the event
        # is gone, so a historical causal question ("which manipulation, at what
        # level, when") had nothing to ask. This scan path records the answer
        # once, as it happens.
        #
        # NOTHING READS IT YET. Recording is the whole of this unit; PO3 gaining
        # a historical consumer is a later unit with its own certification.
        #
        # No exact contract means no ledger. A store that invented one would
        # file foreign evidence under production identity.
        # HEALTH IS TRUTHFUL. "no sweep to record" and "a sweep happened and
        # durable memory failed" must never both look like an empty list --
        # a consumer would read absence-of-record as absence-of-event, which is
        # the same epistemic lie the whole unit exists to end. Absent by design
        # is likewise not the same as broken.
        from market_data import occurrence_ledger as _OL
        self.contract_id = str(contract_id or "").strip()
        self.occurrence_ledger = None
        self.occurrence_ledger_status = _OL.NOT_CONFIGURED
        self.occurrence_ledger_error = ""
        if self.contract_id:
            try:
                self.occurrence_ledger = _OL.OccurrenceLedger(self.contract_id)
                self.occurrence_ledger_status = self.occurrence_ledger.health()["status"]
            except Exception as exc:  # noqa: BLE001 — memory must never kill the scan
                self.occurrence_ledger = None
                self.occurrence_ledger_status = _OL.UNAVAILABLE
                self.occurrence_ledger_error = f"{type(exc).__name__}: {str(exc)[:160]}"
        # ACTIVE-PATH-STATE-1 — cross-scan derived state (never persisted).
        self._active_path = None
        self._active_path_prior_protected: dict = {}
        self.last_occurrence_writes: list = []
        self.last_occurrence_persistence_status = self.occurrence_ledger_status
        self.last_occurrence_persistence_error = self.occurrence_ledger_error

        # CANDLE-CONTINUITY 2a (2026-08-11). Canonical data may invalidate
        # derived knowledge; derived knowledge may never survive a revision of
        # the history that created it without reconciliation.
        #
        # The provider owns canonical HISTORY. This owns DERIVED STATE. It is
        # deliberately not the provider's job to know how to rebuild protected
        # swings or Po3 -- a data feed that could reach into market cognition
        # would be the same boundary violation the reconcilers were.
        #
        # Revision is computed from the candles this object already receives,
        # so no caller can bypass it by forgetting to pass a flag.
        self._history = CONT.HistoryRevision()
        self._derived_revision = 0
        self.rebuilds = []

    # ── candle-derived state, re-derived from repaired history ────────────────
    #
    # AUDITED 2026-08-11 by introspection, not inference. Of 23 attributes this
    # object carries, these are the ones whose value depends on candle history.
    # `_flip_registry` is created LAZILY inside a scan and would have been
    # missed by reading __init__ alone -- which is precisely why the set was
    # enumerated from a live instance rather than guessed.
    CANDLE_DERIVED_STATE = (
        "memory",                # snapshots built from candles
        "htf_engine",            # fed candles_1m directly every scan
        "setup_tracker",         # setups tracked across candle-derived snapshots
        "swing_tracker",         # protected swings registered from candles
        "po3_stability",         # phase stability over candle-derived Po3
        "session_po3",           # canonical session PO3 lifecycle authority
        "expansion_stability",   # expansion stability over candle-derived vol
        "_flip_registry",        # LAZY: structure flips, session-lifetime
        "previous_snapshot",     # a candle-derived snapshot
        "previous_qual_state",   # derived from that snapshot
        "bars_in_state",         # a counter over derived states
        # LUNA-LIQUIDITY-SCOPE-TRUTH-1. The PRIOR established session range and
        # its date. Both are derived from `session_po3`, which is itself
        # candle-derived, so a revised tape invalidates them. Discarding is the
        # fail-closed answer: after a revision the organism can no longer vouch
        # that this range predated any event, and `po3_scope` correctly reads
        # UNKNOWN until an established range forms again. Keeping them would let
        # a range from a tape that no longer exists classify a live event.
        "_prior_po3_range",
        "_prior_po3_session_date",
        # LIQUIDITY-SWEEP-EPISODE-IDENTITY-1. What the PREVIOUS scan observed
        # and wrote. A canonical-history rebuild must not carry a prior scan's
        # result forward as though it belonged to the rebuilt state. The durable
        # LEDGER is a different question and is deliberately NOT here.
        "last_occurrence_writes",
        # ACTIVE-PATH-STATE-1 (2026-08-24). DERIVED ownership, and derived
        # knowledge may never outlive the history that produced it. Every input
        # to it -- sweeps, structure breaks, the protected-swing ladder -- comes
        # from candles, so a canonical-history revision invalidates the leg it
        # established. The durable OCCURRENCE LEDGER is a different question and
        # is deliberately NOT here: facts stay, conclusions are rebuilt.
        "_active_path",
        "_active_path_prior_protected",
    )

    #: NOT rebuilt, and why. Recorded so the exclusion is a decision rather than
    #: an oversight: identity/config (symbol, account_provider, capital_identity),
    #: evidence sinks that must survive to describe the rebuild itself
    #: (retrieval_telemetry, scan_count), and `stance_memory` / `thesis_engine`,
    #: which hold BRAIN history rather than candle-derived facts -- discarding
    #: Terra's own stance because a data hole was repaired would destroy
    #: cognition the repair has no claim over.
    STATE_NOT_CANDLE_DERIVED = (
        "symbol", "account_provider", "capital_identity", "scan_count",
        "retrieval_telemetry", "meta_engine",
        # EXEC-PRICE-FRESHNESS-1. A live connection to the venue quote stream:
        # config/identity like `account_provider`, and emphatically NOT derived
        # from candle history. Rebuilding it on a history revision would drop
        # the subscription that makes executable pricing possible.
        "quote_provider",
        "prev_experience_summary", "prev_memory_search", "prev_dashboard",
        # LIQUIDITY-SWEEP-EPISODE-IDENTITY-1 — HISTORICAL RECORD, NOT DERIVED
        # KNOWLEDGE. `contract_id` is identity/config and cannot be changed by a
        # candle revision. The LEDGER is a durable audit of what the certified
        # detector OBSERVED AND RECORDED AT BIRTH; rebuilding it on a history
        # revision would delete real historical records and re-derive them under
        # today's detector semantics, which is not repair -- it is rewriting what
        # was witnessed. Persistence HEALTH is likewise not candle-derived: a
        # continuity repair cannot magically restore failed storage.
        #
        # THIS IS NOT A CLAIM OF CURRENT EXECUTION AUTHORITY. These records mean
        # "this is what the authoritative detector observed at birth", NOT "this
        # remains valid causal authority after every later continuity revision".
        # Producer/detector lineage + revision reconciliation must be certified
        # before Unit 1 may consume them for execution-bearing PO3 causality.
        "contract_id", "occurrence_ledger", "occurrence_ledger_status",
        "occurrence_ledger_error", "last_occurrence_persistence_status",
        "last_occurrence_persistence_error",
    )

    #: COGNITIVE state — RE-ANCHORED, never replayed. (CONTINUITY-2B.)
    #:
    #: An earlier version of this file claimed these "hold Terra's own stance,
    #: not candle-derived facts", and that a repaired hole had no claim over
    #: them. AUDITED 2026-08-11: that was wrong, on both, by different routes.
    #:
    #:   stance_memory  -> `history_summary()` -> `stance_history` -> DIRECTLY
    #:                     into Terra's prompt, and persisted to disk
    #:   thesis_engine  -> `snapshot["thesis_state"]` -> consumed by
    #:                     `trade_qualification_engine`, and persisted to disk
    #:                     (`lifecycle_enabled()` defaults TRUE -- this is live,
    #:                     unlike the separately-gated ECU path)
    #:
    #: They are not mechanically derived from candles; they are EPISTEMICALLY
    #: derived from them. A belief formed while twenty minutes were missing is
    #: as stale as a swing computed across the same hole -- it simply cannot be
    #: recomputed, because it was a reading rather than a calculation. So the
    #: law is broader than "candle-derived": no knowledge whose truth depends on
    #: a superseded version of market history may remain AUTHORITATIVE after
    #: that history is revised. Deterministic knowledge is replayed; cognitive
    #: knowledge is invalidated or explicitly re-anchored.
    COGNITIVE_STATE_RE_ANCHORED = ("stance_memory", "thesis_engine")

    def _rebuild_derived_state(self, candles_1m: list, revision: int) -> dict:
        """Discard every candle-derived fact and re-derive it from the repaired
        tape. REPLACEMENT, not cleaning.

        Surgically removing the swings a hole fabricated would mean knowing
        which ones it fabricated. Re-deriving cannot leave a stale object
        behind, because the objects do not survive. Measured cost: ~6 ms per
        `build_snapshot` and 1.33 s for a 240-bar warmup, with NO model call --
        `build_snapshot` only reaches the Brain under BRAIN_ECU_MODE, which is
        off. Against a 60-second cadence that is ~2% of one tick.

        Never raises. A rebuild that failed leaves `_derived_revision` behind
        the history revision, so the mismatch persists and the producer keeps
        refusing -- failing closed rather than resuming on unproven state.
        """
        import time
        from adaptive_learning.meta_awareness_engine import MetaAwarenessEngine  # noqa: F401
        from market_data.htf_memory_engine import HtfMemoryEngine
        from narrative_authority.protected_swings import ProtectedSwingTracker
        from setup_lifecycle.setup_tracker import SetupTracker
        from state.market_memory import MarketMemory
        from structure.po3_alignment_manager import Po3StabilityManager
        from structure.session_po3 import SessionPo3Authority
        from volatility.expansion_stability import ExpansionStabilityManager

        started = time.time()
        bars = list(candles_1m or [])
        record = {"revision": revision, "from_revision": self._derived_revision,
                  "bars": len(bars), "ok": False, "derived": 0,
                  "inserted": list(self._history.last_inserted)}
        # A rebuild that DERIVES NOTHING must never claim currency. Below the
        # confirmation lookback the replay loop simply does not execute, so
        # without this the method would return ok on an empty tape and open the
        # gate onto state built from nothing -- a fail-open hiding inside a
        # success path. Found by a test that fed it a garbage tape.
        if len(bars) < self.REBUILD_MIN_BARS:
            record["error"] = (f"only {len(bars)} bars; {self.REBUILD_MIN_BARS} "
                               "are required to confirm a pivot")
            record["seconds"] = round(time.time() - started, 3)
            self.rebuilds.append(record)
            return record
        try:
            self.memory = MarketMemory(max_snapshots=20)
            self.htf_engine = HtfMemoryEngine(symbol=self.symbol)
            self.setup_tracker = SetupTracker()
            self.swing_tracker = ProtectedSwingTracker()
            self.po3_stability = Po3StabilityManager()
            self.session_po3 = SessionPo3Authority()
            self._prior_po3_range = None
            self._prior_po3_session_date = None
            self.expansion_stability = ExpansionStabilityManager()
            self._flip_registry = None
            self.previous_snapshot = None
            self.previous_qual_state = None
            self.bars_in_state = 0
            # LIQUIDITY-SWEEP-EPISODE-IDENTITY-1. What the PREVIOUS scan observed
            # and wrote belonged to the tape as it was BEFORE the revision, so it
            # must not survive as though it described the rebuilt state. The
            # durable LEDGER is deliberately untouched here: those are records of
            # what the detector witnessed at birth, and re-deriving them under
            # today's semantics would rewrite the witnessed past rather than
            # repair it.
            self.last_occurrence_writes = []
            # ACTIVE-PATH-STATE-1. The leg was established from the tape as it
            # was BEFORE the revision, so the CONCLUSION dies with that history.
            # The occurrence ledger keeps the underlying facts; ownership is
            # re-derived from them rather than carried across the seam.
            self._active_path = None
            self._active_path_prior_protected = {}

            # Re-derive by replaying the canonical tape through the SAME
            # builder production uses. A private reconstruction would be a
            # second definition of what a swing is.
            derived = 0
            for end in range(self.REBUILD_MIN_BARS, len(bars) + 1):
                window = bars[:end]
                snapshot = build_snapshot(
                    build_timeframes(window), symbol=self.symbol,
                    swing_tracker=self.swing_tracker,
                    po3_stability=self.po3_stability,
                    session_po3=self.session_po3,
                    # The growing replay window IS the deep series here: the
                    # rebuild already holds the whole canonical tape, so context
                    # reconstructs from exactly the bars the phase does.
                    deep_1m=window,
                    expansion_stability=self.expansion_stability,
                    contract_id=self.contract_id)
                self._update_structure_flips(snapshot)
                derived += 1
            self.htf_engine.update(bars)
            record["cognitive"] = self._reanchor_cognitive_state(revision)
            # (There is deliberately no `if not derived` check here: the
            # length guard above already guarantees the replay loop runs at
            # least once, so a zero-derived success is unreachable. A guard no
            # test can kill is a liability, not defence.)
            record["derived"] = derived
            self._derived_revision = revision
            record["ok"] = True
        except Exception as exc:  # noqa: BLE001 — a failed rebuild stays refused
            record["error"] = f"{type(exc).__name__}: {exc}"
        record["seconds"] = round(time.time() - started, 3)
        self.rebuilds.append(record)
        return record

    def _reanchor_cognitive_state(self, revision: int) -> dict:
        """Strip authority from beliefs formed under the superseded tape.

        Not deletion: the stances stay on record as evidence of what Terra
        actually thought, marked with the revision that superseded them so the
        next prompt is TOLD rather than quietly steered. The active thesis is
        invalidated outright, because it gates qualification and cannot be
        re-derived. Never raises.
        """
        out = {}
        try:
            out["stance"] = self.stance_memory.supersede(
                revision, note="canonical market history was repaired")
        except Exception as exc:  # noqa: BLE001
            out["stance"] = {"error": f"{type(exc).__name__}: {exc}"}
        try:
            out["thesis"] = self.thesis_engine.invalidate_on_history_revision(
                revision, ts=str(self.previous_snapshot or ""))
        except Exception as exc:  # noqa: BLE001
            out["thesis"] = {"error": f"{type(exc).__name__}: {exc}"}
        return out

    #: Below this the detectors have no lookback to confirm a pivot against.
    REBUILD_MIN_BARS = 20

    def derived_state_is_current(self) -> bool:
        """Authoritative cognition is permitted only while these agree."""
        return self._derived_revision == self._history.revision

    # ── one scan ──────────────────────────────────────────────────────────────
    def scan(self, candles_1m: list, *, now: datetime = None,
             deep_1m: list = None) -> dict:
        from ai_retrieval.retrieval import retrieve_for_snapshot
        from shared_context.council import run_council
        from shared_context.shared_market_context import build_shared_market_context
        from state_transitions.transition_engine import analyze_transition

        if not candles_1m:
            raise ScanCycleError("no candles: refusing to scan a market it cannot see")
        now = now or datetime.now(timezone.utc)
        self.scan_count += 1

        raw_data = build_timeframes(candles_1m)
        htf_context = self.htf_engine.update(candles_1m)

        # CANDLE-CONTINUITY (2026-08-11). Computed from the SAME series every
        # engine below reads, so the report can never describe a different tape
        # than the one that produced the facts. On 2026-08-11 a 20-minute hole
        # reached the Brain looking perfectly contiguous, and the entire buy-side
        # manipulation through 29,800 lived inside it. A gap is not thin data:
        # `find_swings` confirms pivots against neighbours on BOTH sides, so
        # across a hole it can invent structure that never existed.
        continuity = CONT.summarize(candles_1m, timeframe="1m")

        # Did the PAST change since the last scan? Appending a freshly closed
        # minute is ordinary growth; inserting one at or before the previous tip
        # rewrites what every tracker already computed from.
        history_revision = self._history.observe(candles_1m)
        if history_revision != self._derived_revision:
            self._rebuild_derived_state(candles_1m, history_revision)

        from adaptive_learning.capital_intelligence_engine import track_capital
        try:
            account = self.account_provider() if self.account_provider else {}
            capital_report = track_capital(self.symbol, account=account or {},
                                           identity=self.capital_identity)
        except Exception:  # noqa: BLE001 — capital contributes nothing on error
            capital_report = {}

        # EXEC-PRICE-FRESHNESS-1. The executable picture AT THIS SCAN, captured
        # from the already-running quote stream. Settled candles keep answering
        # "what has the market done"; this answers "what would this trade cost
        # right now", and the two never share a field again.
        #
        # TOOLBOX-EXECUTION-PRICE-ORDERING-1. Captured ONCE, before the snapshot
        # is built, and handed in: the toolbox measures zone location against
        # this exact block. A second provider read after the build would let the
        # quote move between them, showing the Brain a price its own tool
        # locations were never computed from.
        execution_price = self._execution_price()
        snapshot = build_snapshot(
            raw_data, memory=self.memory,
            experience_summary=self.prev_experience_summary,
            prior_memory_search=self.prev_memory_search,
            prior_dashboard=self.prev_dashboard,
            thesis_engine=self.thesis_engine, symbol=self.symbol,
            swing_tracker=self.swing_tracker, po3_stability=self.po3_stability,
            session_po3=self.session_po3, deep_1m=deep_1m,
            expansion_stability=self.expansion_stability,
            capital_report=capital_report, htf_context=htf_context,
            contract_id=self.contract_id, execution_price=execution_price)
        snapshot["candle_continuity"] = continuity
        # The revision contract, carried to whoever decides whether to trade.
        # A repaired tape with stale trackers is the same lie under a new flag,
        # so healthy candles are NOT sufficient -- the derived facts must have
        # been built from the history that exists now.
        snapshot["derived_state"] = {
            "history_revision": self._history.revision,
            "derived_revision": self._derived_revision,
            "current": self.derived_state_is_current(),
            "last_rebuild": (self.rebuilds[-1] if self.rebuilds else None),
        }

        # Record observed tape facts. Deliberately AFTER the snapshot is fully
        # built and deliberately NOT written into it: the ledger is a memory of
        # what happened, not an input to this scan's decision. Nothing about
        # qualification, tooling, candidates or the Brain payload may change
        # because a fact was remembered.
        self.last_occurrence_writes = self._record_sweep_occurrences(snapshot)

        # ACTIVE-PATH-STATE-1 (2026-08-24). Record the structural chronology the
        # organism was throwing away, then derive current ownership from it.
        #
        # This block runs AFTER the snapshot is otherwise complete and writes
        # exactly one key. It is the accumulated answer to "which side owns the
        # tape", which no instantaneous field in this snapshot can give: BOS is
        # a boolean that expires next scan, and the protected-swing tracker pops
        # each level as the next one registers.
        #
        # FACTS ARE DURABLE, STATE IS DERIVED. The ledger keeps the events
        # forever; ownership is recomputed here every scan and never read back
        # from disk as a conclusion.
        snapshot["active_path_state"] = self._update_active_path(snapshot)

        cur_qual = (snapshot.get("qualification", {}).get("status") or "no_trade").lower()
        self.bars_in_state = (self.bars_in_state + 1
                              if cur_qual == self.previous_qual_state else 1)
        snapshot["state_transition"] = analyze_transition(
            snapshot, self.previous_snapshot, self.bars_in_state)
        self.previous_snapshot = snapshot
        # REMEMBERED FOR THE NEXT SCAN, NOT USED FOR THIS ONE. Only an
        # ESTABLISHED range is carried: a forming range has not earned the
        # authority to say what is outside it, and `po3_reference` refuses it
        # anyway -- carrying it here would only make that refusal harder to see.
        _sp3 = (snapshot.get("session_po3") or {}) if isinstance(snapshot, dict) else {}
        _rng = _sp3.get("range") or {}
        self._prior_po3_range = dict(_rng) if _rng.get("established") else None
        self._prior_po3_session_date = (
            str(_sp3.get("session_date") or "") or
            (str(snapshot.get("timestamp") or "")[:10] if isinstance(snapshot, dict) else None))
        self.previous_qual_state = cur_qual

        snapshot["setup_lifecycle"] = self.setup_tracker.update(snapshot, self.symbol)
        snapshot["shared_context"] = build_shared_market_context(snapshot, self.symbol)
        snapshot["council"] = run_council(snapshot["shared_context"])
        # ONE retrieval per scan. This exact object is what the Brain consumes
        # AND what the telemetry describes -- recomputing it for telemetry could
        # produce evidence that disagrees with what Terra was actually shown.
        import time as _time
        from ai_retrieval.retrieval import retrieval_startup_state
        _t0 = _time.perf_counter()
        retrieval_result = retrieve_for_snapshot(snapshot, self.symbol)
        _elapsed_ms = (_time.perf_counter() - _t0) * 1000.0
        snapshot["ai_retrieval"] = retrieval_result
        try:
            telem = self.retrieval_telemetry.record_scan(
                scan_id=self.snapshot_id(snapshot, now),
                result=retrieval_result,
                startup_state=retrieval_startup_state(),
                duration_ms=_elapsed_ms)
            # Linkage: the Brain artifact can be traced to the exact retrieval
            # record that fed it.
            snapshot["memory_retrieval_telemetry_id"] = telem.get("scan_id")
            self._last_retrieval_telemetry = telem
        except Exception:  # noqa: BLE001 — observability never gates a scan
            self._last_retrieval_telemetry = None

        # PIPE-1: under ECU the single canonical Brain call already ran inside
        # build_snapshot and IS the consumed thesis. Calling the brain again here
        # would bill a second request and — worse — author the candidate from a
        # different read than the one the snapshot was qualified against.
        from ai_brain.ecu import ecu_enabled
        canonical = (snapshot.get("candidate_thesis") or {}).get("brain_block")
        # Structure flips are advanced BEFORE the Brain reads its input, so the
        # authorized catalog for THIS scan already contains them.
        self._update_structure_flips(snapshot)

        if ecu_enabled() and canonical is not None:
            brain_block = canonical
        else:
            brain_block = run_narrative_brain(snapshot, self.symbol, self.stance_memory)
        snapshot["ai_brain"] = brain_block

        # ── TWO-BRAIN SHADOW ────────────────────────────────────────────────
        # Runs AFTER the production thesis is settled, and lands in its own key.
        # `brain_result` -- the only thing CandidateProducer reads -- is built
        # below from `brain_block` and never sees this. Off unless
        # TWO_BRAIN_MODE says otherwise; never raises.
        shadow = self._two_brain_shadow(snapshot)

        return {
            "snapshot": snapshot,
            "brain_block": brain_block,
            "two_brain_shadow": shadow,
            "brain_input": self._brain_input(snapshot),
            "brain_result": self.to_brain_result(brain_block),
            "qualification": snapshot.get("qualification") or {},
            # PROD-20260807 EVIDENCE DEFECT: the live qualification object was
            # never persisted, so no forensic replay could establish whether a
            # proposal died at qualification, objective, geometry or RR. The
            # causal chain must be reconstructable without archaeology.
            "qualification_evidence": {
                "status": (snapshot.get("qualification") or {}).get("status"),
                "qualified": (snapshot.get("qualification") or {}).get("qualified"),
                "reason": (snapshot.get("qualification") or {}).get("reason"),
                "direction": (snapshot.get("qualification") or {}).get("direction"),
                "authorized_playbooks": (snapshot.get("qualification") or {}
                                         ).get("authorized_playbooks"),
                "authorized_objectives": [
                    {"objective_id": o.get("objective_id"), "kind": o.get("kind"),
                     "price": o.get("price"), "side": o.get("side")}
                    for o in ((snapshot.get("ai_brain") or {}).get("input_payload")
                              or {}).get("authorized_objectives", [])],
            },
            "engine_inventory": self.engine_inventory(snapshot),
            "snapshot_id": self.snapshot_id(snapshot, now),
            "market_data_timestamp": str(snapshot.get("timestamp") or ""),
            "latest_closed_bar_timestamp": self._latest_bar(candles_1m),
            "scan_count": self.scan_count,
            "source": (brain_block or {}).get("source"),
            "memory_retrieval_telemetry": getattr(
                self, "_last_retrieval_telemetry", None),
        }

    # ── adapters ──────────────────────────────────────────────────────────────
    def _update_structure_flips(self, snapshot: dict) -> list:
        """Advance the structure-flip lifecycle for this scan.

        Owned here because lifecycle is a property of the SESSION, not of one
        snapshot: BIRTH, SUPERSEDED and INVALIDATED are transitions between
        scans. Never raises -- a vocabulary failure may not cost a scan.
        """
        try:
            from structure.structure_flip import FlipRegistry
            if getattr(self, "_flip_registry", None) is None:
                self._flip_registry = FlipRegistry()
            self._flip_registry.update(snapshot.get("structure") or {},
                                       timestamp=str(snapshot.get("timestamp") or ""))
            candidates = self._flip_registry.candidates()
        except Exception:  # noqa: BLE001
            candidates = []
        snapshot["structure_flips"] = candidates
        self._build_mtf_state(snapshot, candidates)
        return candidates

    def _build_mtf_state(self, snapshot: dict, flips: list) -> dict:
        """Assemble MTF_MARKET_STATE from atomic facts. Never raises.

        A NEW lane. It does not read, alias, or rehabilitate the legacy
        structure authority -- it reads swings, directional BOS, liquidity
        sweeps and the per-timeframe protected registry, and reports how the
        four timeframes relate.
        """
        try:
            from market_state.mtf_market_state import build
            price = None
            for tf in ("1m", "3m", "5m", "15m"):
                lc = ((snapshot.get("timeframes") or {}).get(tf) or {}).get("last_candle")
                if lc and lc.get("close") is not None:
                    price = lc["close"]
                    break
            state = build(structure=snapshot.get("structure") or {},
                          liquidity=snapshot.get("liquidity") or {},
                          protected_swings=snapshot.get("protected_swings") or {},
                          structure_flips=flips, price=price,
                          timestamp=str(snapshot.get("timestamp") or ""))
        except Exception:  # noqa: BLE001
            state = {}
        snapshot["mtf_market_state"] = state
        return state

    def _execution_price(self) -> dict:
        """The fresh executable block for this scan. Never raises.

        A provider that is absent, empty or throwing yields a block that STATES
        it has no price, naming which of those three it was. It never yields a
        settled close wearing an executable label -- that substitution is the
        defect this method exists to end.
        """
        from broker.topstepx_execution_price import (NO_QUOTE_PROVIDER,
                                                     QUOTE_PROVIDER_FAILED,
                                                     from_capture, unavailable)
        if self.quote_provider is None:
            return unavailable(NO_QUOTE_PROVIDER)
        try:
            return from_capture(self.quote_provider())
        except Exception:  # noqa: BLE001 — a broken stream is reported, not raised
            return unavailable(QUOTE_PROVIDER_FAILED)

    def _brain_input(self, snapshot: dict) -> dict:
        """The mechanical evidence the Brain reasoned over.

        `run_narrative_brain` builds this internally and does not return it, so
        it is rebuilt from the SAME function and the same snapshot rather than
        approximated — the producer resolves the objective and invalidation out
        of it, and an approximation would let a candidate name a level the
        market evidence never contained.
        """
        try:
            history = (self.stance_memory.history_summary()
                       if self.stance_memory else {"available": False})
            return build_brain_input(snapshot, history)
        except Exception:  # noqa: BLE001
            return {}

    def _two_brain_shadow(self, snapshot: dict):
        """Record what the hybrid organism WOULD have done. Observation only.

        The deterministic author reads the raw snapshot, so shadow runs the same
        market the production lane just judged -- one session, two architectures,
        identical facts. Nothing downstream reads the result; it exists to be
        compared after the close.

        Never raises and never returns anything a gate consults. If shadow
        breaks, the scan is unaffected.
        """
        try:
            from ai_brain.two_brain import SHADOW, two_brain_mode
            if two_brain_mode() != SHADOW:
                return None
            from ai_brain.narrative_brain import _deterministic
            from broker.luna_candidate_producer import (
                authorized_invalidation_catalog, authorized_objective_catalog)
            from ai_brain.two_brain import ShadowObserver

            if getattr(self, "_shadow_observer", None) is None:
                # The adjudicator is injected EXPLICITLY. Constructing
                # ShadowObserver() bare leaves `_adjudicate is None`, and every
                # bound proposal then ends at BOUND_NOT_ADJUDICATED -- shadow
                # would run all session and never once ask Terra anything.
                from ai_brain.two_brain import accounted_adjudicator
                self._shadow_observer = ShadowObserver(
                    adjudicator=accounted_adjudicator)
            brain_input = self._brain_input(snapshot)
            price = (brain_input.get("market") or {}).get("current_price")
            thesis = _deterministic(snapshot, brain_input, [])
            objectives = (authorized_objective_catalog({}, brain_input, float(price))
                          if price is not None else [])
            invalidations = authorized_invalidation_catalog(brain_input)
            return self._shadow_observer.observe(
                snapshot=snapshot, brain_input=brain_input,
                deterministic_thesis=thesis, objective_catalog=objectives,
                invalidation_catalog=invalidations,
                snapshot_id=str(snapshot.get("snapshot_id")
                                or snapshot.get("timestamp") or ""),
                session_id=getattr(self, "session_id", "") or "",
                scan=getattr(self, "scan_number", None))
        except Exception:  # noqa: BLE001 — an observation may never cost a scan
            return None

    @staticmethod
    def to_brain_result(brain_block: dict) -> dict:
        """Scan-loop brain block -> the producer's expected result shape."""
        b = brain_block or {}
        return {"ok": (b.get("source") == SOURCE_LLM),
                "parsed": b.get("output") or {},
                "fallback_reason": b.get("fallback_reason"),
                "source": b.get("source"),
                "model": b.get("llm_model"),
                "warnings": b.get("warnings") or []}

    @staticmethod
    def is_sovereign(brain_block: dict) -> bool:
        """Only a clean validated llm read may author a production candidate."""
        b = brain_block or {}
        return (b.get("source") == SOURCE_LLM and not b.get("fallback_reason")
                and bool(b.get("output")))

    @staticmethod
    def engine_inventory(snapshot: dict) -> dict:
        """Which evidence engines actually populated this snapshot."""
        inv = {}
        for key in ("liquidity", "protected_swings", "po3", "volatility",
                    "delivery_state", "session_state", "volume_witness",
                    "narrative_authority", "htf_memory", "setup_lifecycle"):
            v = snapshot.get(key)
            inv[key] = ("PRESENT_AND_POPULATED" if v else
                        "PRESENT_BUT_EMPTY" if v is not None else "ABSENT")
        return inv

    @staticmethod
    def snapshot_id(snapshot: dict, now: datetime) -> str:
        return (str(snapshot.get("snapshot_id") or "")
                or f"scan-{now.strftime('%Y%m%dT%H%M%S')}")

    @staticmethod
    def _latest_bar(candles_1m: list) -> str:
        last = candles_1m[-1] if candles_1m else {}
        return str(last.get("timestamp") or "")

    def _recover_active_path(self, snapshot: dict) -> dict:
        """Rebuild current-session path state from durable occurrences.

        Called ONCE, on the first scan of a process. Replays the immutable
        events this contract already recorded for THIS production session, in
        event order, into the fresh synthesizer -- so a restart at 10:50 still
        knows at 10:52 which side owns the tape.

        BOUNDARIES ARE FILTERS, NOT AFTERTHOUGHTS. Prior-session and
        prior-contract facts remain durable forever and are excluded here: they
        may inform history, they may not regain execution-bearing authority.

        NO GHOST RESURRECTION. A level named by an old ledger record is not
        evidence that the producer still holds it, so the recovered
        load-bearing structure is reconciled against the live
        `ProtectedSwingTracker` immediately below; correspondence that cannot be
        established is reported as absent rather than assumed.

        Never raises. Returns a small diagnostic.
        """
        from market_state.active_path import (PROTECTED_SWING_REGISTERED,
                                              PROTECTED_SWING_REPLACED,
                                              PROTECTED_SWING_VIOLATED,
                                              STRUCTURE_BREAK, LIQUIDITY_SWEEP,
                                              production_session_key)
        out = {"replayed": 0, "session": None, "reconciled": None}
        try:
            if self.occurrence_ledger is None or self._active_path is None:
                return out
            key = production_session_key((snapshot or {}).get("timestamp"))
            out["session"] = key
            if not key:
                return out
            supported = {LIQUIDITY_SWEEP, STRUCTURE_BREAK,
                         PROTECTED_SWING_REGISTERED, PROTECTED_SWING_REPLACED,
                         PROTECTED_SWING_VIOLATED}
            rows = [r for r in (self.occurrence_ledger.occurrences() or [])
                    if r.get("event_type") in supported
                    and r.get("contract") == self.contract_id
                    and production_session_key(r.get("event_time")) == key]
            rows.sort(key=lambda r: (str(r.get("event_time") or ""),
                                     str(r.get("occurrence_id") or "")))
            self._active_path.ingest(rows)
            out["replayed"] = len(rows)
            out["reconciled"] = self._reconcile_load_bearing(snapshot)
            # SEED THE PROTECTED-SWING BASELINE. A fresh process has an empty
            # `prior_protected`, so every level the tracker currently holds
            # would read as a BRAND-NEW registration on the first scan --
            # re-dating the load-bearing structure to the restart instead of to
            # when the market actually defended it.
            self._active_path_prior_protected = (
                ((snapshot or {}).get("protected_swings") or {})
                .get("by_timeframe") or {})
        except Exception as exc:  # noqa: BLE001 — recovery must not kill a scan
            out["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        return out

    def _reconcile_load_bearing(self, snapshot: dict) -> bool:
        """Does the recovered load-bearing level still exist in the producer?

        A durable occurrence proves the level was registered once. It does not
        prove the tracker still holds it -- the ghost-reference defect in a new
        costume. When the live registry cannot corroborate the level, the
        derived structure is dropped rather than published as `producer_backed`.
        """
        ap = self._active_path
        lb = getattr(ap, "load_bearing", None)
        if not lb:
            return None
        bt = ((snapshot or {}).get("protected_swings") or {}).get("by_timeframe") or {}
        side = "lows" if ap.owner == "bullish" or ap.forming_direction == "bullish" else "highs"
        live = {r.get("level") for r in (bt.get(side) or {}).values()}
        if live and lb.get("level") in live:
            return True
        ap.load_bearing = None
        return False

    def _update_active_path(self, snapshot: dict) -> dict:
        """Record the structural chronology, then derive current path ownership.

        Never raises: market memory must not be able to kill a scan.

        LEDGER HEALTH GATES AUTHORITY. "No path is established" and "path state
        could not be derived" are different facts, and publishing the first
        when the second is true would be a false certainty of exactly the kind
        this unit exists to remove -- so an unhealthy or absent ledger yields
        `state_available: False` with a reason, never `owner: none`.
        """
        from market_state.active_path import ActivePath, extract_occurrences
        try:
            first_use = self._active_path is None
            if first_use:
                self._active_path = ActivePath()
            if not self.contract_id:
                return ActivePath().state(available=False,
                                          unavailable_reason="no_exact_contract")
            if self.occurrence_ledger is None:
                return ActivePath().state(
                    available=False,
                    unavailable_reason=f"ledger:{self.occurrence_ledger_status}")
            health = self.occurrence_ledger.health().get("status")
            # LIFECYCLE BEFORE INGEST. A leg established in a previous
            # production session, or under a previous exact contract, loses
            # execution-bearing ownership here -- BEFORE this scan's events can
            # extend it. Without this the guarantee rested on the launcher
            # happening to restart every morning.
            self._active_path.enforce_lifecycle(
                (snapshot or {}).get("timestamp"), self.contract_id)
            # RESTART RECOVERY. A brand-new process has an empty ActivePath and
            # would otherwise learn only what THIS scan witnessed -- so a
            # restart at 10:50 would forget the leg established between 09:45
            # and 10:50 and answer "who owns the tape" from a single snapshot.
            # That is the original defect displaced from scan lifetime to
            # PROCESS lifetime, which is not a fix.
            #
            # DURABLE FACTS, RECOMPUTED CONCLUSION. The prior chronology is
            # replayed out of the ledger it was already being written to. No
            # second store, and the derived conclusion is never persisted.
            if first_use:
                self._recover_active_path(snapshot)
            occurrences = extract_occurrences(
                snapshot, self._active_path_prior_protected, self.contract_id)
            for occ in occurrences:
                try:
                    self.occurrence_ledger.record(occ)
                except Exception:  # noqa: BLE001
                    pass
            # Derivation consumes the SAME occurrences that were offered to the
            # ledger, so a persistence failure degrades durability without
            # silently changing this scan's state.
            self._active_path.ingest(occurrences)
            self._active_path_prior_protected = (
                (snapshot.get("protected_swings") or {}).get("by_timeframe") or {})
            state = self._active_path.state(
                available=(health == _OL_HEALTHY),
                unavailable_reason=(None if health == _OL_HEALTHY
                                    else f"ledger:{health}"))
            self._active_path.mark_scan_end()
            return state
        except Exception as exc:  # noqa: BLE001
            from market_state.active_path import ActivePath as _AP
            return _AP().state(available=False,
                               unavailable_reason=f"error:{type(exc).__name__}")

    def _record_sweep_occurrences(self, snapshot: dict) -> list:
        """Persist every sweep this scan observed. THE ONLY PRODUCTION WRITER.

        The detector owns WHAT HAPPENED, `market_events` owns WHICH CANONICAL
        OBJECT it is, and this records WHAT MUST NOT BE FORGOTTEN. Recording is
        idempotent by construction: the same settled candle yields the same
        canonical id on every scan, so re-observing a sweep across scans dedupes
        instead of accumulating twins -- and the next non-sweep bar cannot erase
        a fact that was already written.

        Never raises. A memory failure degrades ledger health; it must not take
        a live trading scan down with it.
        """
        from market_data import occurrence_ledger as _OL
        ledger = self.occurrence_ledger
        if ledger is None:
            # Absent by design (no exact contract) or unavailable (construction
            # failed). Both are already recorded; neither is silently "fine".
            self.last_occurrence_persistence_status = self.occurrence_ledger_status
            self.last_occurrence_persistence_error = self.occurrence_ledger_error
            return []
        try:
            # The production-safe adapter, NOT `market_events`: that module is
            # quarantined from production because it reconstructs sweeps from a
            # bridged array-neighbour close, and importing it here would carry
            # that cadence-unsafe path across the line.
            from market_data.sweep_occurrence import liquidity_sweep_occurrence
            from market_data.liquidity_scope import stamp as _scope_stamp

            def _po3_stamp(f, prior_range, session_date):
                """Session scope only -- the detector scope is already frozen."""
                out = _scope_stamp(f, highs=None, lows=None,
                                   po3_range=prior_range,
                                   session_date=session_date)
                return {"po3_scope": out["po3_scope"],
                        "po3_scope_reference": out["po3_scope_reference"]}
            written = []
            for tf, block in sorted((snapshot.get("liquidity") or {}).items()):
                if not isinstance(block, dict):
                    continue
                fact = block.get("sweep_fact")
                if not fact:
                    continue
                # THE RANGE THAT EXISTED BEFORE THE EVENT, not the one this
                # scan just derived. Judging a sweep against a range the sweep
                # itself helped extend would let the event create its own
                # yardstick; `_prior_po3_range` is last scan's established
                # range, so the boundary predates the event it judges.
                fact = dict(fact)
                fact.update(_po3_stamp(fact, self._prior_po3_range,
                                       self._prior_po3_session_date))
                occurrence = liquidity_sweep_occurrence(
                    fact, source_tf=tf, contract=self.contract_id)
                if occurrence is None:
                    continue          # unprovable identity is not an occurrence
                written.append(ledger.record(occurrence))
            health = ledger.health()
            self.last_occurrence_persistence_status = health["status"]
            self.last_occurrence_persistence_error = health["detail"]
            return written
        except Exception as exc:  # noqa: BLE001 — remembering must never kill the scan
            # THE DISTINCTION THIS UNIT REFUSES TO LOSE: an empty return here
            # does not mean the tape was quiet, it means memory broke.
            self.last_occurrence_persistence_status = _OL.DEGRADED
            self.last_occurrence_persistence_error = (
                f"{type(exc).__name__}: {str(exc)[:160]}")
            return []


def decision_window() -> tuple:
    """The repository's configured decision window, as (start, end, tz)."""
    return (os.getenv("SCAN_START_TIME", "09:30"),
            os.getenv("SCAN_END_TIME", "14:00"),
            os.getenv("SCAN_TIMEZONE", "America/New_York"))


def in_decision_window(now_et: datetime, start: str = None, end: str = None) -> bool:
    """True when new entries are permitted. Management is never gated by this."""
    s, e, _ = decision_window()
    start, end = start or s, end or e
    hhmm = now_et.strftime("%H:%M")
    return start <= hhmm <= end
