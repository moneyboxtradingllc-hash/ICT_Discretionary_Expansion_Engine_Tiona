r"""Durable session authorization and per-trade child missions.

Arming is not a flag. `--arm` alone is a process argument: it does not survive a
restart, it carries no account identity, and it cannot say which session it
authorized. A durable record can — and it is what a restarted process reads to
learn that its allowance was already spent.

    session authorization (max 2 trades)
        |-- trade mission 1  (max 1 attempt)
        \-- trade mission 2  (max 1 attempt)

Two separate controls. A trade mission's single attempt is consumed by the
ATTEMPT, not by a fill: a venue rejection spends it exactly like an execution,
because the alternative is retrying into a venue whose state is unknown.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone

from broker import topstepx_mission_recovery as RECOVERY
# RISK-DOCTRINE-MIGRATION (2026-08-20). The bound terms below were LITERALS
# restating production doctrine. When the ceiling moved to 50.0 and the risk
# cap to $350, a correctly-minted authorization would have been refused by
# its own doctrine check -- the one gate that must never disagree with the
# engine it authorizes. The trades check already read its owner
# (MAX_BOT_TRADES_PER_SESSION); these now do too.
from broker.topstepx_combine_risk import (ABSOLUTE_MAX_STOP_POINTS,
                                          PREFERRED_MAX_STOP_POINTS,
                                          PRODUCTION_MAX_CONTRACTS,
                                          PRODUCTION_MAX_RISK_USD)
from broker import topstepx_mission_state as MS

#: OWNER LAW (2026-08-31). The session's realized-loss spending limit, in
#: dollars. It lives HERE, beside the other signed session terms, rather than in
#: `topstepx_combine_risk`: this is a per-session authorization constraint, not
#: a global strategy constant, and duplicating it into the risk module would
#: create a second owner of a number only the authorization may commit to.
#:
#: IT IS A BUDGET, NOT A GUARANTEE. It governs whether a NEW entry may be sized
#: and how large it may be. A stop that gaps can still realize more than this.
DAILY_LOSS_BUDGET_USD = 725.00

MAX_BOT_TRADES_PER_SESSION = 2
MAX_ATTEMPTS_PER_TRADE_MISSION = 1
COMPOUNDING = False

# The TopstepX production decision window. Deliberately NOT read from
# SCAN_START_TIME/SCAN_END_TIME: those configure the legacy equity scan loop
# (08:30-15:00) and must never silently widen the live futures trading window.
#
# PRE-NY-EXECUTION-WINDOW-1:
# MNQ trades continuously before the 09:30 US cash open. Luna cognition is
# already active pre-bell; this boundary governs when candidate/execution
# authority becomes lawful. Candidate and mission gates share this window.
PRODUCTION_WINDOW_START = "09:00"
PRODUCTION_WINDOW_END = "14:00"
PRODUCTION_WINDOW_TZ = "America/New_York"

#: DATE-SCOPED OPERATOR WINDOW RULINGS.
#:
#: An extended session is a decision about ONE DAY, so it is expressed as one
#: day and expires by construction. A key that is not today's session date
#: cannot widen today's window, and a forgotten entry cannot silently become
#: permanent doctrine -- which is exactly what editing PRODUCTION_WINDOW_END
#: would have done. Every date absent from this map gets 09:30-14:00.
#:
#: `hard_flatten` is a SEPARATE authority from `end`. `end` stops new entries;
#: `hard_flatten` closes what is already open. They may share a clock time and
#: they do not share a meaning: at the boundary the machine's job changes from
#: finding trades to getting flat.
SESSION_WINDOW_OVERRIDES = {
    # 2026-08-12 operator ruling, TODAY ONLY. The production defect found this
    # morning cost the session its first four hours; scanning is extended to
    # 15:54:59 with a hard flatten at 15:55. 2026-08-13 reverts automatically.
    "20260812": {"start": "09:30", "end": "15:55", "hard_flatten": "15:55"},
}


def window_for(session_date) -> dict:
    """The effective window for ONE session date.

    Returns start/end/hard_flatten plus whether an override applied, so callers
    can TELL THE OPERATOR rather than quietly running a different day's rules.
    """
    key = str(session_date or "").strip()
    o = SESSION_WINDOW_OVERRIDES.get(key)
    if o:
        return {"session_date": key, "start": o["start"], "end": o["end"],
                "hard_flatten": o.get("hard_flatten"), "override": True}
    return {"session_date": key, "start": PRODUCTION_WINDOW_START,
            "end": PRODUCTION_WINDOW_END, "hard_flatten": None, "override": False}


def window_text(session_date) -> str:
    """The canonical `HH:MM-HH:MM TZ` string stamped into an authorization."""
    w = window_for(session_date)
    return f"{w['start']}-{w['end']} {PRODUCTION_WINDOW_TZ}"


class AuthorizationRefused(RuntimeError):
    """The session is not authorized to execute. Always fail closed."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SessionAuthorization:
    """What must be true, durably, before any order path becomes reachable."""
    session_id: str
    account_fingerprint: str
    contract_id: str
    session_date: str
    decision_window: str
    maximum_trades: int = MAX_BOT_TRADES_PER_SESSION
    maximum_risk_per_trade: float = PRODUCTION_MAX_RISK_USD
    maximum_contracts: int = PRODUCTION_MAX_CONTRACTS
    preferred_stop_ceiling: float = PREFERRED_MAX_STOP_POINTS
    absolute_stop_ceiling: float = ABSOLUTE_MAX_STOP_POINTS
    # Bound terms, not decoration: an authorization that did not commit to the
    # attempt cap or to compounding-off could be widened after signing.
    maximum_attempts_per_trade: int = MAX_ATTEMPTS_PER_TRADE_MISSION
    compounding: bool = COMPOUNDING
    # UPGRADE-...-TERRA (2026-08-06): the Brain identity is part of what was
    # authorized. Binding only the risk terms would let the model, its reasoning
    # effort, JSON enforcement or the prompt/validator contract change under an
    # authorization that was granted for a different organism -- which is
    # exactly what happened mid-session on 2026-08-06 when the semantic contract
    # was repaired while an authorization was live.
    brain_model: str = ""
    brain_reasoning_effort: str = ""
    json_mode_required: bool = True
    brain_contract_fingerprint: str = ""
    # ENFORCE-MEMORY-RETRIEVAL-ENABLEMENT-AUTHORITY (2026-08-07): whether the
    # session was authorized to reason WITH historical descriptive analogs.
    # Bound because it materially changes the evidence payload the Brain
    # receives -- an authorization granted to a memory-enabled organism must not
    # silently validate under a memory-blind runtime, or the reverse.
    retrieval_enabled: bool = False
    # LUNA-DAILY-LOSS-BUDGET-GOVERNOR-1 (2026-08-31). A SIGNED SESSION LOSS
    # BUDGET, and deliberately a SENTINEL rather than a default value.
    #
    # `= 725.0` would have been the convenient choice and the wrong one: every
    # authorization written before this term existed would silently acquire a
    # limit it never signed, which is retroactively strengthening a record after
    # the fact. `None` instead means the record still LOADS for inspection --
    # and cannot VERIFY as execution-authoritative, because `verify` refuses it
    # below. The issuer supplies the value explicitly; nothing else may.
    #
    # It participates in `fingerprint()`, so a budget hand-edited on disk fails
    # verification exactly like a hand-widened risk ceiling.
    daily_loss_budget_usd: "float | None" = None
    issued_at: str = ""
    authorization_fingerprint: str = ""
    path: str = ""

    # ── identity ──────────────────────────────────────────────────────────────
    def fingerprint(self) -> str:
        """Binds the authorization to its own terms.

        Editing any limit on disk changes this, so a hand-widened risk ceiling
        or contract cap fails verification instead of being honoured.
        """
        # Every part is coerced to str. A record written before the Terra
        # migration has None for the brain fields, and joining None raised
        # TypeError -- which propagated out of verify() as an unhandled crash
        # instead of a stated refusal, because the launcher only catches
        # AuthorizationRefused. A legacy record must FAIL CLOSED, not explode.
        raw = "|".join(str(part if part is not None else "") for part in (
            self.session_id, self.account_fingerprint, self.contract_id,
            self.session_date, self.decision_window, self.maximum_trades,
            self.maximum_risk_per_trade, self.maximum_contracts,
            self.preferred_stop_ceiling, self.absolute_stop_ceiling,
            self.maximum_attempts_per_trade, bool(self.compounding),
            self.brain_model, self.brain_reasoning_effort,
            bool(self.json_mode_required), self.brain_contract_fingerprint,
            bool(self.retrieval_enabled),
            self.daily_loss_budget_usd,
            self.issued_at))
        return "auth:" + hashlib.sha256(raw.encode()).hexdigest()[:16]

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k != "path"}

    def save(self) -> str:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path), prefix=".auth-")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self.as_dict(), fh, indent=2, default=str)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)
        return self.path

    # ── verification ──────────────────────────────────────────────────────────
    def verify(self, *, account_fingerprint: str, contract_id: str,
               session_date: str, now: datetime = None) -> "SessionAuthorization":
        """Every mismatch is a refusal. Nothing here repairs or widens."""
        # THE BUDGET MUST HAVE BEEN SIGNED. A record from before this term
        # existed is readable, auditable and NOT execution-authoritative: the
        # session loss budget is a limit the authorization has to have committed
        # to, and no default may supply it after the fact.
        budget = self.daily_loss_budget_usd
        if budget is None:
            raise AuthorizationRefused(
                "NO_DAILY_LOSS_BUDGET: this authorization predates the signed "
                "session loss budget and cannot authorize execution; issue a "
                "new one rather than defaulting a term it never signed")
        try:
            value = float(budget)
        except (TypeError, ValueError):
            value = float("nan")
        if not (value == value) or value <= 0:
            raise AuthorizationRefused(
                f"INVALID_DAILY_LOSS_BUDGET: {budget!r} is not a positive "
                f"dollar amount")
        # ORDER MATTERS. The budget check runs FIRST because the term is part
        # of the fingerprint: a record written before it existed fails the
        # signature too, and reporting that as AUTHORIZATION_CORRUPT would
        # accuse an honest legacy record of having been tampered with. Schema
        # growth and a hand-edited limit are different facts and get different
        # refusals. A record that HAS a budget and was edited still fails below.
        if self.authorization_fingerprint != self.fingerprint():
            raise AuthorizationRefused(
                "AUTHORIZATION_CORRUPT: the record does not match its own terms; "
                "a limit was edited after it was signed")
        if self.account_fingerprint != account_fingerprint:
            raise AuthorizationRefused(
                "AUTHORIZATION_ACCOUNT_MISMATCH: authorized for a different account")
        if self.contract_id != contract_id:
            raise AuthorizationRefused(
                f"AUTHORIZATION_CONTRACT_MISMATCH: authorized for {self.contract_id}, "
                f"session trades {contract_id}")
        if self.session_date != session_date:
            raise AuthorizationRefused(
                f"AUTHORIZATION_EXPIRED: issued for {self.session_date}, "
                f"today is {session_date}; authorization does not roll over")
        if self.maximum_trades > MAX_BOT_TRADES_PER_SESSION:
            raise AuthorizationRefused(
                f"AUTHORIZATION_EXCEEDS_DOCTRINE: {self.maximum_trades} trades "
                f"above the {MAX_BOT_TRADES_PER_SESSION}-trade session law")
        if (self.absolute_stop_ceiling > ABSOLUTE_MAX_STOP_POINTS
                or self.maximum_risk_per_trade > PRODUCTION_MAX_RISK_USD):
            raise AuthorizationRefused(
                f"AUTHORIZATION_EXCEEDS_DOCTRINE: stop ceiling "
                f"{self.absolute_stop_ceiling:g}/{ABSOLUTE_MAX_STOP_POINTS:g} or risk "
                f"${self.maximum_risk_per_trade:g}/${PRODUCTION_MAX_RISK_USD:g} above production law")
        if int(self.maximum_attempts_per_trade or 0) > MAX_ATTEMPTS_PER_TRADE_MISSION:
            raise AuthorizationRefused(
                f"AUTHORIZATION_EXCEEDS_DOCTRINE: {self.maximum_attempts_per_trade} "
                f"attempts per trade above the {MAX_ATTEMPTS_PER_TRADE_MISSION}-attempt law")
        if int(self.maximum_contracts or 0) > 15:
            raise AuthorizationRefused(
                f"AUTHORIZATION_EXCEEDS_DOCTRINE: {self.maximum_contracts} contracts above 15")
        if float(self.preferred_stop_ceiling or 0) > 35.0:
            raise AuthorizationRefused(
                f"AUTHORIZATION_EXCEEDS_DOCTRINE: preferred stop "
                f"{self.preferred_stop_ceiling} above 35 points")
        if bool(self.compounding):
            raise AuthorizationRefused(
                "AUTHORIZATION_EXCEEDS_DOCTRINE: compounding is off by doctrine")
        from ai_brain import production_model as PM
        if self.brain_model and self.brain_model != PM.PRODUCTION_MODEL:
            raise AuthorizationRefused(
                f"AUTHORIZATION_BRAIN_MODEL_MISMATCH: authorized for "
                f"{self.brain_model!r}, production now runs {PM.PRODUCTION_MODEL!r}")
        if (self.brain_contract_fingerprint
                and self.brain_contract_fingerprint != PM.brain_contract_fingerprint()):
            raise AuthorizationRefused(
                "AUTHORIZATION_BRAIN_CONTRACT_CHANGED: the prompt/schema/validator "
                "contract changed after this authorization was issued")
        from ai_retrieval.retrieval import retrieval_enabled as _retrieval_enabled
        runtime_retrieval = _retrieval_enabled()
        if bool(self.retrieval_enabled) != runtime_retrieval:
            raise AuthorizationRefused(
                f"AUTHORIZATION_RETRIEVAL_STATE_MISMATCH: authorized with "
                f"retrieval_enabled={bool(self.retrieval_enabled)}, runtime "
                f"resolves {runtime_retrieval}. Descriptive analogs change what "
                f"the Brain receives, so the two must agree.")
        if self.brain_reasoning_effort != (PM.reasoning_effort() or ""):
            raise AuthorizationRefused(
                f"AUTHORIZATION_REASONING_EFFORT_MISMATCH: authorized "
                f"{self.brain_reasoning_effort!r}, production resolves "
                f"{PM.reasoning_effort()!r}")
        # The window is checked against the ruling for THIS authorization's own
        # session date, so an extended day verifies on that day and only on that
        # day. A record carrying 09:30-15:55 for any other date is a mismatch.
        _w = window_for(self.session_date)
        expected_window = f"{_w['start']}-{_w['end']} {PRODUCTION_WINDOW_TZ}"
        if self.decision_window not in (expected_window,
                                        f"{_w['start']}-{_w['end']}"):
            raise AuthorizationRefused(
                f"AUTHORIZATION_WINDOW_MISMATCH: {self.decision_window!r} is not "
                f"the production window {expected_window!r}")
        return self

    @classmethod
    def load(cls, path: str) -> "SessionAuthorization | None":
        if not os.path.exists(path):
            return None
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception:  # noqa: BLE001 — a damaged record authorizes nothing
            raise AuthorizationRefused(
                "AUTHORIZATION_CORRUPT: the record could not be read") from None
        auth = cls(**{k: d.get(k) for k in (
            "session_id", "account_fingerprint", "contract_id", "session_date",
            "decision_window", "maximum_trades", "maximum_risk_per_trade",
            "maximum_contracts", "preferred_stop_ceiling", "absolute_stop_ceiling",
            "maximum_attempts_per_trade", "compounding", "brain_model",
            "brain_reasoning_effort", "json_mode_required",
            "brain_contract_fingerprint", "retrieval_enabled",
            # LUNA-DAILY-LOSS-BUDGET-GOVERNOR-1. THE ALLOWLIST IS THE CONTRACT:
            # a term absent from it is silently dropped on load, so a correctly
            # signed $725 record came back off disk with None and refused
            # itself with NO_DAILY_LOSS_BUDGET. Signing a term and being able
            # to READ IT BACK are two different guarantees.
            "daily_loss_budget_usd", "issued_at",
            "authorization_fingerprint")})
        # A legacy record has no retrieval field. `None` must FAIL CLOSED as
        # False -- never crash, and never be read as permission.
        if auth.retrieval_enabled is None:
            auth.retrieval_enabled = False
        # NO SUCH COERCION FOR THE BUDGET, DELIBERATELY. Retrieval has a safe
        # closed value (False = no memory). A loss budget does not: any number
        # invented here would be permission to risk money that nothing signed.
        # `None` is carried through unchanged so `verify()` refuses it.
        auth.path = path
        return auth


