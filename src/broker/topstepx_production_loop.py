"""The scan-to-execution branch: where the Brain reaches the order path.

`--arm` used to change a printed line. It now controls the ONLY branch that can
reach `gated_submit`. Disarmed, the loop runs the entire organism — candles,
scan, Luna, candidate, bracket, adaptive sizing — and stops at a hard boundary
before minting a token or consuming an attempt. That is what makes a disarmed
run genuinely rehearsable: the same code produces the same candidate, and only
the last step is unreachable.

Outcomes are returned, never printed from inside, so a test can assert on them.
"""
from __future__ import annotations

from datetime import datetime, timezone

from broker import topstepx_mission_reconciler as RECON
from broker import daily_loss_budget as DLB
from broker import topstepx_order_discovery as DISC
from broker import topstepx_session_authorization as SA
from broker.topstepx_combine_risk import PRODUCTION_MAX_RISK_USD
from market_data.session_context import DEEP_HISTORY_BARS as SESSION_CONTEXT_DEEP_BARS
from data_feed import candle_continuity as CONT
from broker import topstepx_mission_state as MS
from broker import topstepx_session_lifecycle as LIFECYCLE
from broker import topstepx_session_authorization as SA
from broker import topstepx_slippage as SL
from broker import topstepx_smoke_auth as auth
from broker.topstepx_candidate_freshness import CandidateStale
from broker.topstepx_combine_risk import RiskRejection
from broker.luna_candidate_producer import NoCandidate
from live_scan.production_scan_cycle import ProductionScanCycle

# outcomes
NO_CANDLES = "NO_CANDLES"
BRAIN_DEGRADED = "BRAIN_DEGRADED"
NO_CANDIDATE = "NO_CANDIDATE"
RISK_REJECTED = "RISK_REJECTED"
QUALIFIED_CANDIDATE_OBSERVED = "QUALIFIED_CANDIDATE_OBSERVED"
EXECUTION_DISARMED = "EXECUTION_DISARMED"
TRADE_MISSION_REFUSED = "TRADE_MISSION_REFUSED"
SUBMITTED = "SUBMITTED"
SUBMIT_FAILED = "SUBMIT_FAILED"
WINDOW_CLOSED = "WINDOW_CLOSED"
SESSION_COMPLETE = "SESSION_COMPLETE"



def _journal_state_for(result: dict, JOURNAL) -> str:
    """Map an actuator outcome onto the durable lifecycle.

    The distinction that matters is between states that FORBID a further write
    (the venue may still be holding our request) and states that close the
    effect. An explicit refusal is terminal because nothing is in flight; a
    silent non-appearance is not, because it may still land.
    """
    from broker import break_even_actuator as ACT
    outcome, reason = result.get("outcome"), result.get("reason")
    if outcome == ACT.APPLIED:
        return JOURNAL.READBACK_APPLIED
    if outcome == ACT.REJECTED:
        return JOURNAL.EXPLICITLY_REJECTED
    if outcome == ACT.PROTECTION_DEFECT:
        return JOURNAL.PROTECTION_DEFECT
    if outcome == ACT.HELD:
        if reason == ACT.POSITION_GONE or reason == ACT.NO_POSITION:
            return JOURNAL.POSITION_FLAT
        return JOURNAL.HELD_ALREADY
    if outcome == ACT.AMBIGUOUS:
        if reason == ACT.EFFECT_ABSENT:
            return JOURNAL.TRANSPORT_AMBIGUOUS
        return JOURNAL.READBACK_UNPROVEN
    return JOURNAL.READBACK_UNPROVEN


