"""TOPSTEPX execution runner — one Luna-authored candidate, end to end.

Carries exactly ONE genuine qualified candidate through submit -> fill ->
protection -> exit -> verified flat, recording an evidence-backed, timestamped
transition for every step.

Three properties this is built around, because each is a way the mission can
fail badly rather than merely fail:

  ONE ENTRY, EVER. `_entry_attempted` latches on the first submit attempt and is
  never cleared. A second candidate, a retry after a timeout, or a second call
  into `run()` is refused. Duplicate live entries are the worst outcome here —
  worse than no trade, worse than a rejected trade.

  UNCERTAINTY IS NOT PERMISSION. An HTTP timeout after submit means the order
  may or may not exist. That is an UNKNOWN state and it is reconciled by asking
  the venue what is true — never by resubmitting.

  PROTECTION IS PROVEN, NOT ASSUMED. A fill without both protective orders
  observable within a bounded deadline triggers emergency flatten. An
  unprotected position on a Combine is how a trailing drawdown ends an
  evaluation in one move.

This module NEVER mints authorization. The operator's phrase mints a token
elsewhere; the runner only spends one.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from ai_brain import engine_payload_audit as engine_audit
from broker import topstepx_smoke_auth as smoke_auth
from broker import topstepx_emergency_liquidation as EL
from broker import topstepx_order_discovery as DISC
from broker import topstepx_submission_record as SUBREC
from broker.topstepx_client import TopstepXError
from broker.topstepx_combine_risk import (
    ABSOLUTE_MAX_STOP_POINTS, MAX_RISK_PER_TRADE_USD, MIN_REWARD_TO_RISK,
    PRODUCTION_MAX_CONTRACTS, PRODUCTION_MAX_RISK_USD, SMOKE_MAX_CONTRACTS,
    BracketGeometry, RiskRejection, build_bracket, risk_for, ticks_between,
)
from broker.topstepx_redaction import assert_clean

# ── states ────────────────────────────────────────────────────────────────────
DISARMED = "DISARMED"
READINESS_CONFIRMED = "READINESS_CONFIRMED"
AUTHORIZED = "AUTHORIZED"
WAITING_FOR_CANDIDATE = "WAITING_FOR_CANDIDATE"
CANDIDATE_RECEIVED = "CANDIDATE_RECEIVED"
CANDIDATE_VALIDATED = "CANDIDATE_VALIDATED"
RISK_APPROVED = "RISK_APPROVED"
SUBMITTING = "SUBMITTING"
ACKNOWLEDGED = "ACKNOWLEDGED"
FILLED = "FILLED"
PROTECTION_PENDING = "PROTECTION_PENDING"
#: EXEC-PRICE-ANCHOR-1 — the provisional fill-relative bracket has been replaced
#: by the authorized structural invalidation and objective, and the venue has
#: been asked to confirm it. Distinct from PROTECTED so evidence can never imply
#: structural anchoring was proven when only side agreement was checked.
PROTECTION_REANCHORED = "PROTECTION_REANCHORED"
PROTECTED = "PROTECTED"
EXIT_PENDING = "EXIT_PENDING"
FLAT = "FLAT"
VERIFIED_CLEAN = "VERIFIED_CLEAN"

TERMINAL_SUCCESS = (VERIFIED_CLEAN,)

# failure states
AUTH_EXPIRED = "AUTH_EXPIRED"
STALE_CANDIDATE = "STALE_CANDIDATE"
AI_TIMEOUT = "AI_TIMEOUT"
AI_FALLBACK = "AI_FALLBACK"
QUALIFICATION_REJECTED = "QUALIFICATION_REJECTED"
RISK_REJECTED = "RISK_REJECTED"
SUBMIT_REJECTED = "SUBMIT_REJECTED"
ACK_TIMEOUT = "ACK_TIMEOUT"
FILL_TIMEOUT = "FILL_TIMEOUT"
PROTECTION_MISSING = "PROTECTION_MISSING"
STREAM_STALE = "STREAM_STALE"
ACCOUNT_MISMATCH = "ACCOUNT_MISMATCH"
CONTRACT_MISMATCH = "CONTRACT_MISMATCH"
EMERGENCY_FLATTENING = "EMERGENCY_FLATTENING"
FLATTEN_FAILED = "FLATTEN_FAILED"
RESIDUAL_ORDERS = "RESIDUAL_ORDERS"
SUBMIT_UNKNOWN = "SUBMIT_UNKNOWN"
#: The venue answered and the answer could NOT be persisted. Its own state
#: because the operator response differs from every other failure: the trade
#: outcome may be perfectly fine while the evidence for it is missing.
SUBMISSION_RECORD_WRITE_FAILED = "SUBMISSION_RECORD_WRITE_FAILED"

# Ledger / freshness gates get their OWN names. Collapsing every refusal into a
# generic "validation failed" would hide which gate saved the account, and the
# lifecycle artifact has to be able to say exactly that.
EXTERNAL_ACTIVITY_DETECTED = "EXTERNAL_ACTIVITY_DETECTED"
EXTERNAL_ACTIVITY_UNRESOLVED = "EXTERNAL_ACTIVITY_UNRESOLVED"
CANDIDATE_STALE = "CANDIDATE_STALE"
OBJECTIVE_SWEPT = "OBJECTIVE_SWEPT"
OBJECTIVE_MATERIALLY_DELIVERED = "OBJECTIVE_MATERIALLY_DELIVERED"
INVALIDATION_TOUCHED = "INVALIDATION_TOUCHED"
SNAPSHOT_SUPERSEDED = "SNAPSHOT_SUPERSEDED"
ACCOUNT_STATE_CHANGED = "ACCOUNT_STATE_CHANGED"
RISK_DRIFTED = "RISK_DRIFTED"
REWARD_COLLAPSED = "REWARD_COLLAPSED"
TOKEN_BINDING_MISMATCH = "TOKEN_BINDING_MISMATCH"
MANUAL_ACTIVITY_DETECTED = "MANUAL_ACTIVITY_DETECTED"

# freshness reason -> runner state, so the artifact names the precise gate
_STALE_REASON_STATE = {
    "objective_swept": OBJECTIVE_SWEPT,
    "objective_materially_delivered": OBJECTIVE_MATERIALLY_DELIVERED,
    "invalidation_touched": INVALIDATION_TOUCHED,
    "snapshot_superseded": SNAPSHOT_SUPERSEDED,
    "account_state_changed": ACCOUNT_STATE_CHANGED,
    "manual_activity": MANUAL_ACTIVITY_DETECTED,
    "contract_changed": CONTRACT_MISMATCH,
    "data_stale": STREAM_STALE,
    "reward_below_floor": REWARD_COLLAPSED,
    "risk_above_cap": RISK_DRIFTED,
}

FAILURE_STATES = frozenset({
    AUTH_EXPIRED, STALE_CANDIDATE, AI_TIMEOUT, AI_FALLBACK, QUALIFICATION_REJECTED,
    RISK_REJECTED, SUBMIT_REJECTED, ACK_TIMEOUT, FILL_TIMEOUT, PROTECTION_MISSING,
    STREAM_STALE, ACCOUNT_MISMATCH, CONTRACT_MISMATCH, EMERGENCY_FLATTENING,
    FLATTEN_FAILED, RESIDUAL_ORDERS, SUBMIT_UNKNOWN,
    EXTERNAL_ACTIVITY_DETECTED, EXTERNAL_ACTIVITY_UNRESOLVED, CANDIDATE_STALE,
    OBJECTIVE_SWEPT, OBJECTIVE_MATERIALLY_DELIVERED, INVALIDATION_TOUCHED,
    SNAPSHOT_SUPERSEDED, ACCOUNT_STATE_CHANGED, RISK_DRIFTED, REWARD_COLLAPSED,
    TOKEN_BINDING_MISMATCH, MANUAL_ACTIVITY_DETECTED,
    SUBMISSION_RECORD_WRITE_FAILED,
})

# Engines whose ABSENCE makes a candidate ineligible. Emptiness may be a valid
# market state (no sweep happened); absence means the organ never reached the
# Brain at all, which is a wiring defect, not a market condition.
REQUIRED_ENGINES = (
    "market_structure", "liquidity", "po3", "volatility", "session_state",
    "adaptive_context", "vector_retrieval_analogs", "playbook_families",
    "tool_families", "thesis_lifecycle", "protected_levels", "delivery_state",
)

ACK_DEADLINE_SECONDS = 10.0
FILL_DEADLINE_SECONDS = 30.0
PROTECTION_DEADLINE_SECONDS = 15.0
MAX_MARKET_DATA_AGE_SECONDS = 90.0


class RunnerHalt(RuntimeError):
    """The runner stopped. `state` names the failure."""

    def __init__(self, state: str, detail: str = "") -> None:
        super().__init__(f"{state}: {detail}" if detail else state)
        self.state = state
        self.detail = detail


@dataclass
class Transition:
    state: str
    at: datetime
    detail: str = ""
    evidence: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"state": self.state, "at": self.at.isoformat(),
                "detail": assert_clean(self.detail, "transition"),
                "evidence": self.evidence}


@dataclass
class ExecutionRunner:
    """One-shot runner. Construct, `run()` once, read `artifact`."""

    session: Any                       # write-capable venue session
    account_fingerprint: str
    contract: Any                      # TopstepXContract
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)

    state: str = DISARMED
    transitions: list = field(default_factory=list)
    #: Flight-recorder context. Unset -> recording is off (smoke tools, tests).
    submission_store_dir: str = ""
    submission_session_id: str = ""
    submission_mission_id: str = ""
    submission_authorization_fingerprint: str = ""
    submission_record: dict = None
    #: Set when a venue answer could not be persisted. Never cleared silently.
    recording_failure: dict = None
    #: The customTag stamped on our entry; protective legs suffix it.
    submission_custom_tag: str = ""
    #: Called with the venue order id the instant the venue acknowledges, before
    #: the ack is reported upward. The mission-durability seam; None in the
    #: smoke tools and unit tests, which own no mission.
    on_venue_acknowledged: Optional[Any] = None
    #: Which doctrine actually judged this runner's trades. The runner is what
    #: enforces max_risk_usd / max_stop_points, so it is also what stamps them
    #: into the evidence -- V13 recorded the smoke constants on a production
    #: submission because `evidence()` imported them instead of being told.
    execution_lane: str = "smoke"
    #: EXEC-PRICE-ANCHOR-1 — does this runner own the PROMPT post-fill lifecycle?
    #:
    #: Set by `ProductionSession.build_runner` and nowhere else, so the smoke
    #: tools and the 54 existing `gated_submit` unit-test call sites keep their
    #: meaning: they assert submission gating, not fill acquisition, and a
    #: default-on hook would silently change what every one of them proves.
    #:
    #: Production forgetting to set it is the obvious failure mode, so
    #: `tests/test_exec_price_anchor.py` pins BOTH that `build_runner` sets it
    #: and that `gated_submit` honours it.
    prompt_fill_authority: bool = False
    #: How long the prompt lifecycle waits for the AUTHORITATIVE full fill.
    #: Injectable so a harness can exercise the deadline without spending it in
    #: wall-clock time; production leaves it at the module default.
    fill_deadline_seconds: float = FILL_DEADLINE_SECONDS
    #: Wall-clock source for BOUNDED WAITS only (never for decision timestamps).
    #: Separate from `clock` on purpose -- see `acquire_full_fill`.
    _elapsed: Optional[Any] = None
    #: Result of the prompt post-fill lifecycle. None -> it never ran.
    protection_outcome: dict = None
    artifact: dict = field(default_factory=dict)
    token: Optional[Any] = None
    geometry: Optional[BracketGeometry] = None
    order_id: Optional[int] = None
    entry_capture: Optional[Any] = None       # QuoteCapture taken at submit
    execution_context: Optional[Any] = None   # threaded identity for the exit
    # Caps the runner enforces at the final gate. Default to PRODUCTION
    # doctrine; the smoke tooling passes its own explicitly.
    max_risk_usd: float = PRODUCTION_MAX_RISK_USD
    max_stop_points: float = ABSOLUTE_MAX_STOP_POINTS
    max_contracts: int = PRODUCTION_MAX_CONTRACTS
    min_reward_to_risk: float = MIN_REWARD_TO_RISK
    capture_failure: Optional[str] = None
    submit_at: Optional[datetime] = None
    ack_at: Optional[datetime] = None
    _entry_attempted: bool = False
    _run_called: bool = False

    # ── transitions ───────────────────────────────────────────────────────────
    def _to(self, state: str, detail: str = "", evidence: dict = None) -> None:
        self.state = state
        self.transitions.append(Transition(state, self.clock(), detail, evidence or {}))

    def _stamp_governing_caps(self, geo):
        """Attach the ceilings THIS runner enforces to the geometry's evidence.

        Every geometry the runner accepts passes through here, so the recorded
        caps and the enforced caps cannot drift apart. `BracketGeometry` is
        frozen, so this returns a copy.
        """
        if geo is None:
            return geo
        return geo.governed_by(max_risk_usd=self.max_risk_usd,
                               max_stop_points=self.max_stop_points,
                               lane=self.execution_lane)

    def _halt(self, state: str, detail: str = "", evidence: dict = None):
        self._to(state, detail, evidence)
        raise RunnerHalt(state, detail)

    # ── 1. readiness + authorization ──────────────────────────────────────────
    def confirm_readiness(self, readiness: dict) -> None:
        if (readiness or {}).get("verdict") != "READY":
            self._halt(STALE_CANDIDATE, f"readiness verdict is {(readiness or {}).get('verdict')!r}")
        self._to(READINESS_CONFIRMED, "readiness artifact accepted",
                 {"readiness_ref": readiness.get("generated_at_utc")})

    def arm(self, token) -> None:
        """Accept an operator token. The runner never mints one."""
        if token is None:
            self._halt(AUTH_EXPIRED, "no operator authorization supplied")
        if token.spent:
            self._halt(AUTH_EXPIRED, "authorization already spent")
        if token.is_expired(self.clock()):
            self._halt(AUTH_EXPIRED, "authorization expired")
        self.token = token
        self._to(AUTHORIZED, "one-use authorization accepted", {"token": token.describe()})
        self._to(WAITING_FOR_CANDIDATE, "awaiting one qualified Luna-authored candidate")

    # ── 2. candidate intake ───────────────────────────────────────────────────
    def accept_candidate(self, candidate: dict) -> dict:
        """Validate one candidate against every intake requirement."""
        if self._entry_attempted:
            self._halt(RESIDUAL_ORDERS, "an entry was already attempted; no second candidate")
        self._to(CANDIDATE_RECEIVED, "candidate presented",
                 {"snapshot_id": candidate.get("snapshot_id")})

        prov = engine_audit.thesis_provenance(candidate.get("brain_result") or {})
        if not prov["is_live_llm"]:
            self._halt(AI_FALLBACK, f"thesis source is not the live LLM: {prov['fallback_reason']}",
                       {"provenance": prov})
        # UPGRADE-...-TERRA (2026-08-06): resolved from the single authority.
        # This was a THIRD hardcoded "gpt-5.6-luna" -- after the producer and the
        # pricing table. Each one silently halts every thesis from the new model
        # with no symptom other than trades never happening.
        from ai_brain.production_model import PRODUCTION_MODEL
        if prov["model"] != PRODUCTION_MODEL:
            self._halt(AI_FALLBACK,
                       f"thesis authored by {prov['model']!r}, not {PRODUCTION_MODEL}",
                       {"provenance": prov})
        if candidate.get("ai_state") == "AI_TIMEOUT":
            self._halt(AI_TIMEOUT, "candidate carries a timed-out Brain request")
        if candidate.get("ai_state") in ("AI_STALE", "AI_SUPERSEDED"):
            self._halt(STALE_CANDIDATE, f"brain guard reported {candidate.get('ai_state')}")

        if not candidate.get("sovereign"):
            self._halt(AI_FALLBACK, "candidate is not a sovereign conversion")
        direction = str(candidate.get("direction") or "").lower()
        if direction not in ("bullish", "bearish"):
            self._halt(QUALIFICATION_REJECTED, f"direction {direction!r} cannot author an entry")
        if not candidate.get("opportunity"):
            self._halt(QUALIFICATION_REJECTED, "no opportunity present")
        if not candidate.get("playbook_family") or not candidate.get("tool_family"):
            self._halt(QUALIFICATION_REJECTED, "missing legal playbook or tool family")
        if not candidate.get("qualified"):
            self._halt(QUALIFICATION_REJECTED, "existing qualification funnel refused it")

        # live engine inventory — absence is disqualifying, emptiness is reported
        inventory = engine_audit.audit_payload(candidate.get("brain_input") or {})
        missing = [e for e in REQUIRED_ENGINES
                   if inventory.get(e, {}).get("status") in
                   (engine_audit.ABSENT, engine_audit.BLOCKED)]
        if missing:
            self._halt(QUALIFICATION_REJECTED,
                       f"required engines absent/blocked in the live payload: {sorted(missing)}",
                       {"engine_inventory": inventory})
        empty = [e for e in REQUIRED_ENGINES
                 if inventory.get(e, {}).get("status") == engine_audit.PRESENT_BUT_EMPTY]

        # venue identity + state
        if candidate.get("account_fingerprint") != self.account_fingerprint:
            self._halt(ACCOUNT_MISMATCH, "candidate account fingerprint differs")
        if candidate.get("contract_id") != self.contract.id:
            self._halt(CONTRACT_MISMATCH, "candidate contract differs from the active contract")
        age = candidate.get("market_data_age_seconds")
        if age is None or float(age) > MAX_MARKET_DATA_AGE_SECONDS:
            self._halt(STREAM_STALE, f"market data age {age}s")
        if not candidate.get("user_stream_healthy"):
            self._halt(STREAM_STALE, "user hub is not healthy")

        positions = self.session.open_positions()
        orders = self.working_orders()
        if positions:
            self._halt(RESIDUAL_ORDERS, f"account is not flat ({len(positions)} position(s))")
        if orders:
            self._halt(RESIDUAL_ORDERS, f"{len(orders)} working order(s) already exist")

        self._to(CANDIDATE_VALIDATED, "candidate passed every intake requirement",
                 {"engine_inventory": inventory,
                  "engines_empty_but_present": sorted(empty),
                  "provenance": prov})
        return {"inventory": inventory, "empty": sorted(empty), "provenance": prov}

    # ── 3. risk ───────────────────────────────────────────────────────────────
    def approve_risk(self, candidate: dict) -> BracketGeometry:
        try:
            geo = build_bracket(
                direction=str(candidate.get("direction")).lower(),
                entry_price=float(candidate["entry_price"]),
                invalidation_level=candidate.get("invalidation_level"),
                target_price=candidate.get("target_price"),
                contract=self.contract, size=SMOKE_MAX_CONTRACTS)
        except RiskRejection as exc:
            self._halt(RISK_REJECTED, str(exc), {"reason": exc.reason})
        self.geometry = self._stamp_governing_caps(geo)
        self._to(RISK_APPROVED, f"one contract, ${geo.risk_usd:,.2f} risk",
                 self.geometry.evidence())
        return self.geometry

    def revalidate_before_submit(self, candidate_snapshot, **market) -> dict:
        """Full freshness gate. A stale candidate is DESTROYED, never repaired.

        This is the no-stale-bracket law in code: the only outcomes are "still
        the same trade" or "there is no trade". There is deliberately no branch
        that adjusts a price to rescue a candidate, because rescuing it would
        mean submitting a bracket for a market that no longer exists.
        """
        from broker.topstepx_candidate_freshness import CandidateStale, assess
        try:
            verdict = assess(candidate_snapshot, **market)
        except CandidateStale as exc:
            self.geometry = None                 # destroy the bracket
            self.token = None                    # the authorization dies with it
            self._halt(STALE_CANDIDATE, str(exc), {"stale_reason": exc.reason})
        self._to(CANDIDATE_VALIDATED, "candidate still fresh at submit time", verdict)
        return verdict

    def recheck_risk_at_submit(self, latest_price: float) -> BracketGeometry:
        """Re-derive risk from the FRESHEST price, moments before submitting.

        Price moves between qualification and submit. The stop stays where the
        Brain put it, so drift toward the stop shrinks the distance and drift
        away widens it — and a wider distance means more dollars at risk than
        the trade was approved for. Re-deriving here is the difference between
        approving a plan and approving what will actually happen.

        NOTE this recomputes RISK only. It is not a freshness check and must not
        be mistaken for one — `revalidate_before_submit` decides whether the
        thesis still exists, and must run first.
        """
        if self.geometry is None:
            self._halt(RISK_REJECTED, "risk was never approved")
        try:
            # PRESERVE the approved size and caps. Rebuilding with build_bracket's
            # defaults would silently re-impose the SMOKE limits ($20, 10 points,
            # 1 contract) at the final gate, shrinking an approved production
            # bracket to one contract and rejecting any stop wider than 10 points.
            geo = build_bracket(
                direction=self.geometry.direction, entry_price=float(latest_price),
                invalidation_level=self.geometry.stop_price,
                target_price=self.geometry.target_price,
                contract=self.contract, size=self.geometry.size,
                max_risk_usd=self.max_risk_usd,
                max_stop_points=self.max_stop_points,
                min_reward_to_risk=self.min_reward_to_risk,
                max_contracts=self.max_contracts)
        except RiskRejection as exc:
            self._halt(RISK_REJECTED, f"risk recheck at submit failed: {exc}",
                       {"reason": exc.reason, "latest_price": latest_price})
        self.geometry = self._stamp_governing_caps(geo)
        self._to(RISK_APPROVED, f"risk re-verified at {latest_price}: ${geo.risk_usd:,.2f}",
                 geo.evidence())
        return geo

    # ── 4. submission ─────────────────────────────────────────────────────────
    # ── the gated submit path ─────────────────────────────────────────────────
    def reconcile_ledger(self, ledger, *, trades=None, orders=None,
                         positions=None) -> dict:
        """Attribute all observed activity before letting a candidate near submit.

        Runs BEFORE approval and again in the atomic pre-submit block, because
        the account can change in between — which is exactly what happened on
        2026-08-05 when the operator traded mid-session.
        """
        for row in (positions if positions is not None else self.session.open_positions()):
            ledger.record("position", row)
        for row in (orders if orders is not None else self.working_orders()):
            ledger.record("order", row)
        if trades:
            ledger.reconcile_trades(trades)

        pause = ledger.requires_pause()
        if pause:
            self._halt(EXTERNAL_ACTIVITY_UNRESOLVED, pause, {"ledger": ledger.summary()})
        return ledger.summary()

    def gated_submit(self, *, account_id: int, ledger, candidate_snapshot,
                     market: dict, latest_price: float, mint_token,
                     refresh: Callable[[], dict] = None,
                     on_attempt_consumed: Callable[[str], None] = None,
                     quote_provider: Callable[[], object] = None) -> dict:
        """The ONLY sanctioned route to an order. Enforces the full sequence.

            ledger -> external check -> freshness -> objective -> invalidation
            -> risk/RR -> mint -> token binding -> burn -> atomic recheck -> send

        `mint_token` is a callable so the token is created HERE — after every
        gate has passed — rather than when Luna first spoke. A token minted at
        thesis time would already be authorizing a market that has moved.

        `refresh` returns the freshest {market, latest_price, ledger_rows} for
        the final atomic recheck. Nothing between that recheck and the request
        may yield, so no other candidate or manual event can slip in unnoticed.
        """
        from broker.topstepx_candidate_freshness import CandidateStale

        if self._entry_attempted:
            self._halt(RESIDUAL_ORDERS, "an entry was already attempted; refusing a second")

        # 1-3. ledger + external activity
        self.reconcile_ledger(ledger)

        # 4-6. freshness / objective / invalidation (raises with a precise state)
        self._assess_freshness(candidate_snapshot, market)

        # 7. risk + reward recheck at the freshest price
        self.recheck_risk_at_submit(latest_price)

        # 8. mint the short-lived token only now
        self.token = mint_token()
        ledger.record_token(self.token.token_id)
        self._to(AUTHORIZED, "token minted after all gates passed",
                 {"token": self.token.describe()})

        # 9. FINAL ATOMIC RECHECK — no awaits, no yields, no I/O gaps after this
        if refresh is not None:
            fresh = refresh()
            self.reconcile_ledger(
                ledger, orders=fresh.get("orders"), positions=fresh.get("positions"))
            self._assess_freshness(candidate_snapshot, fresh.get("market") or market)
            self.recheck_risk_at_submit(fresh.get("latest_price", latest_price))
            if fresh.get("positions"):
                self._invalidate("account is no longer flat")
                self._halt(ACCOUNT_STATE_CHANGED, "positions appeared before submit")
            if fresh.get("orders"):
                self._invalidate("working orders appeared")
                self._halt(ACCOUNT_STATE_CHANGED, "working orders appeared before submit")

        # 9b. CAPTURE THE EXECUTABLE QUOTE - as late as safely possible: after
        # every gate, before the attempt is persisted. Capturing at thesis
        # time, candidate construction or token mint would record a price that
        # was executable minutes ago, which measures nothing useful.
        #
        # NON-BLOCKING: reads in-memory hub state only. A failure is recorded
        # and execution continues - evidence collection must never leave an
        # authorized position unprotected. Missing evidence only makes the
        # observation unreliable later.
        self.entry_capture = None
        if quote_provider is not None:
            try:
                self.entry_capture = quote_provider()
            except Exception as exc:  # noqa: BLE001
                self.capture_failure = f"{type(exc).__name__}"

        # 10. DURABLE ATTEMPT CONSUMPTION — persisted and verified BEFORE the
        # request can leave. A crash after this point costs the authorization;
        # a crash without it would hand back a second attempt, which is worse.
        if on_attempt_consumed is not None:
            on_attempt_consumed(self.token.token_id)

        # 11-12. token binding + burn happen inside submit(), atomically
        from broker.topstepx_session_ledger import bot_tag
        result = self.submit(account_id=account_id, custom_tag=bot_tag(self.token.token_id),
                             candidate_snapshot=candidate_snapshot)

        # 13. EXEC-PRICE-ANCHOR-1 — the PROMPT post-fill lifecycle.
        #
        # The submit transaction ORCHESTRATES; it does not become the owner of
        # structural logic. Everything decided below -- what the authoritative
        # fill is, whether the original thesis still clears its caps at that
        # fill, which exact child orders are ours, what price they must hold,
        # and whether to flatten -- belongs to the runner methods it calls.
        #
        # An entry is not "established" at ACK. Until this returns, the venue is
        # holding a stop and target derived from TICK OFFSETS applied to the
        # fill, which after any slippage are prices the thesis never authorized.
        if self.prompt_fill_authority:
            self.protection_outcome = self.establish_structural_protection(
                deadline_seconds=self.fill_deadline_seconds)
            if not self.protection_outcome.get("established"):
                self._halt(PROTECTION_MISSING,
                           f"structural protection not established after fill: "
                           f"{self.protection_outcome.get('reason')}",
                           {"protection": self.protection_outcome})
            result = {**(result or {}), "protection": self.protection_outcome}
        return result

    def _assess_freshness(self, candidate_snapshot, market: dict) -> dict:
        from broker.topstepx_candidate_freshness import CandidateStale, assess
        try:
            return assess(candidate_snapshot, **market)
        except CandidateStale as exc:
            state = _STALE_REASON_STATE.get(exc.reason, CANDIDATE_STALE)
            self._invalidate(f"stale: {exc.reason}")
            self._halt(state, str(exc), {"stale_reason": exc.reason})

    def _invalidate(self, why: str) -> None:
        """Destroy the bracket and any UNBURNED token. Never repair either."""
        self.geometry = None
        if self.token is not None and not self.token.spent:
            self.token = None
        self._to(WAITING_FOR_CANDIDATE, f"candidate invalidated ({why}); bracket destroyed")

    def submit(self, *, account_id: int, custom_tag: str = None,
               candidate_snapshot=None) -> dict:
        if self._entry_attempted:
            self._halt(RESIDUAL_ORDERS, "an entry was already attempted; refusing a second")
        if self.geometry is None:
            self._halt(RISK_REJECTED, "no approved geometry")

        # Burn BEFORE the request leaves. Whatever happens next — accepted,
        # rejected, timed out, crashed — this authorization is spent.
        # Token validation carries the WHOLE thesis, not just size and account.
        # A one-tick change to the stop, or the same target price under a
        # different objective identity, is a different decision.
        cs = candidate_snapshot
        try:
            burn = smoke_auth.authorize_submission(
                self.token, account_fingerprint=self.account_fingerprint,
                contract_id=self.contract.id, size=self.geometry.size,
                risk_usd=self.geometry.risk_usd,
                stop_points=self.geometry.stop_points,
                candidate_fingerprint=(cs.fingerprint() if cs is not None else None),
                snapshot_id=(cs.snapshot_id if cs is not None else None),
                direction=self.geometry.direction,
                stop_price=self.geometry.stop_price,
                target_price=self.geometry.target_price,
                target_identity=(cs.objective.identity if cs is not None else None),
                now=self.clock())
        except smoke_auth.AuthorizationError as exc:
            # The token was NOT burned — invalidate rather than spend it.
            self._invalidate("token binding mismatch")
            self._halt(TOKEN_BINDING_MISMATCH, str(exc))

        self._entry_attempted = True
        payload = self.geometry.as_order_payload(account_id, self.contract.id, custom_tag)
        self._to(SUBMITTING, "one MNQ market entry with attached bracket",
                 {"token_burn": burn, "request_digest": _digest(payload)})

        # PROD-20260810: the flight recorder. Order 3385801549 was rejected by
        # Topstep and the reason existed only inside the exception below, in
        # memory, on a process that was later stopped. The payload goes to disk
        # BEFORE the socket opens, and whatever the venue says goes to disk the
        # instant it arrives -- ahead of any parsing that could discard it.
        self.submission_custom_tag = custom_tag or ""
        self._open_submission_record(payload, custom_tag)

        started = self.clock()
        self.submit_at = started
        try:
            result = self.session.place_order(payload)
        except TopstepXError as exc:
            # A recording failure here does not change what must happen next --
            # reconcile against the venue either way -- but it is carried into
            # the halt so it can never read as an ordinary refusal.
            self._record_submission_outcome(
                raw_response=self._venue_body(exc), transport_exception=str(exc))
            return self._reconcile_uncertain(f"venue error: {exc}")
        except Exception as exc:  # noqa: BLE001 — timeouts land here
            self._record_submission_outcome(
                raw_response=self._venue_body(exc),
                transport_exception=f"{type(exc).__name__}: {exc}")
            return self._reconcile_uncertain(f"{type(exc).__name__}: {exc}")
        if not self._record_submission_outcome(raw_response=self._venue_body(result)):
            # The order may be live. Find out from the venue, then halt.
            return self._reconcile_after_recording_failure()

        latency = (self.clock() - started).total_seconds()
        self.ack_at = self.clock()
        if latency > ACK_DEADLINE_SECONDS:
            self._to(ACK_TIMEOUT, f"acknowledgment took {latency:.1f}s")
        if not result or not result.get("order_id"):
            self._halt(SUBMIT_REJECTED, f"venue returned no order id: {result}")
        self.order_id = result["order_id"]
        # MISSION-LIFECYCLE (2026-08-11). The symmetric partner to
        # `on_attempt_consumed`, and the hop that did not exist on V13: the
        # venue's order id reached the flight recorder and never reached the
        # mission, because MissionState had no method that could write it on a
        # SUCCESSFUL path. Order 3391019204 filled and stopped out while its
        # mission still read ATTEMPT_CONSUMED / order_id=null.
        #
        # Durable BEFORE the ack is reported upward, exactly as consumption is
        # durable before the request leaves. A failure here is not recoverable
        # by retrying -- the order is LIVE and unrecorded -- so it halts under
        # the existing recording-failure state rather than returning.
        if self.on_venue_acknowledged is not None:
            try:
                self.on_venue_acknowledged(self.order_id)
            except Exception as exc:  # noqa: BLE001 — fail closed, never retry
                self.recording_failure = {
                    "stage": "mission_acknowledgement",
                    "order_id": self.order_id,
                    "error": f"{type(exc).__name__}: {exc}"}
                self._emergency_recording_marker()
                self._halt(SUBMISSION_RECORD_WRITE_FAILED,
                           f"venue acknowledged order {self.order_id} but the "
                           f"mission could not record it: {type(exc).__name__}: {exc}",
                           dict(self.recording_failure))
        self._to(ACKNOWLEDGED, f"order {self.order_id} acknowledged in {latency:.2f}s",
                 {"order_id": self.order_id, "ack_latency_seconds": round(latency, 3)})
        return result

    # ── the flight recorder ───────────────────────────────────────────────────
    #
    # All three helpers are no-ops unless `submission_store_dir` is configured,
    # so the smoke tools and the existing tests keep working untouched. When it
    # IS configured, the pre-transport write is NOT best-effort: a runner that
    # cannot record what it is about to send does not send it.
    def _recording(self) -> bool:
        return bool(getattr(self, "submission_store_dir", None)
                    and getattr(self, "submission_session_id", None))

    def _open_submission_record(self, payload: dict, custom_tag: str) -> None:
        if not self._recording():
            return
        self.submission_record = SUBREC.open_submission(
            store_dir=self.submission_store_dir,
            session_id=self.submission_session_id,
            mission_id=getattr(self, "submission_mission_id", "") or "",
            payload=payload, custom_tag=custom_tag or "",
            token_id=getattr(getattr(self, "token", None), "token_id", "") or "",
            authorization_fingerprint=getattr(
                self, "submission_authorization_fingerprint", "") or "",
            account_fingerprint=getattr(self, "account_fingerprint", "") or "",
            contract_id=self.contract.id,
            symbol=getattr(self.contract, "name", "") or "",
            geometry=(self.geometry.evidence() if self.geometry else {}))

    @staticmethod
    def _venue_body(obj) -> dict:
        """The venue's own dict, wherever it is hiding.

        A success carries `raw`; a `TopstepXError` may carry the body on the
        exception. Anything unrecognised yields {} rather than a guess -- an
        invented body would be worse than an absent one.
        """
        for candidate in (getattr(obj, "venue_body", None),
                          getattr(obj, "raw", None),
                          obj.get("raw") if isinstance(obj, dict) else None,
                          obj if isinstance(obj, dict) else None):
            if isinstance(candidate, dict) and candidate:
                return candidate
        return {}

    def _record_submission_outcome(self, *, raw_response: dict = None,
                                   transport_exception: str = None,
                                   state: str = None,
                                   reconciliation: dict = None) -> bool:
        """Persist the venue's answer. Returns False if it could not be written.

        This used to `except Exception: pass`, which quietly reintroduced the
        exact PROD-20260810 failure one layer down: the venue answers, the
        write fails, the answer dies in memory anyway. Recording failure is now
        a first-class condition.

        It still must not MASK the venue. The answer is kept in memory, the
        caller reconciles against the venue, and only then does the session
        halt -- broker reality is handled first, evidence failure second, and
        neither is hidden.
        """
        if not self._recording() or not getattr(self, "submission_record", None):
            return True
        try:
            self.submission_record = SUBREC.record_response(
                store_dir=self.submission_store_dir,
                session_id=self.submission_session_id,
                submission=self.submission_record, raw_response=raw_response,
                transport_exception=transport_exception, state=state,
                reconciliation=reconciliation)
            return True
        except Exception as exc:  # noqa: BLE001
            body = dict(raw_response or {})
            self.recording_failure = {
                "error": f"{type(exc).__name__}: {exc}",
                "submission_id": (self.submission_record or {}).get("submission_id"),
                "venue_order_id": body.get("orderId", body.get("order_id")),
                "success": body.get("success"),
                "error_code": body.get("errorCode"),
                "error_message": body.get("errorMessage"),
                "raw_response": body or None,
                "transport_exception": transport_exception,
                "note": ("the venue answered but the answer could not be "
                         "persisted; it is preserved here in memory and in "
                         "the runner transitions"),
            }
            self._to(SUBMISSION_RECORD_WRITE_FAILED,
                     f"could not persist the venue response: {exc}",
                     dict(self.recording_failure))
            self._emergency_recording_marker()
            return False

    def _emergency_recording_marker(self) -> None:
        """Last-ditch attempt to leave a trace somewhere else. Never raises.

        The primary ledger write already failed, so this is not relied upon --
        it is a second chance, not the guarantee. The guarantee is the halt.
        """
        try:
            path = os.path.join(self.submission_store_dir,
                                f"RECORDING_FAILURE_{self.submission_session_id}.jsonl")
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"at": self.clock().isoformat(),
                                     "mission_id": self.submission_mission_id,
                                     **self.recording_failure}, default=str) + "\n")
        except Exception:  # noqa: BLE001
            pass

    def _reconcile_after_recording_failure(self):
        """Ask the venue what is true, then halt. Never resubmit.

        Called when the venue answered but the answer could not be stored. The
        position (if any) is surfaced, not hidden behind the recorder error.
        """
        try:
            positions = self.session.open_positions()
            orders = self.working_orders()
        except Exception as exc:  # noqa: BLE001
            self._halt(SUBMISSION_RECORD_WRITE_FAILED,
                       f"the venue response could not be persisted AND the venue "
                       f"could not be re-queried ({exc}). Operator intervention "
                       f"required; NOT resubmitting.",
                       dict(self.recording_failure or {}))
        evidence = {"open_positions": len(positions), "open_orders": len(orders),
                    "positions": positions, "orders": orders,
                    **(self.recording_failure or {})}
        self._to(SUBMIT_UNKNOWN,
                 "reconciling after a recording failure; the venue is the authority",
                 evidence)
        self._halt(SUBMISSION_RECORD_WRITE_FAILED,
                   f"the venue answered but the response could not be persisted. "
                   f"Venue now reports {len(positions)} position(s) and "
                   f"{len(orders)} working order(s). The session is HALTED for "
                   f"operator review; NOT resubmitting.", evidence)

    def _reconcile_uncertain(self, why: str) -> dict:
        """UNKNOWN after submit. Ask the venue; never resubmit."""
        self._to(SUBMIT_UNKNOWN, f"submission outcome unknown ({why}); reconciling")
        try:
            orders = self.working_orders()
            positions = self.session.open_positions()
        except TopstepXError as exc:
            self._halt(SUBMIT_UNKNOWN,
                       f"cannot reconcile after an uncertain submit: {exc}. "
                       f"NOT resubmitting; operator intervention required.")
        evidence = {"open_orders": len(orders), "open_positions": len(positions)}
        if positions:
            self._to(FILLED, "reconciliation found a position; the order did exist", evidence)
            return {"order_id": None, "reconciled": True, "position": positions[0]}
        if orders:
            self._to(ACKNOWLEDGED, "reconciliation found a working order", evidence)
            return {"order_id": orders[0].get("id"), "reconciled": True}
        self._halt(SUBMIT_REJECTED,
                   "reconciliation found neither position nor order; the entry did not land. "
                   "The authorization is spent — a new operator phrase is required.", evidence)

    # ── 5. fill + protection ──────────────────────────────────────────────────
    def confirm_fill(self, fill_event: dict) -> dict:
        if not fill_event:
            self._halt(FILL_TIMEOUT, "no fill event observed within the deadline")
        size = int(fill_event.get("size") or 0)
        if size != SMOKE_MAX_CONTRACTS:
            self._halt(PROTECTION_MISSING, f"filled {size} contracts, expected {SMOKE_MAX_CONTRACTS}")
        if fill_event.get("contract_id") != self.contract.id:
            self._halt(CONTRACT_MISMATCH, "fill is on a different contract")
        self._to(FILLED, f"filled {size} @ {fill_event.get('price')}",
                 {"fill": fill_event,
                  "reference_drift": _slippage(self.geometry, fill_event.get("price"))})
        self._to(PROTECTION_PENDING, "awaiting both protective orders")
        return fill_event

    def measure_entry_slippage(self, *, fill_event, candidate_snapshot=None,
                               ledger=None, attribution="EXPANSION_BOT", fills=None):
        """Entry observation from the captured quote. Raw, persisted, never P&L.

        Partial fills collapse to a quantity-weighted average first, so ONE order
        yields ONE observation - counting each row would inflate the sample and
        manufacture round trips that never happened.
        """
        from broker import topstepx_slippage as SL
        if self.entry_capture is None:
            return None
        agg = SL.aggregate_fills(fills) if fills else None
        price = agg["vwap"] if (agg and agg["vwap"] is not None) else fill_event.get("price")
        qty = agg["quantity"] if agg else int(fill_event.get("size") or 0)
        cs = candidate_snapshot
        obs = SL.measure_entry(
            capture=self.entry_capture,
            direction=("buy" if self.geometry.direction == "bullish" else "sell"),
            fill_price=price, quantity=qty,
            tick_size=self.contract.tick_size, tick_value=self.contract.tick_value,
            contract_id=self.contract.id, request_at=self.submit_at,
            ack_at=self.ack_at, fill_at=fill_event.get("at"),
            fill_order_id=(agg or {}).get("order_id") or self.order_id,
            expected_order_id=self.order_id, attribution=attribution,
            candidate_id=(cs.candidate_id if cs is not None else ""),
            snapshot_id=(cs.snapshot_id if cs is not None else ""),
            account_fingerprint=self.account_fingerprint,
            trade_id=fill_event.get("trade_id"))
        _attach_partials(obs, agg, SL)
        if ledger is not None:
            ledger.record(obs)
        return obs

    def measure_exit_slippage(self, *, exit_type, fill_price, quantity, quote_capture,
                              requested_price=None, candidate_snapshot=None,
                              ledger=None, attribution="EXPANSION_BOT", order_id=None,
                              trade_id=None, fills=None, request_at=None, fill_at=None):
        """Exit observation. Requested price by exit type - never the trade's move."""
        from broker import topstepx_slippage as SL
        if quote_capture is None:
            return None
        agg = SL.aggregate_fills(fills) if fills else None
        price = agg["vwap"] if (agg and agg["vwap"] is not None) else fill_price
        qty = agg["quantity"] if agg else int(quantity or 0)
        cs = candidate_snapshot
        obs = SL.measure_exit(
            capture=quote_capture,
            direction=("buy" if self.geometry.direction == "bullish" else "sell"),
            exit_type=exit_type, requested_price=requested_price, fill_price=price,
            quantity=qty, tick_size=self.contract.tick_size,
            tick_value=self.contract.tick_value, contract_id=self.contract.id,
            request_at=request_at, fill_at=fill_at,
            order_id=(agg or {}).get("order_id") or order_id, trade_id=trade_id,
            attribution=attribution,
            candidate_id=(cs.candidate_id if cs is not None else ""),
            snapshot_id=(cs.snapshot_id if cs is not None else ""),
            account_fingerprint=self.account_fingerprint)
        _attach_partials(obs, agg, SL)
        if ledger is not None:
            ledger.record(obs)
        return obs

    def build_execution_context(self, *, candidate_snapshot, mission_id, fill_event,
                                stop_order_id=None, target_order_id=None, path=""):
        """Persist what the exit needs. Identity is threaded, never inferred later."""
        from broker import topstepx_slippage as SL
        cs = candidate_snapshot
        ctx = SL.ExecutionContext(
            candidate_id=cs.candidate_id, candidate_fingerprint=cs.fingerprint(),
            snapshot_id=cs.snapshot_id, mission_id=mission_id,
            account_fingerprint=self.account_fingerprint,
            contract_id=self.contract.id, direction=self.geometry.direction,
            quantity=self.geometry.size, entry_order_id=self.order_id,
            entry_trade_id=fill_event.get("trade_id"),
            entry_fill_price=fill_event.get("price"),
            structural_stop_price=self.geometry.stop_price,
            liquidity_target_price=self.geometry.target_price,
            stop_order_id=stop_order_id, target_order_id=target_order_id,
            entry_capture=(self.entry_capture.evidence(self.contract.tick_size)
                           if self.entry_capture else None),
            path=path)
        if path:
            ctx.save()
        self.execution_context = ctx
        return ctx

    # ── EXEC-PRICE-ANCHOR-1 — absolute structural prices survive the fill ─────
    #
    # Measured live on 2026-08-18 (PRAC execution smoke, BRACKETLESS=0): the
    # venue applies `stopLossBracket`/`takeProfitBracket` TICKS to the ACTUAL
    # FILL. A reference entry of 29591.25 with an intended stop of 29581.25
    # filled at 29574.25 and left the stop working at 29564.25 -- exactly 40
    # ticks below the fill, and ten points below the price the thesis named.
    #
    # `build_bracket` promises the invalidation "becomes the stop unmodified".
    # That promise held through approval and was then undone at the transport
    # boundary, because only a DISTANCE reaches the venue. Dollar risk survives
    # (the distance is preserved) but MARKET TRUTH does not: the stop lands on
    # a level no structural analysis ever authorized, and can sit through the
    # very swing that justified the trade.
    #
    # So the attached brackets are demoted to what they actually are -- PROVISIONAL
    # transport protection that keeps a market fill from being bare -- and the
    # authorized absolute prices are restored once the fill is known.

    def _aligned_structural_prices(self, fill_price: float) -> dict:
        """Snap the AUTHORIZED absolutes to the tick grid. The PRICE is the anchor.

        The grid snap is applied to the AUTHORIZED LEVEL ITSELF, not reconstructed
        from a tick distance off the fill. That distinction is the whole defect:
        a multi-fill VWAP such as 30000.5833 is not on the 0.25 grid, so
        `fill + ticks*tick` lands at 29979.8333 -- near the authorized 29980.00,
        but not ON it. Rebuilding a price from a distance is exactly how the
        absolute level gets lost, which is what EXEC-PRICE-ANCHOR-1 is about.
        An on-grid authorized level therefore survives EXACTLY, whatever the fill.

        The certified conservative convention is preserved in the snap direction:
        the stop moves AWAY from the fill (never comes to rest inside the
        structural level) and the target moves TOWARD it (reward never
        overstated). Economics are still measured in whole ticks from the fill.
        """
        import math
        geo, tick = self.geometry, self.contract.tick_size
        bullish = geo.direction == "bullish"
        # stop is below a long / above a short -> away = down / up
        stop_price = (math.floor(geo.stop_price / tick) if bullish
                      else math.ceil(geo.stop_price / tick)) * tick
        # target is above a long / below a short -> toward = down / up
        target_price = (math.floor(geo.target_price / tick) if bullish
                        else math.ceil(geo.target_price / tick)) * tick
        return {
            "stop_price": round(stop_price, 10),
            "target_price": round(target_price, 10),
            "stop_ticks": ticks_between(fill_price, geo.stop_price, self.contract,
                                        round_away=True),
            "target_ticks": ticks_between(fill_price, geo.target_price, self.contract,
                                          round_away=False),
        }

    def authorize_actual_fill(self, fill_event: dict) -> dict:
        """Re-authorize the ORIGINAL absolute thesis against the ACTUAL fill.

        Restoring absolute prices is exactly what makes risk stop being
        invariant: holding the stop still while the fill moves changes the
        distance, and therefore the money. Approving a plan at
        `candidate.entry_price` is not approving what actually happened, so the
        production caps are re-applied here against the real fill.

        Returns the post-fill economics. Never repairs: a thesis that no longer
        clears its own gates is refused, not resized or relocated.
        """
        geo = self.geometry
        if geo is None:
            return {"authorized": False, "reason": "no_geometry",
                    "detail": "risk was never approved"}
        try:
            fill_price = float((fill_event or {}).get("price"))
        except (TypeError, ValueError):
            return {"authorized": False, "reason": "unusable_fill_price",
                    "detail": f"fill price {(fill_event or {}).get('price')!r} is not numeric"}
        if not math.isfinite(fill_price) or fill_price <= 0:
            return {"authorized": False, "reason": "unusable_fill_price",
                    "detail": f"fill price {fill_price!r} is not a usable price"}

        size = int((fill_event or {}).get("size") or 0)
        if size < 1:
            return {"authorized": False, "reason": "unusable_fill_quantity",
                    "detail": f"filled quantity {size!r}"}
        if size > int(self.max_contracts):
            return {"authorized": False, "reason": "quantity_above_cap",
                    "detail": f"filled {size} exceeds the {self.max_contracts}-contract cap"}

        bullish = geo.direction == "bullish"
        # Side is judged against the ACTUAL fill, never `candidate.entry_price`.
        if bullish and geo.stop_price >= fill_price:
            return {"authorized": False, "reason": "fill_crossed_structural_stop",
                    "detail": f"stop {geo.stop_price} is at/above the fill {fill_price}",
                    "fill_price": fill_price}
        if not bullish and geo.stop_price <= fill_price:
            return {"authorized": False, "reason": "fill_crossed_structural_stop",
                    "detail": f"stop {geo.stop_price} is at/below the fill {fill_price}",
                    "fill_price": fill_price}
        if bullish and geo.target_price <= fill_price:
            return {"authorized": False, "reason": "fill_crossed_objective",
                    "detail": f"objective {geo.target_price} is at/below the fill {fill_price}",
                    "fill_price": fill_price}
        if not bullish and geo.target_price >= fill_price:
            return {"authorized": False, "reason": "fill_crossed_objective",
                    "detail": f"objective {geo.target_price} is at/above the fill {fill_price}",
                    "fill_price": fill_price}

        aligned = self._aligned_structural_prices(fill_price)
        stop_ticks, target_ticks = aligned["stop_ticks"], aligned["target_ticks"]
        if stop_ticks <= 0:
            return {"authorized": False, "reason": "zero_distance_stop",
                    "detail": "the authorized invalidation is less than one tick from the fill",
                    "fill_price": fill_price}

        risk = risk_for(stop_ticks, size, self.contract)
        reward = risk_for(target_ticks, size, self.contract)
        stop_points = stop_ticks * self.contract.tick_size
        out = {
            "fill_price": fill_price, "size": size,
            "authorized_stop_price": geo.stop_price,
            "authorized_target_price": geo.target_price,
            "aligned_stop_price": aligned["stop_price"],
            "aligned_target_price": aligned["target_price"],
            "stop_points": round(stop_points, 6),
            "reward_points": round(target_ticks * self.contract.tick_size, 6),
            "risk_usd": risk, "reward_usd": reward,
            "reward_to_risk": round(reward / risk, 3) if risk else None,
            "max_stop_points": float(self.max_stop_points),
            "max_risk_usd": float(self.max_risk_usd),
            "min_reward_to_risk": float(self.min_reward_to_risk),
        }
        if stop_points > float(self.max_stop_points):
            return {**out, "authorized": False, "reason": "stop_distance_above_cap",
                    "detail": (f"actual-fill stop distance {stop_points:g} points exceeds the "
                               f"{float(self.max_stop_points):g}-point ceiling. The invalidation "
                               f"is the Brain's and is not adjustable.")}
        if risk > float(self.max_risk_usd):
            return {**out, "authorized": False, "reason": "risk_above_cap",
                    "detail": (f"actual-fill risk ${risk:,.2f} exceeds the "
                               f"${float(self.max_risk_usd):,.2f} cap")}
        if risk > 0 and (reward / risk) < float(self.min_reward_to_risk):
            return {**out, "authorized": False, "reason": "reward_below_gate",
                    "detail": (f"actual-fill reward-to-risk {reward / risk:.2f} is below the "
                               f"{float(self.min_reward_to_risk):.2f} gate")}
        return {**out, "authorized": True, "reason": None, "detail": ""}

    def protective_children(self, working_orders: list) -> dict:
        """The exact stop and target children of THIS entry, or ambiguity.

        Ownership is `mission_owns_order` lineage -- parent/linked order ids and
        the mission tag -- never "nearest price" or "newest order on the
        contract". An order we cannot prove is ours is never modified.
        """
        # DISCOVERED + OWNED IS STILL NOT PROTECTING. A terminal child is ours
        # and visible and can protect nothing, so lifecycle is filtered before
        # the stop/target census -- otherwise a filled stop and its replacement
        # would present as two owned stops and read as ambiguous ownership.
        rows = [o for o in DISC.working_orders(working_orders)
                if self.mission_owns_order(o)]
        stops = [o for o in rows if int(o.get("type") or 0) == 4]
        targets = [o for o in rows if int(o.get("type") or 0) == 1]
        problem = None
        if len(stops) != 1 or len(targets) != 1:
            problem = (f"child ownership unproven: {len(stops)} stop(s), "
                       f"{len(targets)} target(s) provably belong to entry "
                       f"{self.order_id}")
        return {"stop": stops[0] if len(stops) == 1 else None,
                "target": targets[0] if len(targets) == 1 else None,
                "ambiguous": problem is not None, "detail": problem}

    def acquire_full_fill(self, *, deadline_seconds: float = FILL_DEADLINE_SECONDS,
                          sleep=None) -> dict:
        """The AUTHORITATIVE fill for this entry: full quantity, weighted average.

        `first fill != authoritative fill`. Production sizes up to fifteen
        micros and one parent order can fill across several executions, so a
        re-anchor computed from the first trade event would authorize the trade
        against a price that was never paid. Only fills whose `orderId` is THIS
        parent are counted, and the average is volume-weighted.

        Bounded, and it never resubmits: the order has already left, so waiting
        for authoritative state is reconciliation, not a second attempt.
        """
        import time
        sleep = sleep or time.sleep
        want = int(self.geometry.size) if self.geometry else 0
        # A DEADLINE IS WALL-CLOCK, not the injected business clock. `self.clock`
        # exists so a caller can pin decision time -- the production harness
        # passes `lambda: NOW` -- and a frozen clock makes a bounded wait
        # UNBOUNDED: elapsed stays 0 and the poll loop never exits. Timeouts and
        # decision timestamps are different quantities and need different sources.
        elapsed = getattr(self, "_elapsed", None) or time.monotonic
        started = elapsed()
        seen, last = [], {}
        while (elapsed() - started) < float(deadline_seconds):
            try:
                trades = self.session.recent_trades()
            except Exception as exc:  # noqa: BLE001 — an unreadable venue is not a fill
                last = {"error": f"{type(exc).__name__}: {str(exc)[:120]}"}
                trades = []
            seen = [t for t in (trades or [])
                    if str(t.get("orderId")) == str(self.order_id)]
            filled = sum(int(t.get("size") or 0) for t in seen)
            # Spread FIRST, then the fresh values -- the other order lets a stale
            # reading overwrite the current one, which mislabels a partial fill
            # at the deadline as "no fill observed".
            last = {**last, "fill_count": len(seen), "filled_quantity": filled,
                    "requested_quantity": want}
            if filled == want and want > 0:
                notional = sum(float(t.get("price") or 0) * int(t.get("size") or 0)
                               for t in seen)
                vwap = notional / filled
                # Cross-check against the venue's own position before trusting it.
                try:
                    positions = self.session.open_positions()
                except Exception as exc:  # noqa: BLE001
                    return {"complete": False, "reason": "position_unreadable",
                            "detail": f"{type(exc).__name__}", **last}
                pos_qty = sum(abs(int(p.get("size") or 0)) for p in (positions or [])
                              if str(p.get("contract_id")
                                     or p.get("contractId") or "") == str(self.contract.id))
                if pos_qty != filled:
                    return {"complete": False, "reason": "position_quantity_disagrees",
                            "detail": f"attributed fills {filled}, venue position {pos_qty}",
                            "position_quantity": pos_qty, **last}
                return {"complete": True, "reason": None, "fill_price": vwap,
                        "size": filled, "fill_count": len(seen),
                        "requested_quantity": want, "position_quantity": pos_qty,
                        "trade_ids": [t.get("id") for t in seen]}
            if filled > want:
                return {"complete": False, "reason": "overfill",
                        "detail": f"attributed {filled} against a request of {want}", **last}
            sleep(0.5)
        return {"complete": False,
                "reason": "partial_fill_at_deadline" if last.get("filled_quantity")
                else "no_fill_observed",
                "detail": f"{last.get('filled_quantity', 0)}/{want} filled within "
                          f"{deadline_seconds:g}s", **last}

    def _prove_leg(self, *, name: str, order_id, wanted: float, size: int,
                   is_stop: bool) -> dict:
        """Read the venue back and prove THIS EXACT child sits on `wanted`.

        A 2xx from `/api/Order/modify` is a claim. The readback is the proof, and
        it is bound to the child id `protective_children` already established --
        never re-discovered as "the first stop on this contract", which would
        happily approve an operator's own order.
        """
        try:
            rows = self.working_orders()
        except Exception as exc:  # noqa: BLE001
            return {"proven": False, "reason": f"{name}_readback_unavailable",
                    "detail": f"{type(exc).__name__}: {str(exc)[:120]}"}
        match = [o for o in (rows or []) if str(o.get("id")) == str(order_id)]
        if len(match) != 1:
            return {"proven": False, "reason": f"{name}_child_missing",
                    "detail": f"{len(match)} order(s) with id {order_id} after modify"}
        order = match[0]
        if not self.mission_owns_order(order):
            return {"proven": False, "reason": f"{name}_lineage_lost",
                    "detail": f"order {order_id} no longer proves this mission's lineage"}
        if int(order.get("type") or 0) != (4 if is_stop else 1):
            return {"proven": False, "reason": f"{name}_type_changed",
                    "detail": f"order {order_id} type is {order.get('type')}"}
        qty = order.get("size") if order.get("size") is not None else order.get("quantity")
        if qty is not None and int(qty) != int(size):
            return {"proven": False, "reason": f"{name}_quantity_wrong",
                    "detail": f"{name} quantity {qty} != filled quantity {size}"}
        price = _price_of(order)
        if price is None or abs(price - wanted) > _PRICE_EPSILON:
            return {"proven": False, "reason": f"{name}_price_wrong",
                    "detail": f"{name} working at {price}, authorized structure is {wanted}"}
        return {"proven": True, "order_id": order_id, "price": price}

    def reanchor_protection_to_structure(self, *, fill_event: dict,
                                         working_orders: list) -> dict:
        """Replace provisional fill-relative protection with the authorized levels.

        STOP FIRST AND PROVEN FIRST. Protection authority outranks profit-taking
        authority, so the loss-bounding leg is modified AND read back AND proven
        before the target is touched at all. If the stop modify succeeds but the
        readback is wrong or unavailable, the target is never modified -- the
        position is flattened instead.

        Every failure is terminal. There is no approved bounded-drift doctrine,
        so the outcome is exact structural prices or a flat account.

        PROTECTION-STATE-AUTHORITY-1: this runs exactly ONCE per position. Once
        the management baseline is armed, protection may have advanced, and
        re-anchoring would push the ORIGINAL invalidation back over a stop that
        has already given up risk -- a silent widening on the one code path
        allowed to move a live stop. It refuses instead, and deliberately does
        NOT flatten: a managed position with proven protection is healthy, and
        killing it to resolve our own bookkeeping would be the worse outcome.

        THE ARMED FLAG IS NOT PROOF OF PROTECTION. It lives in a JSON file that
        a restart reads back, and yesterday's JSON cannot answer "what will
        actually exit me now" -- only the venue can. So the flag alone buys a
        refusal to re-anchor, never a claim of establishment: the owned working
        stop must be found and reconciled first. If no owned stop can be proven,
        this reports protection as UNESTABLISHED and lets the existing
        protection-failure policy decide, rather than letting stale local memory
        impersonate a healthy managed position.
        """
        ctx = self.execution_context
        if ctx is not None and ctx.protection_baseline_armed:
            from broker import protection_state as PS
            adoption = self.adopt_venue_protection(working_orders)
            common = {"reanchored": False, "reason": PS.BASELINE_ALREADY_ARMED,
                      "adoption": adoption,
                      "active_protective_stop": ctx.active_protective_stop,
                      "original_thesis_invalidation": ctx.original_thesis_invalidation}
            if adoption.get("outcome") == PS.NO_VENUE_STOP:
                return dict(common, already_established=False,
                            reason="protection_unproven_at_venue",
                            detail="local state is armed but no owned working "
                                   "stop could be proven at the venue "
                                   f"({adoption.get('reason') or 'none found'}); "
                                   "a persisted flag is not protection")
            return dict(common, already_established=True,
                        detail=f"protection is established and working at "
                               f"{ctx.active_protective_stop}; re-anchoring to "
                               f"{ctx.original_thesis_invalidation} would restore risk")
        auth = self.authorize_actual_fill(fill_event)
        if not auth.get("authorized"):
            flat = self.emergency_flatten(
                f"post-fill authorization failed ({auth.get('reason')}): {auth.get('detail')}")
            return {"reanchored": False, "authorization": auth, "flattened": flat}

        children = self.protective_children(working_orders)
        if children["ambiguous"]:
            flat = self.emergency_flatten(children["detail"])
            return {"reanchored": False, "authorization": auth,
                    "reason": "child_ownership_ambiguous", "flattened": flat}

        size = int(auth["size"])
        # The exact ids are carried forward; nothing downstream re-discovers them.
        ids = {"stop": children["stop"].get("id"), "target": children["target"].get("id")}
        legs = (("stop", ids["stop"], auth["aligned_stop_price"], "stop_price", True),
                ("target", ids["target"], auth["aligned_target_price"], "limit_price", False))
        moved, proofs = {}, {}
        for name, order_id, wanted, price_field, is_stop in legs:
            try:
                self.session.modify_order(order_id, **{price_field: wanted})
            except Exception as exc:  # noqa: BLE001 — unknown is treated as failure
                flat = self.emergency_flatten(
                    f"{name} modify to {wanted} failed/uncertain: "
                    f"{type(exc).__name__}: {str(exc)[:160]}")
                return {"reanchored": False, "authorization": auth,
                        "reason": f"{name}_modify_failed", "moved": moved,
                        "child_ids": ids, "flattened": flat}
            proof = self._prove_leg(name=name, order_id=order_id, wanted=wanted,
                                    size=size, is_stop=is_stop)
            proofs[name] = proof
            if not proof["proven"]:
                flat = self.emergency_flatten(
                    f"{name} re-anchor unproven ({proof['reason']}): {proof['detail']}")
                return {"reanchored": False, "authorization": auth, "moved": moved,
                        "reason": proof["reason"], "proofs": proofs,
                        "child_ids": ids, "flattened": flat}
            moved[name] = wanted

        readback = self.verify_protection(self.working_orders(),
                                          fill_price=auth["fill_price"],
                                          authorization=auth)
        if not readback.get("verified"):
            return {"reanchored": False, "authorization": auth, "moved": moved,
                    "reason": "readback_failed", "verification": readback,
                    "proofs": proofs, "child_ids": ids}
        # ONLY HERE. Stop modified, stop readback proven, target proven, whole
        # protection verified. This is the first instant at which a stop exists
        # that is both structural and real, so this is where the monotonic law
        # begins. Arming any earlier would forbid the widening this very method
        # is built to perform.
        baseline = self._arm_protection_baseline(
            thesis_invalidation=auth["authorized_stop_price"],
            proven_stop_price=auth["aligned_stop_price"])
        self._to(PROTECTION_REANCHORED,
                 f"protection restored to the authorized structure "
                 f"(stop {auth['aligned_stop_price']}, target {auth['aligned_target_price']})",
                 {"authorization": auth, "verification": readback,
                  "child_ids": ids, "proofs": proofs, "baseline": baseline})
        return {"reanchored": True, "authorization": auth, "moved": moved,
                "verification": readback, "proofs": proofs, "child_ids": ids,
                "baseline": baseline}

    def _arm_protection_baseline(self, *, thesis_invalidation,
                                 proven_stop_price) -> dict:
        """Record BOTH truths, each from its own authority.

        `thesis_invalidation` is `authorized_stop_price` -- the canonical
        authored structural invalidation, thesis history that the venue does
        not get a vote on. `proven_stop_price` is `aligned_stop_price`, the
        tick-aligned number actually proven working at the venue.

        They can differ by a tick and that difference is preserved. Collapsing
        it would let broker rounding rewrite what the thesis said.
        """
        from broker import protection_state as PS
        ctx = self.execution_context
        if ctx is None:
            return {"schema": PS.SCHEMA, "armed": False,
                    "reason": "no_execution_context",
                    "detail": "protection was proven with no context to record it in"}
        result = PS.arm_baseline(direction=ctx.direction,
                                 thesis_invalidation=thesis_invalidation,
                                 proven_stop_price=proven_stop_price,
                                 already_armed=bool(ctx.protection_baseline_armed))
        if result.get("armed"):
            ctx.original_thesis_invalidation = result["original_thesis_invalidation"]
            ctx.active_protective_stop = result["active_protective_stop"]
            ctx.protection_baseline_armed = True
            ctx.save()
        return result

    def adopt_venue_protection(self, working_orders: list = None) -> dict:
        """Make local protection state agree with what the venue is holding.

        THE CORRECTION ONLY EVER TRAVELS VENUE -> PROCESS. Nothing in here
        modifies an order, so stale local state cannot widen working protection
        on restart; the worst it can do is be wrong about it for one tick, and
        then it is corrected. Believing we are better protected than the venue
        will honour is the failure this method exists to end.

        A stop whose lineage is not provably ours is not a source of truth
        either -- `protective_children` establishes exactly one owned stop or
        none, and none means nothing is adopted.
        """
        from broker import protection_state as PS
        ctx = self.execution_context
        if ctx is None:
            return {"schema": PS.SCHEMA, "outcome": PS.NO_VENUE_STOP,
                    "adopted": None, "reason": "no_execution_context",
                    "detail": "no context to reconcile protection into"}
        if working_orders is None:
            try:
                working_orders = self.working_orders()
            except Exception as exc:  # noqa: BLE001
                return {"schema": PS.SCHEMA, "outcome": PS.NO_VENUE_STOP,
                        "adopted": ctx.active_protective_stop,
                        "reason": "venue_unreadable",
                        "detail": f"{type(exc).__name__}: {str(exc)[:120]}"}
        stop = self.protective_children(working_orders).get("stop")
        result = PS.reconcile_with_venue(
            direction=ctx.direction,
            active_protective_stop=ctx.active_protective_stop,
            venue_stop_price=_price_of(stop) if stop else None)
        if result.get("outcome") == PS.ADOPTED:
            ctx.active_protective_stop = result["adopted"]
            ctx.save()
        return result

    def entry_exposure_state(self) -> dict:
        """What this entry can still do to the account, read from the venue.

        Three separate facts, never merged: is the PARENT still able to fill, is
        there a POSITION, and are there mission-owned working orders. "Flat" is
        only one of them, and it is the one that a late parent fill can undo.
        """
        try:
            orders = self.working_orders()
            positions = self.session.open_positions()
        except Exception as exc:  # noqa: BLE001
            return {"readable": False, "detail": f"{type(exc).__name__}: {str(exc)[:120]}"}
        parent = [o for o in (orders or []) if str(o.get("id")) == str(self.order_id)]
        mine = [o for o in (orders or []) if self.mission_owns_order(o)
                and str(o.get("id")) != str(self.order_id)]
        qty = sum(abs(int(p.get("size") or 0)) for p in (positions or [])
                  if str(p.get("contract_id") or p.get("contractId") or "")
                  == str(self.contract.id))
        return {"readable": True, "parent_working": bool(parent),
                "position_quantity": qty, "mission_orders": [o.get("id") for o in mine],
                "terminal": (not parent) and qty == 0 and not mine}

    def abandon_unfilled_entry(self, reason: str, *, passes: int = 3) -> dict:
        """Fail closed on an entry whose fill could not be authoritatively proven.

        ABANDONMENT IS A LIFECYCLE DECISION. LIQUIDATION IS NOT.

        This method used to carry its own convergence loop -- cancel the parent,
        re-read, close the position, then cancel the protective children. That
        ordering was written to solve a real problem the emergency path did not
        yet solve: for a PARTIALLY filled parent, closing 5 of 12 and cancelling
        afterwards leaves a window in which the remaining 7 can fill, and the
        account comes back from the dead after recovery has begun.

        The reasoning was right and the scope was too narrow. It stopped the
        PARENT from creating new exposure before the close, but left the
        protective CHILDREN executable across it -- which is the ordering
        `TOPSTEP-EMERGENCY-FLATTEN-ATOMICITY-1` removed from `emergency_flatten`
        on the evidence of 2026-08-26, where a surviving stop reversed a flat
        account 86 milliseconds after the close. Two liquidation sequences meant
        each one only defended against the failure its author had seen.

        THE PARENT WAS NEVER A SPECIAL CASE. `mission_owns_order` proves the
        entry order by id, so the certified planner already treats an unfilled
        remainder as exactly what it is -- a member of the old-trade exposure
        set -- and neutralises it in the same batch as the children, before any
        close. The general law subsumes the special one:

            an old-trade order can create unintended exposure whenever its
            executable quantity exceeds the REMAINING opposing position

        SELL 15 entry, 8 filled, 7 still working: closing BUY 8 leaves SHORT 7.
        Same defect class as the stop, and now the same defence.

        So account mutation is delegated in full. What stays here is the part
        that is genuinely about the ATTEMPT rather than the ACCOUNT: the
        abandonment reason, the bookkeeping, and the refusal to call a recovery
        clean on anything less than a proven-terminal parent, zero position and
        zero mission-owned working orders.

        `passes` is retained for call compatibility. Convergence rounds are the
        planner's budget now, and it reports how many it used.

        A 2xx is never proof; the re-read is.
        """
        liquidation = self.emergency_flatten(f"abandoning unfilled entry: {reason}")

        # STEPS ARE DERIVED FROM WHAT ACTUALLY HAPPENED, never narrated
        # independently. The parent is named separately only because a reader
        # of this report cares which order was the entry -- the planner made no
        # such distinction, and did not need to.
        steps: list = []
        for oid in liquidation.get("cancelled_mission_orders") or []:
            steps.append({"step": ("cancel_parent" if str(oid) == str(self.order_id)
                                   else "cancel_child"),
                          "ok": True, "order_id": oid})
        for failure in liquidation.get("cancellation_failures") or []:
            oid = failure.get("order_id")
            steps.append({"step": ("cancel_parent" if str(oid) == str(self.order_id)
                                   else "cancel_child" if oid is not None
                                   else "close_position"),
                          "ok": False, "order_id": oid,
                          "error": failure.get("error")})
        if liquidation.get("closed") or self.contract.id in (
                liquidation.get("closed_contracts") or []):
            steps.append({"step": "close_position", "ok": True})
        if liquidation.get("emergency_state") == EL.E9_INCIDENT_HALT:
            steps.append({"step": "halt", "ok": False, "halted": True,
                          "reason": liquidation.get("emergency_reason"),
                          "error": liquidation.get("emergency_detail")})
        for halt in liquidation.get("halts") or []:
            steps.append({"step": "read", "ok": False, "detail": halt})

        # THE ABANDONMENT'S OWN PROOF, not the liquidation's. `entry_exposure_state`
        # asserts three separate facts -- parent not working, zero position, no
        # mission-owned orders -- and an abandonment is only clean when all three
        # hold. A safe liquidation that left the parent working is not a
        # completed abandonment.
        final = self.entry_exposure_state()
        safe = bool(final.get("readable") and final.get("terminal"))
        if final.get("terminal"):
            steps.append({"step": "verified_terminal", "ok": True})
        out = {"safe": safe, "reason": reason, "steps": steps,
               "final_state": final, "passes_used": liquidation.get("rounds"),
               "liquidation": liquidation}
        if not safe and self.state != RESIDUAL_ORDERS:
            # Never claim a clean recovery we could not prove. RESIDUAL_ORDERS is
            # the existing "operator must resolve this" state; `verify_clean`
            # already refuses completion from it. `emergency_flatten` may have
            # entered it already -- this does not re-enter.
            self._to(RESIDUAL_ORDERS,
                     f"unfilled-entry recovery could not be proven terminal: {reason}",
                     out)
        return out

    def establish_structural_protection(self, *, deadline_seconds: float = FILL_DEADLINE_SECONDS,
                                        sleep=None) -> dict:
        """ACK -> full fill -> authorized structure. The prompt post-fill lifecycle.

        This is what production waits for before calling an entry established.
        Before it existed, the only fill observer in the system was the
        scan-tick `MissionReconciler`, up to sixty seconds later -- and its own
        docstring records a trade that was "born and stopped out inside one"
        tick. A re-anchor a minute late is not protection.

            ACK != FILL
            FILL != FULL FILL
            FULL FILL != STRUCTURAL PROTECTION
            STRUCTURAL PROTECTION requires a venue readback
        """
        self._to(PROTECTION_PENDING,
                 "provisional fill-relative brackets are live; acquiring authoritative fill")
        fill = self.acquire_full_fill(deadline_seconds=deadline_seconds, sleep=sleep)
        if not fill.get("complete"):
            # NOT `emergency_flatten`. The parent may still be able to fill, and
            # closing the position before cancelling it is how a "flat" account
            # comes back from the dead. `no_fill_observed` in particular does not
            # prove no position exists -- `recent_trades` can simply lag -- so the
            # venue is asked what is actually true rather than assumed harmless.
            recovery = self.abandon_unfilled_entry(
                f"authoritative fill not established ({fill.get('reason')}): "
                f"{fill.get('detail')}")
            return {"established": False, "reason": fill.get("reason"),
                    "fill": fill, "recovery": recovery, "safe": recovery["safe"]}
        self._to(FILLED,
                 f"full fill proven: {fill['size']} @ {fill['fill_price']} "
                 f"across {fill['fill_count']} execution(s)", {"fill": fill})
        anchor = self.reanchor_protection_to_structure(
            fill_event={"price": fill["fill_price"], "size": fill["size"],
                        "contract_id": self.contract.id},
            working_orders=self.working_orders())
        # `already_established` is establishment, not failure: it means proven
        # structural protection is live and possibly advanced. Treating it as a
        # failure would halt a healthy managed position.
        established = bool(anchor.get("reanchored") or anchor.get("already_established"))
        return {"established": established, "fill": fill, "anchor": anchor,
                "reason": None if established else anchor.get(
                    "reason") or (anchor.get("authorization") or {}).get("reason")}

    def verify_protection(self, working_orders: list, *, fill_price=None,
                          authorization: dict = None) -> dict:
        """Both protective legs must sit on the AUTHORIZED ABSOLUTE prices.

        EXEC-PRICE-ANCHOR-1: this used to check existence plus "opposite sides
        of `geo.entry_price`" -- which a fill-relative bracket passes trivially,
        because a distance preserved from the fill is always on the correct
        side. Side agreement is not price agreement, so the price itself is now
        the proposition.

        `fill_price` is optional so pre-repair callers keep the side check; when
        it is supplied the absolute-price contract is enforced.
        """
        geo = self.geometry
        # WORKING ONLY. A protective verdict is a claim about what can still
        # act; a Filled or Cancelled leg satisfies no part of it.
        rows = [o for o in DISC.working_orders(working_orders)
                if o.get("contract_id") == self.contract.id]
        stops = [o for o in rows if int(o.get("type") or 0) == 4]
        targets = [o for o in rows if int(o.get("type") or 0) == 1]
        if not stops or not targets:
            flat = self.emergency_flatten(
                f"protection incomplete: {len(stops)} stop(s), {len(targets)} target(s)")
            return {"verified": False, "reason": "protection_incomplete", "flattened": flat}

        stop_px = _price_of(stops[0])
        target_px = _price_of(targets[0])
        reference = geo.entry_price if fill_price is None else float(fill_price)
        wrong = []
        if geo.direction == "bullish":
            if stop_px is None or stop_px >= reference:
                wrong.append(f"stop {stop_px} not below {reference}")
            if target_px is None or target_px <= reference:
                wrong.append(f"target {target_px} not above {reference}")
        else:
            if stop_px is None or stop_px <= reference:
                wrong.append(f"stop {stop_px} not above {reference}")
            if target_px is None or target_px >= reference:
                wrong.append(f"target {target_px} not below {reference}")
        if wrong:
            flat = self.emergency_flatten("bracket wrongly signed: " + "; ".join(wrong))
            return {"verified": False, "reason": "bracket_wrongly_signed",
                    "detail": "; ".join(wrong), "flattened": flat}

        if fill_price is not None:
            auth = authorization or self.authorize_actual_fill(
                {"price": fill_price, "size": geo.size})
            want_stop = auth.get("aligned_stop_price")
            want_target = auth.get("aligned_target_price")
            size = int(auth.get("size") or geo.size)
            drift = []
            if want_stop is None or want_target is None:
                drift.append("authorized absolute prices unavailable")
            else:
                if stop_px is None or abs(stop_px - want_stop) > _PRICE_EPSILON:
                    drift.append(f"stop working at {stop_px}, authorized structure is {want_stop}")
                if target_px is None or abs(target_px - want_target) > _PRICE_EPSILON:
                    drift.append(f"target working at {target_px}, authorized objective is {want_target}")
            for name, order in (("stop", stops[0]), ("target", targets[0])):
                if not self.mission_owns_order(order):
                    drift.append(f"{name} order {order.get('id')} is not provably ours")
                qty = order.get("size") if order.get("size") is not None else order.get("quantity")
                if qty is not None and int(qty) != size:
                    drift.append(f"{name} quantity {qty} != filled quantity {size}")
            if drift:
                flat = self.emergency_flatten(
                    "protection is not on the authorized structure: " + "; ".join(drift))
                return {"verified": False, "reason": "protection_not_on_structure",
                        "detail": "; ".join(drift), "stop_price": stop_px,
                        "target_price": target_px, "flattened": flat}

        self._to(PROTECTED, "stop and target working on the authorized structure"
                 if fill_price is not None else "stop and target working on the correct sides",
                 {"stop_order": stops[0], "target_order": targets[0],
                  "stop_price": stop_px, "target_price": target_px,
                  "anchored_to_structure": fill_price is not None})
        return {"verified": True, "stop": stops[0], "target": targets[0],
                "stop_price": stop_px, "target_price": target_px,
                "anchored_to_structure": fill_price is not None}

    # ── 6. exit ───────────────────────────────────────────────────────────────
    def observe_exit(self, exit_event: dict, remaining_orders: list) -> dict:
        self._to(EXIT_PENDING, f"exit observed: {exit_event.get('reason')}", {"exit": exit_event})
        # Scoped by mission lineage, not by contract: an operator order on the
        # same instrument is not ours to cancel.
        split = self.classify_working_orders(remaining_orders or [])
        residual = split["ours"]
        cancelled = []
        for o in residual:
            # OCO should have removed the opposing side. If it did not, that is a
            # venue defect and it gets recorded as one — after we cancel it.
            try:
                self.session.cancel_order(o.get("id"))
                cancelled.append(o.get("id"))
            except TopstepXError as exc:
                self._to(RESIDUAL_ORDERS, f"could not cancel residual order {o.get('id')}: {exc}")
        return {"exit": exit_event, "residual_cancelled": cancelled,
                "oco_defect": bool(cancelled),
                # Never cancelled, always surfaced: verify_clean blocks on these.
                "unaccounted_same_contract": [o.get("id") for o in split["unproven"]],
                "foreign_other_contract": [o.get("id") for o in split["foreign"]]}

    # ── whose order is it? ────────────────────────────────────────────────────
    def mission_owns_order(self, order: dict) -> bool:
        """Is this working order OURS? Lineage only -- never "same contract".

        Measured live 2026-08-10: `close_position` flattens the position and
        leaves the OCO stop and target WORKING. Cleanup therefore has to cancel
        them, and cancelling by contract alone would reach an operator's own
        order on the same instrument.

        Topstep exposes the lineage directly -- the protective legs carry
        `parentOrderId` = the entry order id, the target additionally carries
        `linkedOrderId` = the stop, and their tags are the entry tag suffixed
        `-SL` / `-TP`. Ownership is proven from those, or not claimed at all.

        ONE OWNERSHIP CONTRACT (TOPSTEP-PROTECTIVE-DISCOVERY-AND-LINEAGE-1).
        The rule itself now lives in `topstepx_order_discovery` and the durable
        reconciler asks the same function. Two implementations that disagree are
        worse than either alone: the reconciler accepted only `parent_order_id`,
        so an order proven ours here could be a stranger to the record that
        outlives this process.

        The one thing added locally is the ENTRY ORDER ITSELF. It is ours by
        identity rather than by lineage -- nothing is its parent -- and only
        this object knows which id that is.
        """
        order = order or {}
        if self.order_id is not None and str(order.get("id") or "") \
                == str(self.order_id):
            return str(order.get("contract_id") or order.get("contractId") or "") \
                == str(self.contract.id)
        token_id = str(getattr(getattr(self, "token", None), "token_id", "") or "")
        return DISC.owns(
            order, entry_order_id=self.order_id, contract_id=self.contract.id,
            custom_tag=str(getattr(self, "submission_custom_tag", "") or "").strip(),
            token_id=token_id)

    def classify_working_orders(self, orders=None) -> dict:
        """Split working orders three ways. The middle one is the safe one.

            ours       lineage proves it is this mission's -> CANCEL
            unproven   on our contract, lineage absent     -> BLOCK, never cancel
            foreign    a different contract                -> ignore entirely

        The asymmetry is deliberate. Cancelling requires proof, because
        cancelling an operator's order is an unrecoverable act against someone
        else's intent. BLOCKING requires only doubt, because a working order on
        our instrument that we cannot account for might be our own orphaned
        bracket -- and an orphaned SELL stop under a "flat" bot opens a short.

        So we never cancel what we cannot prove, and never complete while
        anything on our contract is unaccounted for. The operator resolves the
        middle case; the bot refuses to guess in either direction.
        """
        # UNSCOPED. `foreign` means "a different contract", so scoping discovery
        # to our own instrument would make the category unreachable and quietly
        # reduce a three-way judgement to two.
        rows = list(orders if orders is not None
                    else self.working_orders(scoped=False))
        ours, unproven, foreign = [], [], []
        for o in rows:
            same_contract = str((o or {}).get("contract_id")
                                or (o or {}).get("contractId") or "") \
                == str(self.contract.id)
            if self.mission_owns_order(o):
                ours.append(o)
            elif same_contract:
                unproven.append(o)
            else:
                foreign.append(o)
        return {"ours": ours, "unproven": unproven, "foreign": foreign}

    def mission_owned_working_orders(self, orders=None) -> tuple:
        """(ours, everything else). Kept for callers that only cancel."""
        split = self.classify_working_orders(orders)
        return split["ours"], split["unproven"] + split["foreign"]

    def _discover_orders(self, *, scoped: bool = True) -> dict:
        """Canonical order discovery for THIS contract. Never raises.

        Every protection-bearing read in this class used to call
        `session.open_orders()`, i.e. `/api/Order/searchOpen`, which OMITS
        Suspended bracket children by official Gateway contract. So a staged
        stop was invisible to protection verification, to re-anchor readback, to
        exposure accounting and to residual-order cleanup alike -- and each of
        those treats "not in the list" as "does not exist".
        """
        return DISC.discover_orders(
            self.session, contract_id=self.contract.id if scoped else None)

    def working_orders(self, *, scoped: bool = True) -> list:
        """Orders that could still change the account. RAISES when unreadable.

        Terminal rows are excluded: v2/query is a history surface too, and a
        consumer counting working orders must not start counting this morning's
        fills. Completeness is available via `_discover_orders()` for the
        callers whose conclusion depends on having seen everything.

        IT RAISES ON PURPOSE. `discover_orders` never throws, which is right for
        the emergency path -- an exception mid-liquidation is worse than a
        labelled degraded read. But every caller here replaced a call that DID
        throw, and each one wraps it in a `try` whose except branch is the only
        thing standing between an unreadable venue and a claim of safety.
        Silently handing those callers `[]` would convert "we cannot see" into
        "there is nothing there", which is this unit's entire defect.

        `scoped=False` returns other contracts too, for the three-way ownership
        split: an order we classify as FOREIGN must first be visible enough to
        be classified.
        """
        return DISC.require_working_orders(
            self.session, contract_id=self.contract.id if scoped else None)

    def _emergency_venue_read(self) -> dict:
        """Position and EVERY order that could still change it. Never raises.

        DISCOVERY IS NOT `searchOpen`. The official Gateway contract omits
        Suspended bracket children from that endpoint, so its silence is not
        evidence that no protection exists -- and every discovery path in this
        stack read it. `query_orders` asks for Open, Pending, PendingCancellation
        and Suspended explicitly, so a staged child cannot hide behind the
        query's own semantics.

        Falls back to `open_orders()` only when the venue cannot serve the
        query, and says so, because a narrower view must never be mistaken for
        a complete one.
        """
        out = {"positions": None, "orders": None, "errors": [],
               "discovery": "query_orders", "readable": False,
               # LOAD-BEARING, not decoration. Consumed by `EL.plan` before any
               # mutation and by `confirm_flat_and_clear` before any claim.
               "complete": False}
        try:
            out["positions"] = self.session.open_positions()
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"open_positions: {type(exc).__name__}: {exc}")
            return out
        try:
            # NO STATUS FILTER. Deliberately.
            #
            # Filtering to the statuses we currently recognise would let the
            # venue hide a state simply because our enum has not heard of it:
            #
            #     venue returns status 9 someday
            #     -> query asks only for 1/6/7/8
            #     -> the order is invisible
            #     -> the planner never gets to call it UNKNOWN
            #
            # The planner's fail-closed handling of an unrecognised status is
            # worthless if acquisition filters that status out first. A consumer
            # can only reason over facts the producer lets reach it, so
            # discovery returns everything on this contract and classification
            # happens locally, where an unknown value routes to E9.
            out["orders"] = self.session.query_orders(
                contract_id=self.contract.id)
            out["complete"] = True
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"query_orders: {type(exc).__name__}: {exc}")
            try:
                out["orders"] = self.session.open_orders()
                out["discovery"] = "open_orders_fallback_INCOMPLETE"
            except Exception as exc2:  # noqa: BLE001
                out["errors"].append(f"open_orders: {type(exc2).__name__}: {exc2}")
                return out
        out["readable"] = True
        return out

    def _signed_position(self, positions) -> "int | None":
        """Net exposure as a signed integer. None when unreadable -- and None
        must never be coerced to zero, because 'I cannot see the position' and
        'there is no position' are the two states this whole unit exists to
        keep apart."""
        try:
            for row in positions or []:
                if str(row.get("contract_id") or row.get("contractId") or "") \
                        != str(self.contract.id):
                    continue
                size = row.get("size") if row.get("size") is not None \
                    else row.get("netPos")
                if size is None:
                    return None
                size = int(size)
                kind = row.get("type")
                if kind is not None and int(kind) == 2 and size > 0:
                    size = -size          # venue encodes short as type 2
                return size
            return 0
        except (TypeError, ValueError):
            return None

    def emergency_flatten(self, reason: str) -> dict:
        """Converge to FLAT without letting a protective order become an entry.

        THE INCIDENT THIS REPLACES. 2026-08-26, venue-proven: this method
        closed the position first and cancelled the brackets after. 86 ms after
        the close filled, the still-working protective stop fired into a flat
        account and opened a LONG 15. Cleanup cost $307.50 -- more than the
        $210.00 lost by the trade the stop was protecting.

        Order 3451056003 never changed. It was protection while a short
        existed and an ENTRY the moment the account went flat. Authority is a
        relationship between an order and a currently existing position.

        SO CHILDREN ARE NEUTRALISED BEFORE FLATNESS IS CREATED. A child can
        only reverse an account that is already flat; removing entry authority
        first is what makes the close safe. Eight of the nine callers reach
        here because protection is already untrustworthy, so cancelling it
        removes nothing real. The post-fill-authorization caller is the one
        case where valid protection is withdrawn -- that window is reported as
        EMERGENCY_NAKED rather than hidden.

        THE TERMINAL STATE IS COMPOUND: position flat AND every old-trade order
        positively non-executable. Flat alone was true at 13:37:59.718, 86 ms
        before LONG 15.

        `topstepx_emergency_liquidation` decides; this executes. Every step is
        followed by a fresh venue read, and any ambiguity halts rather than
        issuing another position-changing order.
        """
        self._to(EMERGENCY_FLATTENING, reason)
        cancelled, failed, halts, closes = [], [], [], []
        close_state = EL.CLOSE_NOT_SUBMITTED
        decision, rounds = None, 0

        for rounds in range(EL.DEFAULT_MAX_ROUNDS):
            read = self._emergency_venue_read()
            if not read["readable"]:
                halts.append(f"venue unreadable: {read['errors']}")
                break
            size = self._signed_position(read["positions"])
            decision = EL.plan(position_size=size, orders=read["orders"],
                               owns=self.mission_owns_order,
                               close_state=close_state, round_index=rounds,
                               discovery_complete=bool(read.get("complete")))
            action = decision["action"]

            if action == EL.ACTION_CANCEL:
                for oid in decision["order_ids"]:
                    try:
                        self.session.cancel_order(oid)
                        cancelled.append(oid)
                    except Exception as exc:  # noqa: BLE001
                        # A FAILED CANCEL PROVES NOTHING about the order. The
                        # next round re-reads it; it is not assumed gone.
                        # ONE ROW PER ORDER, latest error. The loop retries a
                        # failed cancel deliberately -- a failure proves nothing
                        # about the order -- but a caller wants to know WHICH
                        # orders would not die, not how many times we asked.
                        failed = [f for f in failed if f.get("order_id") != oid]
                        failed.append({"order_id": oid,
                                       "error": f"{type(exc).__name__}: {exc}"})
                continue

            if action == EL.ACTION_PROVE:
                continue        # re-read; PendingCancellation may still fill

            if action == EL.ACTION_CLOSE:
                try:
                    self.session.close_position(self.contract.id)
                    close_state = EL.CLOSE_ACKNOWLEDGED
                    # RECORDED, because "did we mutate the account" is a
                    # question callers ask and `close_state` only answers "what
                    # is in flight right now".
                    closes.append({"contract_id": self.contract.id,
                                   "round": rounds,
                                   "size": decision.get("close_size"),
                                   "side": decision.get("close_side")})
                except Exception as exc:  # noqa: BLE001
                    # AMBIGUOUS. A second close could reverse the account, so
                    # the planner is told the outcome is unknown and halts.
                    close_state = EL.CLOSE_STATE_UNKNOWN
                    failed.append({"order_id": None,
                                   "error": f"close_position: {type(exc).__name__}: {exc}"})
                continue

            break               # DONE or HALT

        safe = EL.is_safe_terminal(decision)
        confirmed = self.confirm_flat_and_clear(reason=reason)
        if not safe:
            detail = (decision or {}).get("detail") or "; ".join(halts) or "unresolved"
            self._to(RESIDUAL_ORDERS, f"emergency liquidation unresolved: {detail}")
        # PRESERVED for existing consumers: a foreign order is never ours to
        # cancel, and callers have always been told which ones we left alone.
        foreign_seen = [o.get("id")
                        for o in ((decision or {}).get("found") or {}).get("unproven", [])]
        return {"flattened": bool(safe and confirmed.get("clean")),
                "reason": reason,
                "foreign_orders_left_alone": foreign_seen,
                "safe_terminal": safe,
                "emergency_state": (decision or {}).get("state"),
                "emergency_detail": (decision or {}).get("detail"),
                # WHY the halt, not just that one happened. An operator acts
                # differently on "we cannot prove whose order that is" than on
                # "the venue stopped answering", and both arrive as E9.
                "emergency_reason": (decision or {}).get("reason"),
                "unresolved_live_exposure": bool(
                    (decision or {}).get("unresolved_live_exposure")),
                "emergency_naked": bool((decision or {}).get("naked")),
                "rounds": rounds + 1,
                "cancelled_mission_orders": cancelled,
                "cancellation_failures": failed,
                "closes": closes,
                "closed": bool(closes),
                "halts": halts,
                **confirmed}

    def confirm_flat_and_clear(self, *, reason: str = "") -> dict:
        """THE INVARIANT: position == 0 AND no mission-owned working order.

        Returns rather than halting so callers can decide; `verify_clean` is
        the gate that refuses completion. Foreign orders never block us -- they
        are not ours to cancel, and blocking on them would strand the mission.
        """
        # THE TERMINALITY ORACLE CONSUMES COMPLETENESS TOO. Authorizing the
        # mutation and proving the account clear are two separate claims, and
        # both rest on having seen the whole order set.
        found = self._discover_orders(scoped=False)
        if not found["complete"]:
            return {"clean": False, "verified": False,
                    "discovery": found["source"],
                    "detail": ("order discovery is INCOMPLETE; a view that may "
                               "be missing members cannot prove the account "
                               "clear")}
        try:
            positions = self.session.open_positions()
            split = self.classify_working_orders()
        except Exception as exc:  # noqa: BLE001
            # EVERY exception, not just `TopstepXError`. This runs INSIDE
            # `emergency_flatten`, whose whole contract is that it converges or
            # reports honestly -- and a liquidation that raises at an open
            # position abandons it. The narrow except let a transport error, an
            # unpinned session or anything else the venue layer can throw
            # escape a safety path as a crash. UNREADABLE IS `clean: False`.
            return {"clean": False, "verified": False,
                    "detail": f"venue could not be queried: "
                              f"{type(exc).__name__}: {exc}"}
        ours = split["ours"] + split["unproven"]
        clean = not positions and not ours
        detail = {"clean": clean, "verified": True,
                  "open_positions": len(positions),
                  "mission_working_orders": [o.get("id") for o in split["ours"]],
                  "unaccounted_same_contract": [o.get("id") for o in split["unproven"]],
                  "foreign_working_orders": [o.get("id") for o in split["foreign"]]}
        if not clean:
            self._to(RESIDUAL_ORDERS,
                     f"not clean after {reason or 'flatten'}: "
                     f"{len(positions)} position(s), {len(ours)} mission order(s)",
                     detail)
        return detail

    # ── 7. final invariant ────────────────────────────────────────────────────
    def verify_clean(self, *, current_fingerprint: str) -> dict:
        """Final reconciliation by REST, even if realtime already said flat.

        Realtime is a stream of claims; the order and position searches are the
        venue's answer. Only the answer closes the mission.
        """
        positions = self.session.open_positions()
        # Anything working on OUR contract blocks completion -- ours for
        # certain, and unproven ones because they might be our orphaned
        # bracket. Only a different contract is ignored.
        split = self.classify_working_orders()
        orders = split["ours"] + split["unproven"]
        checks = {
            "position_quantity_zero": not positions,
            "working_order_count_zero": not orders,
            "account_fingerprint_unchanged": current_fingerprint == self.account_fingerprint,
            "contract_unchanged": True,
            "authorization_consumed": bool(self.token and self.token.spent),
            "no_second_entry_attempted": True,
        }
        if not checks["position_quantity_zero"]:
            self._halt(FLATTEN_FAILED, f"{len(positions)} position(s) remain")
        if not checks["working_order_count_zero"]:
            self._halt(RESIDUAL_ORDERS,
                       f"{len(orders)} working order(s) remain on {self.contract.id} "
                       f"(mission-owned {[o.get('id') for o in split['ours']]}, "
                       f"unaccounted {[o.get('id') for o in split['unproven']]}); "
                       f"a flat position with a live bracket can open a reverse "
                       f"position",
                       {"mission_owned": [o.get("id") for o in split["ours"]],
                        "unaccounted_same_contract": [o.get("id") for o in split["unproven"]],
                        "foreign_other_contract": [o.get("id") for o in split["foreign"]]})
        if not checks["account_fingerprint_unchanged"]:
            self._halt(ACCOUNT_MISMATCH, "account fingerprint changed during the trade")
        if not checks["authorization_consumed"]:
            self._halt(AUTH_EXPIRED, "authorization was never consumed")
        self._to(FLAT, "position closed, no working orders")
        self._to(VERIFIED_CLEAN, "final invariant satisfied", checks)
        return checks

    # ── evidence ──────────────────────────────────────────────────────────────
    def build_artifact(self, *, readiness_ref: str = "", candidate: dict = None,
                       intake: dict = None, luna_usage: dict = None,
                       exit_result: dict = None) -> dict:
        candidate = candidate or {}
        self.artifact = {
            "mission": "TOPSTEPX COMBINE EXECUTION — one-MNQ full-organism smoke",
            "generated_at_utc": self.clock().isoformat(),
            "readiness_artifact_ref": readiness_ref,
            "final_state": self.state,
            "succeeded": self.state in TERMINAL_SUCCESS,
            "transitions": [t.as_dict() for t in self.transitions],
            "engine_inventory": (intake or {}).get("inventory"),
            "engines_empty_but_present": (intake or {}).get("empty"),
            "thesis": {
                "direction": candidate.get("direction"),
                "playbook_family": candidate.get("playbook_family"),
                "tool_family": candidate.get("tool_family"),
                "invalidation_level": candidate.get("invalidation_level"),
                "target_price": candidate.get("target_price"),
                "provenance": (intake or {}).get("provenance"),
            },
            "risk": self.geometry.evidence() if self.geometry else None,
            # Report the caps THIS runner is actually enforcing. Hardcoding the
            # smoke constant made every production artifact claim a 1-contract
            # ceiling while the runner enforced 15.
            "doctrine": {"max_risk_usd": self.max_risk_usd,
                         "max_contracts": self.max_contracts,
                         "max_stop_points": self.max_stop_points,
                         "compounding": False},
            "authorization": self.token.describe() if self.token else None,
            "order_id": self.order_id,
            "luna_usage": luna_usage,
            "exit": exit_result,
            "secret_redaction_proof": {"secrets_in_artifact": 0,
                                       "method": "topstepx_redaction.assert_clean"},
        }
        return self.artifact

    def write_artifact(self, path: str) -> str:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        body = assert_clean(json.dumps(self.artifact, indent=2, default=str), "lifecycle artifact")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        return path