def _issue_retrieval_state() -> bool:
    """The retrieval state at ISSUE time, recorded rather than assumed."""
    from ai_retrieval.retrieval import retrieval_enabled
    return retrieval_enabled()


def issue(*, path: str, session_id: str, account_fingerprint: str, contract_id: str,
          session_date: str, now: datetime = None) -> SessionAuthorization:
    """Create and durably persist one session authorization."""
    from ai_brain import production_model as PM

    now = now or _now()
    auth = SessionAuthorization(
        session_id=session_id, account_fingerprint=account_fingerprint,
        contract_id=contract_id, session_date=session_date,
        # Resolved from production code, not from operator-supplied text.
        brain_model=PM.PRODUCTION_MODEL,
        brain_reasoning_effort=PM.reasoning_effort() or "",
        json_mode_required=True,
        brain_contract_fingerprint=PM.brain_contract_fingerprint(),
        retrieval_enabled=_issue_retrieval_state(),
        # EXPLICIT, NEVER INHERITED. Not from .env, not from the paper lane's
        # DAILY_LOSS_LIMIT_DOLLARS, not from topstep_limits -- none of those is
        # TopstepX authority. The owner's signed session loss budget.
        daily_loss_budget_usd=DAILY_LOSS_BUDGET_USD,
        # Stamped from the ruling for the session date being authorized, so the
        # record states the window that will actually be enforced.
        decision_window=window_text(session_date),
        issued_at=now.isoformat(), path=path)
    auth.authorization_fingerprint = auth.fingerprint()
    auth.save()
    return auth