class ProductionLoop:
    """One production organism: scan -> Luna -> candidate -> (armed) execution."""

    def __init__(self, *, production_session, session_mission, producer, candles,
                 runtime, account_id: int, symbol: str = "MNQ", armed: bool = False,
                 scan_cycle=None, clock=None, in_window=None) -> None:
        self.ps = production_session
        self.mission = session_mission
        self.producer = producer
        self.candles = candles
        self.runtime = runtime
        self.account_id = int(account_id)
        self.symbol = symbol
        self.armed = bool(armed)
        # PROD-20260807: these were never passed, so every production scan
        # wrote its retrieval telemetry to data/replay_sessions/UNSCOPED/ with
        # an empty contract. Evidence was complete but unattributable.
        self.cycle = scan_cycle or ProductionScanCycle(
            symbol, account_provider=self._topstep_account,
            capital_identity=self._capital_identity(),
            session_id=getattr(session_mission, "session_id", "")
                       or getattr(getattr(session_mission, "authorization", None),
                                  "session_id", ""),
            contract_id=str(getattr(production_session.contract, "id", "")),
            # EXEC-PRICE-FRESHNESS-1. The session already owns a LiveQuoteProvider
            # for the submit boundary. The DECISION lane never saw it, so Luna
            # priced her stops off a settled close while the venue knew the real
            # bid and ask. Same provider, second consumer — no new market data.
            quote_provider=getattr(production_session, "quote_provider", None))
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._in_window = in_window or (lambda: True)
        self.outcomes: list = []
        # The candidate currently owning the lane. Reconciliation needs the exact
        # thesis the entry was authorized against — re-deriving it later from
        # price is how an exit gets paired to the wrong entry.
        self.active_candidate = None
        self.last_repair = None
        self.last_window = None
        self.last_daily_loss = None

    def _record_decision(self, scan: dict, disposition: str, reason, detail: str):
        """One death certificate per scan. Never raises; observability only.

        PROD-20260807 EVIDENCE DEFECT: the live qualification object was never
        persisted, so no forensic replay could establish whether a proposal died
        at qualification, objective resolution, geometry or reward-to-risk.
        Zero candidates then required archaeology instead of a lookup.
        """
        try:
            import json as _json
            import os as _os

            from ai_retrieval.retrieval_telemetry import session_root
            telem = getattr(self.cycle, "retrieval_telemetry", None)
            root = session_root(getattr(telem, "session_id", "") or "UNSCOPED")
            _os.makedirs(root, exist_ok=True)
            parsed = ((scan.get("brain_block") or {}).get("output") or {})
            from broker.candidate_decision_record import (build_record,
                                                          terminal_disposition)
            producer = getattr(self.cycle, "producer", None)
            trace = dict(getattr(producer, "last_decision_trace", None) or {})
            qual = scan.get("qualification_evidence")
            if isinstance(qual, dict) and trace.get("qualification_result") is None:
                trace["qualification_result"] = (
                    "PASS" if qual.get("qualified") else "REJECTED")
                trace["qualification_reason"] = qual.get("reason")
            record = build_record(
                session_id=getattr(telem, "session_id", "") or "UNSCOPED",
                scan_id=scan.get("snapshot_id"),
                timestamp_et=scan.get("market_data_timestamp"),
                instrument="MNQ",
                contract=str(getattr(self.cycle, "contract_id", "") or ""),
                parsed=parsed, trace=trace,
                disposition=terminal_disposition(
                    reason, created=(disposition == "CANDIDATE")),
                rejection_reason=reason, detail=detail)
            record["active_draw"] = str(parsed.get("active_draw") or "")[:200]
            record["invalidation_level"] = parsed.get("invalidation_level")
            with open(_os.path.join(root, "candidate_decisions.jsonl"), "a",
                      encoding="utf-8") as fh:
                fh.write(_json.dumps(record, default=str) + chr(10))
        except Exception:  # noqa: BLE001 -- evidence must never gate a scan
            pass

    def _attach_evidence(self, candidate, scan: dict) -> None:
        """Bind this scan's two-Brain and doctrine evidence to the candidate.

        THE JOIN IS BY snapshot_id, never by timestamp, direction or price.
        Reconstructing "which shadow observation belonged to this trade" from
        proximity is precisely the inference that once attributed a manual fill
        to the bot.

        Absence stays absence: a candidate may legitimately exist while the
        deterministic lane stood down, failed to bind, hit the adjudication cap,
        or was switched off entirely. None of those may invalidate a real trade.

        Never raises.
        """
        try:
            import copy as _copy

            snapshot_id = scan.get("snapshot_id")
            shadow = scan.get("two_brain_shadow")
            # SAME-SCAN LAW. The shadow rides the same scan dict, so identity is
            # structural -- but prove it rather than assume it.
            if shadow is not None and not isinstance(shadow, dict):
                shadow, linkage = None, "UNAVAILABLE"
            elif shadow is None:
                from ai_brain.two_brain import two_brain_mode
                linkage = "OFF" if two_brain_mode() == "off" else "UNAVAILABLE"
            else:
                linkage = "SAME_SCAN"

            envelope = (shadow or {}).get("envelope") or {}
            proposal = envelope.get("mechanical_proposal") or {}
            review = envelope.get("terra_review") or {}
            brain = scan.get("brain_result") or {}
            parsed = brain.get("parsed") or {}
            trace = dict(getattr(self.producer, "last_decision_trace", None) or {})

            evidence = {
                "snapshot_id": snapshot_id,
                "two_brain_linkage": linkage,
                "shadow_outcome": (shadow or {}).get("outcome"),
                "production_brain": {
                    "source": brain.get("source"),
                    "model": brain.get("model"),
                    "direction": parsed.get("narrative_direction"),
                    "action": str(parsed.get("current_action") or "")[:120],
                    "objective_id": parsed.get("objective_id"),
                    "invalidation_id": parsed.get("invalidation_id"),
                },
                "two_brain_shadow": {
                    "mechanical_proposal_id": proposal.get("mechanical_proposal_id"),
                    "mechanical_direction": proposal.get("direction"),
                    "objective_id": proposal.get("objective_id"),
                    "invalidation_id": proposal.get("invalidation_id"),
                    "reward_to_risk": proposal.get("reward_to_risk"),
                    "terra_verdict": review.get("verdict"),
                    "terra_confidence": review.get("confidence"),
                    "material_contradictions": review.get("material_contradictions"),
                    "would_have_done": (shadow or {}).get("would_have_done"),
                    "hybrid_disposition": envelope.get("hybrid_disposition"),
                    "authority_mode": envelope.get("authority_mode"),
                },
                "rr_doctrine": {
                    "reward_risk": trace.get("reward_risk"),
                    "reward_risk_floor": trace.get("reward_risk_floor"),
                    "legacy_reward_risk_floor": trace.get("legacy_reward_risk_floor"),
                    "legacy_floor_verdict": trace.get("legacy_floor_verdict"),
                    "eligible_only_because_floor_moved": trace.get(
                        "eligible_only_because_floor_moved"),
                },
                # The Combine governor lives on another branch and is NOT in this
                # build. Recorded as absent rather than fabricated.
                "profit_governor": None,
            }
            # DETACHED. Evidence attached to a candidate is historical fact; a
            # later mutation of the snapshot must not rewrite what was recorded.
            extras = getattr(candidate, "extras", None)
            if isinstance(extras, dict):
                extras["evidence"] = _copy.deepcopy(evidence)
                extras["two_brain_shadow"] = _copy.deepcopy(shadow)
                extras["decision_trace"] = _copy.deepcopy(trace)
                extras["brain_result"] = {
                    "model": brain.get("model"), "source": brain.get("source"),
                    "parsed": _copy.deepcopy(parsed)}
        except Exception:  # noqa: BLE001 -- evidence plumbing may never cost a trade
            pass

    @staticmethod
    def _narrative_telemetry(brain: dict) -> dict:
        """Direction, allowed direction and action -- always reported separately."""
        out = (brain or {}).get("output") or {}
        return {"direction": out.get("narrative_direction"),
                "allowed_direction": out.get("allowed_direction"),
                "action": out.get("current_action"),
                "phase": out.get("narrative_phase"),
                "phase_confidence": out.get("phase_confidence")}

    def _capital_identity(self) -> dict:
        """Identity every capital observation is bound to."""
        from adaptive_learning.capital_intelligence_engine import capital_identity
        acct = getattr(self.ps.session, "account", None)
        return capital_identity(
            venue="TOPSTEPX",
            account_fingerprint=self.ps.account_fingerprint,
            account_mode="COMBINE_SIMULATED" if getattr(acct, "simulated", True)
            else "COMBINE_LIVE",
            currency="USD")

    def _topstep_account(self) -> dict:
        """Equity from the PINNED Topstep account — never another venue's."""
        acct = getattr(self.ps.session, "account", None)
        balance = getattr(acct, "balance", None)
        return {"equity": balance} if balance is not None else {}

    # ── one iteration ─────────────────────────────────────────────────────────
    def scan_once(self) -> dict:
        # Stamp every paid AI request this scan makes with the session and scan
        # it belongs to. Set here rather than threaded through `_call_llm`,
        # whose signature is a contract the test doubles depend on.
        try:
            from ai_brain import narrative_brain as _nb
            _nb.set_call_context(session_id=self.mission.authorization.session_id,
                                 scan=len(self.outcomes) + 1)
        except Exception:  # noqa: BLE001 — accounting may never cost a scan
            pass
        out = self._scan_once()
        self.outcomes.append(out)
        return out

    #: How far back "recent market history" reaches, in ELAPSED MINUTES. Five
    #: hours covers an RTH session with warm-up; it is a time bound because a
    #: bar count is exactly what produced a three-day window.
    HISTORY_HORIZON_MINUTES = 300
    #: Enough contiguous closed minutes for the detectors to confirm a pivot and
    #: for the 15m series to carry more than a couple of buckets. Below this the
    #: honest answer is "not enough history", not "reach further back".
    HISTORY_MINIMUM_BARS = 60

    def _repair_history_if_holed(self, bars: list) -> list:
        """Repair a runtime gap, then re-read. Never raises; never fabricates.

        A provider that cannot repair leaves the bars untouched, the gap stays
        visible in `degraded[]`, and the producer keeps refusing. Recovery is
        attempted, never assumed -- the re-fetch is what proves it, not the
        call returning.
        """
        try:
            report = CONT.summarize(bars, timeframe="1m")
            if report.get("continuous"):
                return bars
            repair = getattr(self.candles, "repair_gaps", None)
            if repair is None:
                return bars
            outcome = repair()
            self.last_repair = outcome
            if not outcome.get("repaired"):
                return bars
            return self.candles.fetch_1m_candles(self.symbol, lookback_bars=300) or bars
        except Exception as exc:  # noqa: BLE001 — repair may never cost a scan
            self.last_repair = {"error": f"{type(exc).__name__}: {exc}"}
            return bars

    def reconcile_missions(self) -> dict:
        """Bring every non-terminal mission up to date with the venue.

        Runs BEFORE each scan's decisions. V13's lesson is that a mission which
        never learns what the venue did wedges the whole session: the trade
        filled and stopped out, the mission stayed ATTEMPT_CONSUMED, and every
        later scan refused with "a trade mission is already active".

        Never raises. A reconciliation failure must not cost a scan -- it leaves
        the mission exactly as it was, which is the safe direction.
        """
        report = []
        try:
            reconciler = RECON.MissionReconciler(
                venue=self.ps.session, contract_id=self.ps.contract.id,
                clock=self.clock)
            for mission in self.mission.load_existing():
                if mission.state in MS.TERMINAL_STATES:
                    continue
                tag = (getattr(self.ps.runner, "submission_custom_tag", "")
                       or "") if self.ps.runner else ""
                report.append(reconciler.reconcile(mission, custom_tag=tag))
        except Exception as exc:  # noqa: BLE001 — reconciliation never costs a scan
            return {"error": f"{type(exc).__name__}: {exc}", "reports": report}
        return {"reports": report}


    # ── BREAK-EVEN-2B — THE ONE PRODUCTION OWNER OF BREAK-EVEN ACTUATION ──────
    def manage_open_position(self) -> dict:
        """Deterministically advance protection on a live position. No cognition.

        THIS IS THE SINGLE CALL SITE. Nothing else in production may invoke
        `break_even_actuator`: two owners could each read fresh truth, each see
        an eligible advance, and each send a write, which is exactly the
        duplicate mutation the exactly-once-EFFECT law exists to forbid. It is
        called from `_scan_once` immediately after reconciliation and BEFORE the
        entry-authority gate, so it runs identically while trading and while the
        session is MANAGEMENT_ONLY with the cap spent.

        NO MODEL IS CONSULTED. Every input is durable evidence or fresh venue
        truth: the actual fill and original stop come from the mission record
        and submission ledger, the trigger from the governed executable quote,
        the price from the certified cost-adjusted geometry, and the monotonic
        law from `protection_state`. That is what lets it keep working after
        entry authority is exhausted, where consulting a provider is forbidden.

        Never raises: management may not cost a scan.
        """
        def out(status, **extra):
            return dict({"status": status}, **extra)

        # THE NO-OP PATH MUST BE FREE. This runs on EVERY tick and the
        # overwhelming majority have nothing to manage, so the cheap durable
        # checks come first and the break-even modules are not imported at all
        # until there is a live position. Paying four module loads inside the
        # scan to discover there is no position lengthens the tick for no
        # reason -- and a longer scan measurably shifts the event-wake timing
        # that the loop's own deadline-based wait is built around.
        try:
            mission = self.mission.active_mission
            if mission is None or mission.order_id is None:
                return out("no_live_mission")
            if mission.state not in (MS.POSITION_OPEN, MS.EXIT_PENDING_RECONCILIATION):
                return out("mission_not_position_open", state=mission.state)

            from broker import break_even as BE
            from broker import break_even_actuator as ACT
            from broker import break_even_baseline as BB
            from broker import topstepx_submission_record as SUBREC

            # R FROM PRIMITIVES. The recovered baseline is actual fill + ORIGINAL
            # initial stop -- never the live stop, which may already have moved,
            # and never the requested entry, which is not a fill.
            index = getattr(mission, "_slot", None) or 1
            baseline = BB.recover(
                mission_path=self.mission.mission_path(index),
                submissions_path=SUBREC.ledger_path(
                    self.mission.store_dir, self.mission.authorization.session_id))
            if baseline.get("status") != BB.RECOVERED:
                return out("baseline_unavailable", baseline=baseline)

            direction = baseline.get("direction")
            # FRESH EXECUTABLE QUOTE, SIDED. A long is triggered by the BID it
            # could exit into; a short by the ASK it would pay to cover. The
            # freshness ceiling lives in `topstepx_execution_price`, which
            # returns None rather than a stale number -- and None means HOLD.
            trigger = self._sided_trigger_price(direction)
            if trigger is None:
                return out("no_fresh_quote", direction=direction)

            ctx = getattr(self.ps.runner, "execution_context", None) if self.ps.runner else None
            armed = bool(getattr(ctx, "protection_baseline_armed", False))
            active_stop = getattr(ctx, "active_protective_stop", None)

            decision = BE.evaluate(
                direction=direction,
                entry_fill_price=baseline.get("entry_fill_price"),
                initial_stop_price=baseline.get("original_initial_stop"),
                active_protective_stop=active_stop,
                current_price=trigger, armed=armed,
                contract=self.ps.contract,
                quantity=baseline.get("quantity") or 1)
            if decision.get("outcome") != BE.PROPOSE:
                # The baseline travels with a DECLINE too: "why did break-even
                # not fire" needs the same primitives as "why did it".
                return out("decision_declines", decision=decision,
                           trigger=trigger, baseline=baseline)

            # ── BREAK-EVEN-2C — WRITE-AHEAD AND THE UNRESOLVED LATCH ────────
            #
            # Measured before this existed: an accepted-but-unproven modify was
            # correctly classified `retryable=False` and then re-sent on EVERY
            # subsequent tick (5 writes in 5 ticks), because the flag lived only
            # in RAM. A restart knew nothing at all. The latch below is what
            # makes exactly-once-EFFECT survive both.
            from broker import break_even_journal as JOURNAL
            store = self.mission.store_dir
            session_id = self.mission.authorization.session_id
            proposed = decision.get("break_even_price")

            probe = ACT.inspect_protection(
                session=self.ps.session, contract_id=self.ps.contract.id,
                entry_order_id=mission.order_id)
            # TWO DIFFERENT ABSENCES, TWO DIFFERENT ANSWERS.
            #
            # NO VENUE TRUTH -> silence. The effect id binds the stop order id,
            # so an unreadable venue would mint a DIFFERENT identity and the
            # latch could not recognise its own unresolved write. Bail before
            # any journal row exists: a spurious intent under a bogus identity
            # is worse than no row at all.
            if not probe.get("known"):
                return out("venue_unreadable_for_effect_identity",
                           probe_errors=probe.get("errors"), decision=decision,
                           baseline=baseline)
            # THREE ANSWERS, NOT TWO. `stop` being falsy used to mean one
            # thing here, and it meant it too loudly: the response to "no owned
            # stop" is to FLATTEN A LIVE POSITION.
            #
            # But `searchOpen` omits Suspended bracket children by venue
            # contract, and that was the only surface this probe ever read. A
            # perfectly protected trade whose stop happened to be staged would
            # present as unprotected, and the safety response would destroy it.
            # An imagined danger must not be answered with a real one.
            #
            #     PRESENT  a stop is proven -> manage it
            #     UNKNOWN  the view was incomplete -> HOLD, change nothing
            #     ABSENT   a COMPLETE view proves none -> certified authority
            presence = probe.get("presence")
            if presence == DISC.UNKNOWN:
                return out("protection_unknown_discovery_incomplete",
                           decision=decision, baseline=baseline, probe=probe,
                           discovery=probe.get("discovery"))
            if presence == DISC.ABSENT or not (probe.get("stop") or {}).get("id"):
                flat = (self.ps.runner.emergency_flatten(
                    "break-even management found no owned protective stop on a "
                    f"live position: {probe.get('problem') or 'none provable'}")
                    if self.ps.runner else None)
                return out("protection_defect", decision=decision,
                           baseline=baseline, probe=probe, flattened=flat)

            stop_order_id = (probe.get("stop") or {}).get("id")
            eid = JOURNAL.effect_id(
                mission_id=mission.mission_id, contract_id=self.ps.contract.id,
                entry_order_id=mission.order_id, stop_order_id=stop_order_id,
                proposed_stop=proposed,
                account_fingerprint=baseline.get("account_fingerprint") or "")

            # RECONCILE-BEFORE-RETRY, ENFORCED. A prior attempt at THIS exact
            # effect may still be in flight at the venue, so no second mutation
            # may be issued. `apply_break_even` is still called -- it re-reads
            # the venue and will HOLD if the effect landed -- but it is called
            # in a mode that cannot write.
            latched = JOURNAL.is_unresolved(store, session_id, eid)
            if latched:
                resolved = ACT.apply_break_even(
                    session=self.ps.session, contract_id=self.ps.contract.id,
                    entry_order_id=mission.order_id, direction=direction,
                    proposed_stop=proposed,
                    expected_size=baseline.get("quantity"), may_write=False)
                JOURNAL.record(store_dir=store, session_id=session_id,
                               effect_id=eid,
                               state=_journal_state_for(resolved, JOURNAL),
                               outcome=resolved.get("outcome"),
                               reason=resolved.get("reason"),
                               active_protective_stop=resolved.get(
                                   "active_protective_stop"),
                               recovered=True)
                return out("unresolved_effect_reconciled", actuation=resolved,
                           decision=decision, effect_id=eid, baseline=baseline)

            # WRITE-AHEAD. No durable intent, no venue mutation: an ambiguous
            # money-moving effect that a restart forgets is exactly the class of
            # bug this unit exists to remove.
            wrote_intent = JOURNAL.record(
                store_dir=store, session_id=session_id, effect_id=eid,
                state=JOURNAL.INTENT, direction=direction,
                entry_order_id=mission.order_id, stop_order_id=stop_order_id,
                target_order_id=(probe.get("target") or {}).get("id"),
                mission_id=mission.mission_id,
                entry_fill_price=baseline.get("entry_fill_price"),
                original_initial_stop=baseline.get("original_initial_stop"),
                initial_risk_points=baseline.get("initial_risk_points"),
                quantity=baseline.get("quantity"),
                current_protective_stop=(probe.get("stop") or {}).get("stop_price"),
                target_price=(probe.get("target") or {}).get("limit_price"),
                proposed_stop=proposed, trigger_price=trigger,
                trigger_side="bid" if str(direction).lower() in ("long", "bullish")
                else "ask")
            if not wrote_intent:
                return out("intent_not_persisted", decision=decision,
                           effect_id=eid, baseline=baseline)

            applied = ACT.apply_break_even(
                session=self.ps.session, contract_id=self.ps.contract.id,
                entry_order_id=mission.order_id, direction=direction,
                proposed_stop=proposed,
                expected_size=baseline.get("quantity"))

            # POST-WRITE. If THIS fails to persist, the local picture is
            # already potentially ambiguous -- the intent is on disk, so the
            # latch still forbids a blind second write on the next tick, which
            # is the fail-closed direction.
            JOURNAL.record(store_dir=store, session_id=session_id, effect_id=eid,
                           state=_journal_state_for(applied, JOURNAL),
                           outcome=applied.get("outcome"),
                           reason=applied.get("reason"),
                           active_protective_stop=applied.get("active_protective_stop"),
                           previous_protective_stop=applied.get(
                               "previous_protective_stop"),
                           target=applied.get("target"),
                           venue_rejection=applied.get("venue_rejection"),
                           error=applied.get("error"))

            # PROTECTION DEFECT IS NOT AN ORDINARY BREAK-EVEN FAILURE.
            #
            # A failed advance normally HOLDS because the ORIGINAL stop still
            # protects the trade. That reasoning collapses when the owned stop
            # itself is gone: the position is live and unprotected, and no
            # stop-price amendment can repair it. It is routed into the ALREADY
            # CERTIFIED safety authority -- `emergency_flatten` closes and
            # cancels and then PROVES both -- rather than growing a second
            # flatten implementation inside break-even.
            if applied.get("outcome") == ACT.PROTECTION_DEFECT and self.ps.runner:
                flat = self.ps.runner.emergency_flatten(
                    f"break-even management found no owned protective stop on a "
                    f"live position: {applied.get('detail')}")
                return out("protection_defect", actuation=applied,
                           decision=decision, flattened=flat, effect_id=eid)

            return out(applied.get("outcome"), actuation=applied,
                       decision=decision, trigger=trigger, baseline=baseline,
                       effect_id=eid)
        except Exception as exc:  # noqa: BLE001 — management never costs a scan
            return out("error", error=f"{type(exc).__name__}: {str(exc)[:200]}")

    def _sided_trigger_price(self, direction):
        """The governed executable quote for THIS side, or None.

        Asks the same authority the submit boundary asks. `executable_price`
        owns the freshness ceiling and returns None for a stale capture, so a
        settled close can never become a management trigger -- the defect
        EXEC-PRICE-FRESHNESS-1 removed.
        """
        try:
            from broker.topstepx_execution_price import executable_price, from_capture
            block = from_capture(self.ps.quote_provider.capture())
            side = "bearish" if str(direction).lower() in ("long", "bullish") else "bullish"
            return executable_price(block, side)
        except Exception:  # noqa: BLE001 — unavailable, never fabricated
            return None

    def _scan_once(self) -> dict:
        # Venue reality first, decisions second.
        self.last_reconciliation = self.reconcile_missions()
        # Deterministic protection management, on every tick, in every
        # mode. Placed BEFORE the entry-authority gate so it keeps
        # running once the cap is spent and cognition is off.
        self.last_management = self.manage_open_position()
        # SESSION-CAP-GRACEFUL-SHUTDOWN-1. ENTRY AUTHORITY AND RESPONSIBILITY
        # ARE SEPARATE. This gate used to require `active_mission is None`, so a
        # session whose allowance was spent but whose trade was still live fell
        # THROUGH to the full scan -- candles, snapshot, Brain payload, Luna
        # call -- once per tick, to decide something it had no authority to act
        # on. On 2026-08-25 that stayed hidden only because the mission went
        # falsely terminal within 38s; repairing that (045c472) is exactly what
        # would have exposed it. Cognition stops at the cap; management does not.
        #
        # Reconciliation above has already run, so an open position keeps being
        # observed while the model is never consulted.
        if LIFECYCLE.entry_authority_exhausted(self.mission):
            state = LIFECYCLE.resolve(mission=self.mission,
                                      venue=self.ps.session,
                                      contract_id=self.ps.contract.id)
            detail = (f"session maximum of "
                      f"{self.mission.authorization.maximum_trades} trades reached")
            if state["reasons"]:
                detail += "; " + "; ".join(state["reasons"])
            return {"outcome": state["mode"], "detail": detail,
                    "lifecycle": state}

        try:
            bars = self.candles.fetch_1m_candles(self.symbol, lookback_bars=300)
        except Exception as exc:  # noqa: BLE001 — a stale feed is not a stand-down
            return {"outcome": NO_CANDLES, "detail": f"{type(exc).__name__}: {exc}"}
        if not bars:
            return {"outcome": NO_CANDLES, "detail": "provider returned no candles"}

        # CANDLE-CONTINUITY 2a. The production caller for runtime repair.
        #
        # Startup warm-up cannot help a hole opened mid-session by a reconnect
        # or a feed stall. Detecting one and staying refused forever is safe but
        # not recovery, so the tape is repaired here and re-fetched; the scan
        # cycle then sees the past has changed and re-derives its own state
        # before deciding anything. This loop never rebuilds market cognition
        # itself -- the provider owns history, the cycle owns derived state.
        bars = self._repair_history_if_holed(bars)

        # CANDLE-CONTINUITY 2c. A WINDOW, not a pile of observations.
        #
        # `lookback_bars=300` asks for the last 300 records the store happens to
        # hold. On 2026-08-11 that reached from Aug 07 to Aug 11 -- three
        # calendar days, six gaps, 5,414 missing minutes -- and `find_swings`
        # confirmed pivots against "neighbours" days apart. 29,752.50 became a
        # 5m/15m swing low that way and from there the draw Terra was handed.
        # The detector was mechanically correct; its input contract simply
        # never required the records to be adjacent in time.
        #
        # Bounded, continuous, and aligned to a 15m boundary so no derived
        # timeframe inherits a fabricated leading bucket. Too little coherent
        # history is DEGRADATION, never permission to stitch older bars.
        coherent = CONT.coherent_window(
            bars, horizon_minutes=self.HISTORY_HORIZON_MINUTES,
            minimum_bars=self.HISTORY_MINIMUM_BARS)
        self.last_window = coherent
        if not coherent["sufficient"]:
            return {"outcome": NO_CANDLES,
                    "detail": f"incoherent market history: {coherent['reason']}",
                    "window": {k: coherent[k] for k in
                               ("bars", "span_minutes", "offered",
                                "discarded_as_incoherent", "continuous")}}
        bars = coherent["window"]

        # CROSS-SESSION DEPTH, FETCHED SEPARATELY. The scan window above stays
        # exactly 300 coherent minutes -- nothing downstream sees more market
        # than it did before. This second bounded request exists only so
        # `session_context` can reach back to the CME day open at 18:00 ET the
        # previous evening; the bound is proven in the focused tests, not
        # asserted by comment. A failure here costs CONTEXT, never the scan.
        try:
            deep = self.candles.fetch_1m_candles(
                self.symbol, lookback_bars=SESSION_CONTEXT_DEEP_BARS)
        except Exception:                       # noqa: BLE001 — context is not
            deep = None                         # worth losing a scan over
        scan = self.cycle.scan(bars, now=self.clock(), deep_1m=deep)
        brain = scan["brain_block"]
        source = (brain or {}).get("source")

        # Degraded is a BRAIN failure, not a market stand-down. Reporting it as
        # "no setup" would quietly convert an outage into evidence about price.
        if not ProductionScanCycle.is_sovereign(brain):
            # A fallback_reason means the read was repaired or substituted, even
            # when source still says llm. That is degradation, not a quiet market.
            if (brain or {}).get("fallback_reason") or source in (
                    "degraded", "llm_failed_fallback", "fallback", "deterministic"):
                return {"outcome": BRAIN_DEGRADED, "source": source,
                        "detail": ((brain or {}).get("fallback_reason")
                                   or "; ".join((brain or {}).get("warnings") or [])
                                   or "brain did not return a sovereign read"),
                        "scan": scan["scan_count"]}
            return {"outcome": NO_CANDIDATE, "source": source,
                    "detail": "no sovereign directional thesis", "scan": scan["scan_count"]}

        in_window = bool(self._in_window())
        try:
            candidate = self.producer.produce(
                brain_result=scan["brain_result"], brain_input=scan["brain_input"],
                snapshot=scan["snapshot"], qualification=scan["qualification"],
                engine_inventory=scan["engine_inventory"],
                snapshot_id=scan["snapshot_id"],
                market_data_timestamp=scan["market_data_timestamp"],
                latest_closed_bar_timestamp=scan["latest_closed_bar_timestamp"],
                in_window=in_window, now=self.clock())
        except NoCandidate as exc:
            self._record_decision(scan, "REJECTED", exc.reason, str(exc))
            outcome = WINDOW_CLOSED if exc.reason == "window_closed" else NO_CANDIDATE
            # Direction and action are reported separately. Rendering a bearish
            # stand-down and a genuinely conflicted market both as bare
            # NO_CANDIDATE hides the one fact an operator most needs: whether the
            # organism has a directional read at all.
            return {"outcome": outcome, "reason": exc.reason, "detail": str(exc),
                    "stand_down": getattr(exc, "stand_down", False),
                    **self._narrative_telemetry(brain), "scan": scan["scan_count"]}

        # EVIDENCE-SUBSTRATE-PHASE0 — attach the same-scan evidence the flight
        # recorder will need at fill time. Capture only: nothing downstream reads
        # it, and it is attached AFTER the candidate already exists, so it cannot
        # participate in whether one was created.
        self._attach_evidence(candidate, scan)
        self._record_decision(scan, "CANDIDATE", None, "")
        self.mission.candidate_count += 1
        # A newer candidate supersedes the prior one; stale candidates are never
        # carried between scans.
        self.active_candidate = candidate

        # LUNA-DAILY-LOSS-BUDGET-GOVERNOR-1 — THE SESSION LOSS BUDGET.
        #
        # Resolved HERE, after a candidate exists and BEFORE any trade mission or
        # attempt is opened. That ordering is the point: risk truth we could not
        # establish is not a trade the session should pay an attempt for, so a
        # venue read failure, incomplete discovery or an unattributable
        # in-session fill refuses the entry without spending anything.
        #
        # It cannot reach management. `manage_open_position()` already ran at the
        # top of this tick by SESSION-CAP-GRACEFUL-SHUTDOWN-1 ordering, so an
        # exhausted or unknown budget never touches a live position's protection.
        budget = DLB.resolve(
            session=self.ps.session, contract_id=self.ps.contract.id,
            missions=self.mission.trade_missions,
            authorization=self.mission.authorization,
            max_risk_usd=PRODUCTION_MAX_RISK_USD,
            window_start=SA.PRODUCTION_WINDOW_START,
            tz_name=SA.PRODUCTION_WINDOW_TZ)
        self.last_daily_loss = budget
        if not budget["entry_permitted"]:
            self._record_decision(scan, "REJECTED", budget["state"],
                                  budget.get("reason") or "")
            return {"outcome": NO_CANDIDATE, "reason": budget["state"],
                    "detail": (f"daily loss budget {budget['state']}: "
                               f"{budget.get('reason')}"),
                    "daily_loss": budget, "stand_down": True,
                    **self._narrative_telemetry(brain), "scan": scan["scan_count"]}

        # Production sizing. A rejection here is the doctrine working: the
        # invalidation is the thesis and is never moved to make a setup fit.
        try:
            self.ps.runner = None                 # a new candidate, a new bracket
            runner = self.ps.build_runner(
                candidate, max_risk_usd=budget["allowed_planned_risk"])
        except RiskRejection as exc:
            return {"outcome": RISK_REJECTED, "candidate_id": candidate.candidate_id,
                    "reason": getattr(exc, "reason", ""), "detail": str(exc),
                    "scan": scan["scan_count"]}

        sized = {"size": runner.geometry.size,
                 "stop_points": runner.geometry.stop_points,
                 "stop_price": runner.geometry.stop_price,
                 "target_price": runner.geometry.target_price,
                 "risk_usd": runner.geometry.risk_usd,
                 "stop_range": self.ps.sizing["stop_range"],
                 "reward_to_risk": self.ps.sizing["reward_to_risk"]}

        if not self.armed:
            # THE BOUNDARY. No token is minted and no attempt is consumed:
            # everything above ran, and nothing below is reachable.
            return {"outcome": QUALIFIED_CANDIDATE_OBSERVED,
                    "execution": EXECUTION_DISARMED,
                    "candidate_id": candidate.candidate_id,
                    "candidate_fingerprint": candidate.fingerprint(),
                    "direction": candidate.direction, "sizing": sized,
                    "objective": candidate.objective.identity,
                    "scan": scan["scan_count"]}

        return self._execute(candidate, scan, sized, in_window)

    # ── armed only ────────────────────────────────────────────────────────────
    def _execute(self, candidate, scan: dict, sized: dict, in_window: bool) -> dict:
        positions = self.ps.session.open_positions()
        # CANONICAL DISCOVERY, AND IT RAISES. This count gates whether a trade
        # mission may open at all: a Suspended residual child must be able to
        # block it, and an UNREADABLE venue must never be able to clear it. The
        # read it replaced threw on failure, so the scan died before a mission
        # existed; silently returning an empty list here would open one.
        orders = DISC.require_working_orders(
            self.ps.session, contract_id=self.ps.contract.id)
        unknown = self.ps.ledger.requires_pause() is not None
        try:
            mission = self.mission.open_trade_mission(
                positions=len(positions), working_orders=len(orders),
                unknown_external=unknown, in_window=in_window)
        except SA.AuthorizationRefused as exc:
            return {"outcome": TRADE_MISSION_REFUSED, "detail": str(exc),
                    "candidate_id": candidate.candidate_id}

        snap = scan["snapshot"]
        market = {
            "current_price": candidate.entry_price,
            "high_since": (snap.get("market") or {}).get("high_since", candidate.entry_price),
            "low_since": (snap.get("market") or {}).get("low_since", candidate.entry_price),
            "tick_size": self.ps.contract.tick_size,
            "snapshot_id": candidate.snapshot_id,
            "contract_id": self.ps.contract.id,
            "account_fingerprint": self.ps.account_fingerprint,
            "account_state_digest": "", "data_age_seconds":
                self.runtime.health().get("last_quote_age") or 0.0,
            "in_window": in_window, "manual_activity": unknown,
            "now": self.clock()}

        def mint():
            self.mission.token_count += 1
            return auth.issue(
                phrase=auth.AUTHORIZATION_PHRASE,
                account_fingerprint=self.ps.account_fingerprint,
                contract_id=self.ps.contract.id,
                candidate_fingerprint=candidate.fingerprint(),
                snapshot_id=candidate.snapshot_id, direction=candidate.direction,
                stop_price=candidate.invalidation_price,
                target_price=candidate.objective.price,
                target_identity=candidate.objective.identity,
                max_risk_usd=self.mission.authorization.maximum_risk_per_trade,
                max_contracts=self.mission.authorization.maximum_contracts,
                # PROD-20260810 DEFECT. Risk and contracts were bound to the
                # authorization; the stop ceiling was not passed at all, so
                # `issue()` fell through to its SMOKE_MAX_STOP_POINTS default of
                # 10 points. A legitimate 33.75-point structural stop -- well
                # inside the 35/40 doctrine -- halted at TOKEN_BINDING_MISMATCH
                # before any order endpoint, and burned a trade mission.
                #
                # Bound to the SAME authorization object the other two limits
                # come from, so there is no third source of truth: the value is
                # already fingerprinted into the authorization and already
                # refused above 40 by AUTHORIZATION_EXCEEDS_DOCTRINE.
                max_stop_points=self.mission.authorization.absolute_stop_ceiling,
                # The venue tag is the only attribution evidence a Topstep
                # order carries. A production order must not say "smoke".
                token_prefix=auth.PRODUCTION_TOKEN_PREFIX,
                now=self.clock())

        def on_consumed(token_id: str):
            # Durable BEFORE the request leaves. A crash after this point finds
            # the attempt already spent and reconciles instead of re-entering.
            mission.consume_attempt(candidate_fingerprint=candidate.fingerprint(),
                                    token_id=token_id)
            self.mission.entry_attempt_count += 1

        def on_acknowledged(order_id):
            # MISSION-LIFECYCLE. The hop V13 did not have. Raising here is the
            # point: the runner turns it into SUBMISSION_RECORD_WRITE_FAILED and
            # halts, because an acknowledged order we cannot record is the one
            # case where carrying on is worse than stopping.
            mission.record_venue_acknowledgement(
                venue_order_id=order_id,
                session_id=self.mission.authorization.session_id,
                authorization_fingerprint=self.mission.authorization.fingerprint(),
                submitted_at=self.clock().isoformat(),
                evidence="venue ack at submit")

        # The runner was already built during sizing, so `build_runner` will not
        # run again inside `submit()` -- these must land on BOTH the session
        # (for any later rebuild) and the live runner, or the hook silently
        # never fires. That is precisely the failure shape this whole mission
        # exists to remove, so it is wired in both places deliberately.
        self.ps.acknowledgement_hook = on_acknowledged
        self.ps.trade_mission_id = mission.mission_id
        if self.ps.runner is not None:
            self.ps.runner.on_venue_acknowledged = on_acknowledged
            self.ps.runner.submission_mission_id = mission.mission_id

        try:
            result = self.ps.submit(
                candidate=candidate, market=market,
                latest_price=candidate.entry_price, mint_token=mint,
                account_id=self.account_id, on_attempt_consumed=on_consumed)
        except (CandidateStale, Exception) as exc:  # noqa: BLE001
            return {"outcome": SUBMIT_FAILED, "detail": f"{type(exc).__name__}: {exc}",
                    "candidate_id": candidate.candidate_id, "sizing": sized,
                    "mission_state": mission.state,
                    "attempt_consumed": mission.attempt_count > 0}

        return {"outcome": SUBMITTED, "candidate_id": candidate.candidate_id,
                "sizing": sized, "mission_id": mission.mission_id,
                "mission_state": mission.state, "result": result,
                "attempt_consumed": mission.attempt_count > 0}

    # ── reconciliation ────────────────────────────────────────────────────────
    def reconcile_after_fill(self, *, candidate, fill_event: dict, trades: list,
                             orders: list, stop_order_id=None,
                             target_order_id=None) -> dict:
        out = self.ps.reconcile_entry(
            candidate=candidate, trades=trades, orders=orders, fill_event=fill_event,
            stop_order_id=stop_order_id, target_order_id=target_order_id)
        self.mission.filled_trade_count += 1
        return out

    def reconcile_after_exit(self, *, candidate, exit_type: str, trades: list,
                             orders: list, exit_order_id=None, fill_price=None,
                             quantity=None) -> dict:
        out = self.ps.reconcile_exit(
            candidate=candidate, exit_type=exit_type, trades=trades, orders=orders,
            exit_order_id=exit_order_id, fill_price=fill_price, quantity=quantity)
        self.mission.completed_round_trip_count = self.ps.slippage.round_trips()
        active = self.mission.active_mission
        if active is not None:
            active.transition("COMPLETE", f"exit reconciled ({exit_type})")
        return out

    def final_flat_state(self) -> dict:
        found = DISC.discover_orders(self.ps.session,
                                     contract_id=self.ps.contract.id)
        positions = self.ps.session.open_positions()
        orders = found["working"] or []
        return {"positions": len(positions), "working_orders": len(orders),
                "discovery": found["source"],
                # FLAT IS A POSITIVE CLAIM AND NEEDS A COMPLETE VIEW. An
                # incomplete surface can be silent about a Suspended child, and
                # the last state this session reports is the one an operator
                # trusts when deciding whether to walk away.
                "flat": bool(found["complete"]) and not positions and not orders,
                "counters": self.mission.counters(),
                "sample": self.ps.slippage.sample_status()}