def _attach_partials(obs, agg, SL):
    """One order, one observation. Unreliable aggregation degrades the record."""
    if agg is None:
        return obs
    obs["partial_fills"] = {"fill_count": agg["fill_count"], "vwap": agg["vwap"],
                            "aggregation_reliable": agg["aggregation_reliable"]}
    if not agg["aggregation_reliable"]:
        obs["reliable"] = False
        obs["quality"] = SL.UNRELIABLE_UNLINKED_FILL
    return obs


def _digest(payload: dict) -> dict:
    """Safe request summary — shape and sizes, never the account number."""
    return {"contractId": payload.get("contractId"), "type": payload.get("type"),
            "side": payload.get("side"), "size": payload.get("size"),
            "stopLossBracket": payload.get("stopLossBracket"),
            "takeProfitBracket": payload.get("takeProfitBracket"),
            "accountId": "[REDACTED]"}


#: Prices are venue decimals on a 0.25 tick; this only absorbs float noise, and
#: is far tighter than one tick so a genuinely misplaced leg can never pass.
_PRICE_EPSILON = 1e-6


def _price_of(order: dict):
    for key in ("stop_price", "limit_price", "stopPrice", "limitPrice"):
        v = (order or {}).get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _slippage(geo, fill_price):
    if geo is None or fill_price is None:
        return None
    try:
        return round(float(fill_price) - geo.entry_price, 4)
    except (TypeError, ValueError):
        return None