# ── the session's trade missions ──────────────────────────────────────────────
@dataclass
class ProductionSessionMission:
    """Owns the session's trade allowance and its child trade missions."""
    authorization: SessionAuthorization
    store_dir: str
    trade_missions: list = field(default_factory=list)
    #: (void entry, mission) pairs excused from the allowance. Kept, not deleted.
    voided_missions: list = field(default_factory=list)

    # Counted separately: Luna speaking is not a trade.
    candidate_count: int = 0
    token_count: int = 0
    entry_attempt_count: int = 0
    filled_trade_count: int = 0
    completed_round_trip_count: int = 0

    def mission_path(self, index: int) -> str:
        return os.path.join(self.store_dir,
                            f"trade_mission_{self.authorization.session_id}_{index}.json")

    def _slot_range(self) -> range:
        """Slots to scan. Wider than the allowance because a voided mission
        keeps its slot forever -- the replacement opens beside it, never on it."""
        return range(1, self.authorization.maximum_trades
                     + RECOVERY.MAX_VOIDED_MISSIONS_PER_SESSION + 1)

    def next_mission_index(self) -> int:
        """The first unoccupied slot. Never returns an index that would
        overwrite an existing mission record, voided or not."""
        used = {i for i in self._slot_range() if os.path.exists(self.mission_path(i))}
        return (max(used) + 1) if used else 1

    def load_existing(self) -> list:
        """Reload child missions so a restart inherits the spent allowance.

        A mission named in the void ledger is set aside rather than counted --
        but only if it STILL proves it never reached the venue. The ledger is
        re-checked against the mission every load; it is never trusted on its
        own word. A void that no longer verifies silently costs a trade again.
        """
        self.trade_missions = []
        self.voided_missions = []
        voids = RECOVERY.load_voids(self.store_dir, self.authorization.session_id)
        for i in self._slot_range():
            m = MS.load(self.mission_path(i))
            if m is None:
                continue
            entry = voids.get(i)
            # The submission ledger is consulted on every load, so a void can
            # never survive against evidence that the venue saw the request.
            evidence = RECOVERY.submission_evidence_for(
                self.store_dir, self.authorization.session_id, m.mission_id,
                token_id=getattr(m, "token_id", "") or "")
            if entry is not None and RECOVERY.never_reached_venue(
                    m, submission_evidence=evidence)[0]:
                self.voided_missions.append((entry, m))
            else:
                self.trade_missions.append(m)
        # Attempts are counted honestly, voided or not: the attempt happened.
        # Only the ALLOWANCE is restored, never the history of what occurred.
        self.entry_attempt_count = sum(
            1 for m in self.trade_missions + [v[1] for v in self.voided_missions]
            if m.state in MS.ATTEMPT_SPENT_STATES or m.attempt_count > 0)
        return self.trade_missions

    @property
    def active_mission(self):
        for m in self.trade_missions:
            if m.state not in MS.TERMINAL_STATES:
                return m
        return None

    # ── four different facts, four different counters ─────────────────────────
    #
    # PROD-20260810 collapsed these into one number and got the wrong answer.
    # An attempt happened, the venue saw the request, the venue refused it, and
    # a trade occurred are not the same event, and only the last one spends the
    # doctrine's allowance of two BOT TRADES.
    def submissions_made(self) -> int:
        """Missions that got as far as consuming an attempt."""
        return len([m for m in self.trade_missions
                    if m.attempt_count > 0 or m.state in MS.ATTEMPT_SPENT_STATES])

    def venue_rejections(self) -> int:
        """Confirmed zero-fill refusals by the venue. Real events, not trades."""
        return len([m for m in self.trade_missions
                    if m.state == MS.VENUE_REJECTED_ZERO_FILL])

    def rejected_missions(self) -> list:
        return [m for m in self.trade_missions
                if m.state == MS.VENUE_REJECTED_ZERO_FILL]

    def trades_used(self) -> int:
        """Bot TRADES consumed from the authorization.

        A confirmed zero-fill venue rejection is excluded: nothing filled, no
        position existed, and the doctrine grants two trades -- not two
        submissions. The mission itself is kept, terminal and fully readable;
        only its claim on the allowance is released.

        This is NOT a free retry. `may_open_trade_mission` halts the session on
        a rejection, so restored allowance cannot become a machine-gun of
        rejected orders. Allowance and permission are separate answers.
        """
        return len([m for m in self.trade_missions
                    if m.state != MS.VENUE_REJECTED_ZERO_FILL])

    def may_open_trade_mission(self, *, positions: int, working_orders: int,
                               unknown_external: bool, in_window: bool) -> tuple:
        """Every condition that must hold before another trade may begin."""
        if self.active_mission is not None:
            return False, "a trade mission is already active; never two at once"
        # THE SAFETY BOUNDARY. A rejection frees the allowance but STOPS the
        # session. A malformed or newly-unsupported venue payload would
        # otherwise submit, be refused, keep its allowance, submit again, and
        # do that every minute until the window closed. Restoring capacity and
        # granting permission are deliberately different decisions.
        rejected = self.rejected_missions()
        if rejected:
            return False, (
                f"{len(rejected)} venue rejection(s) this session "
                f"({rejected[-1].mission_id}: "
                f"[{rejected[-1].venue_error_code}] "
                f"{rejected[-1].venue_error_message or 'reason unrecorded'}); "
                f"the trade allowance is intact but the session is HALTED "
                f"pending operator review")
        if self.trades_used() >= self.authorization.maximum_trades:
            return False, (f"session maximum of {self.authorization.maximum_trades} "
                           f"bot trades reached")
        unresolved = [m for m in self.trade_missions if m.must_reconcile()]
        if unresolved:
            return False, f"{len(unresolved)} trade mission(s) awaiting reconciliation"
        if positions:
            return False, f"account holds {positions} position(s); must be flat"
        if working_orders:
            return False, f"{working_orders} working order(s) outstanding; must be zero"
        if unknown_external:
            return False, "unknown external activity on the account"
        if not in_window:
            return False, "outside the decision window"
        return True, "clear to open a trade mission"

    def open_trade_mission(self, *, positions: int, working_orders: int,
                           unknown_external: bool, in_window: bool):
        ok, why = self.may_open_trade_mission(
            positions=positions, working_orders=working_orders,
            unknown_external=unknown_external, in_window=in_window)
        if not ok:
            raise AuthorizationRefused(f"TRADE_MISSION_REFUSED: {why}")
        # NOT trades_used() + 1. After a void those diverge, and reusing the
        # slot would overwrite the record of the failure it excused.
        index = self.next_mission_index()
        mission = MS.open_mission(
            path=self.mission_path(index),
            mission_id=f"{self.authorization.session_id}-T{index}",
            account_fingerprint=self.authorization.account_fingerprint,
            contract_id=self.authorization.contract_id,
            # Each child is bound to the session authorization, so a mission
            # cannot outlive or be transplanted onto a different authorization.
            authorization_fingerprint=self.authorization.authorization_fingerprint,
            max_attempts=MAX_ATTEMPTS_PER_TRADE_MISSION)
        self.trade_missions.append(mission)
        return mission

    def counters(self) -> dict:
        return {"candidates": self.candidate_count, "tokens": self.token_count,
                "entry_attempts": self.entry_attempt_count,
                "filled_trades": self.filled_trade_count,
                "round_trips": self.completed_round_trip_count,
                "trade_missions_used": self.trades_used(),
                "trade_missions_allowed": self.authorization.maximum_trades,
                # Reported separately so a rejection can never read as a trade.
                "submissions_made": self.submissions_made(),
                "venue_rejections": self.venue_rejections(),
                "session_halted_for_review": bool(self.rejected_missions()),
                # Surfaced so a restored allowance is never silent.
                "trade_missions_voided": len(self.voided_missions),
                "void_classes": [v[0].get("void_class") for v in self.voided_missions]}
