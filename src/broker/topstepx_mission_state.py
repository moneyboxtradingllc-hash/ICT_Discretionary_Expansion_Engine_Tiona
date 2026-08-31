"""Crash-safe one-attempt authorization for the Combine smoke.

The in-memory `_entry_attempted` latch survives a clean run and nothing else.
A process that dies between "order sent" and "response received" would restart
believing no attempt had been made — and the operator has stepped away, so no
human memory backstops it. This module makes the single-attempt allowance
durable on disk.

THE ORDERING THAT MATTERS. Consumption is persisted BEFORE the request can
leave, never after:

    gates pass -> token validated -> persist ATTEMPT_CONSUMED -> verify it
    landed -> burn token -> submit exactly once

Persisting after the call would leave the exact window this exists to close: a
crash mid-request, then a restart that believes it still has an attempt. The
cost of the strict order is that a process which dies between persistence and
submission has spent its attempt on nothing. That is the correct trade — a
wasted authorization is recoverable by asking the operator; a duplicate live
entry is not.

FAILING CLOSED. Unreadable or half-written state is `STATE_UNCERTAIN`, never
`UNARMED`. A corrupt file is the one case where guessing "fresh mission" would
authorize exactly the thing the file exists to prevent.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone

UNARMED = "UNARMED"
ARMED = "ARMED"
CANDIDATE_APPROVED = "CANDIDATE_APPROVED"
TOKEN_MINTED = "TOKEN_MINTED"
ATTEMPT_CONSUMED = "ATTEMPT_CONSUMED"
SUBMIT_UNKNOWN = "SUBMIT_UNKNOWN"

#: The venue answered with an order id. PROD-20260811-V13 had no word for this
#: and no way to write one: the ONLY `self.order_id =` in this class lived in
#: `venue_rejected_zero_fill`, the FAILURE path, so a successful submission was
#: structurally unable to record the order it had just placed. Order 3391019204
#: filled and stopped out for -$138.30 while the mission still read
#: ATTEMPT_CONSUMED / order_id=null / token_spent=false.
VENUE_ACKNOWLEDGED = "VENUE_ACKNOWLEDGED"
POSITION_OPEN = "POSITION_OPEN"
EXIT_PENDING_RECONCILIATION = "EXIT_PENDING_RECONCILIATION"
COMPLETE = "COMPLETE"
TERMINAL_REFUSAL = "TERMINAL_REFUSAL"
WINDOW_CLOSED = "WINDOW_CLOSED"
STATE_UNCERTAIN = "STATE_UNCERTAIN"

#: The request reached Topstep, Topstep positively refused it, and the venue
#: confirms zero fill, no position and no working order.
#:
#: PROD-20260810 had no word for this. Order 3385801549 was rejected with
#: fillVolume 0, and the mission sat in ATTEMPT_CONSUMED forever -- a phantom
#: active mission that refused every later scan with "a trade mission is
#: already active". It is terminal, and it is emphatically NOT
#: INFRASTRUCTURE_ABORT: the venue saw the request. What it is not, is a trade.
VENUE_REJECTED_ZERO_FILL = "VENUE_REJECTED_ZERO_FILL"

# From any of these, the attempt allowance is gone. A restart may reconcile,
# monitor and clean up — it may never create a new entry.
#
# VENUE_REJECTED_ZERO_FILL belongs here: the ATTEMPT genuinely happened and its
# history is preserved. Whether it consumes a TRADE is a different question,
# answered by `ProductionSessionMission.trades_used`, because an attempt, a
# submission, a rejection and a trade are four different facts.
ATTEMPT_SPENT_STATES = frozenset({
    ATTEMPT_CONSUMED, SUBMIT_UNKNOWN, VENUE_ACKNOWLEDGED, POSITION_OPEN,
    EXIT_PENDING_RECONCILIATION, COMPLETE, VENUE_REJECTED_ZERO_FILL,
})
TERMINAL_STATES = frozenset({COMPLETE, TERMINAL_REFUSAL, WINDOW_CLOSED,
                             VENUE_REJECTED_ZERO_FILL})

#: MONOTONIC LADDER. Venue reality only ever moves forward into the durable
#: record. A reconciler that observes a coarse window may advance SEVERAL rungs
#: in one pass -- today's whole trade was born and stopped out inside a single
#: 60-second scan interval -- but it may never walk one back, because "I did not
#: see the position this tick" is not evidence the position never existed.
#:
#: SUBMIT_UNKNOWN and STATE_UNCERTAIN are deliberately OFF the ladder: they are
#: statements about our knowledge, not about the trade, and may be entered from
#: anywhere.
LIFECYCLE_ORDER = (UNARMED, ARMED, ATTEMPT_CONSUMED, VENUE_ACKNOWLEDGED,
                   POSITION_OPEN, EXIT_PENDING_RECONCILIATION, COMPLETE)
_RANK = {state: i for i, state in enumerate(LIFECYCLE_ORDER)}


def lifecycle_rank(state: str):
    """Position on the ladder, or None for the off-ladder states."""
    return _RANK.get(state)


class MissionStateError(RuntimeError):
    """The durable record refuses the requested action."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _merge_ids(known, seen) -> list:
    """Union of durable order identities, order-preserving.

    TOPSTEP-PROTECTIVE-DISCOVERY-AND-LINEAGE-1. `protective_order_ids` used to
    be assigned outright on every observation, so the record only ever held what
    the LAST tick happened to see. Identity is not a live reading; it is the
    permanent answer to "which orders did this mission create", and a mission
    that forgets it cannot attribute its own exit.
    """
    out = list(known or [])
    have = {str(o) for o in out}
    for oid in seen or []:
        if oid is not None and str(oid) not in have:
            out.append(oid)
            have.add(str(oid))
    return out


@dataclass
class MissionState:
    """One smoke mission, bound to account + contract + authorization."""

    mission_id: str
    account_fingerprint: str
    contract_id: str
    authorization_fingerprint: str
    path: str
    max_attempts: int = 1
    attempt_count: int = 0
    state: str = UNARMED
    candidate_fingerprint: str = ""
    token_id: str = ""
    token_spent: bool = False
    order_id: object = None
    position_state: str = "flat"
    last_transition: str = ""
    transition_at: str = ""
    completion_state: str = ""
    #: The venue's own words when it refused this order. Kept ON the mission so
    #: a rejection can never again be reconstructible only from a lost log line.
    venue_error_code: object = None
    venue_error_message: str = ""
    #: Provenance carried ON the mission, so a later reader never has to join
    #: across files to learn which session and which approval produced this
    #: trade. V13 filed its flight record under the RETIRED session id and an
    #: empty authorization fingerprint, and the join that was supposed to prove
    #: the venue had seen the order returned zero rows.
    session_id: str = ""
    #: Venue-observed execution facts. Absent means unobserved, never zero.
    submitted_at: str = ""
    acknowledged_at: str = ""
    filled_quantity: object = None
    fill_price: object = None
    protective_order_ids: list = field(default_factory=list)
    exit_type: str = ""
    exit_price: object = None
    exit_order_id: object = None
    flat_confirmed_at: str = ""
    history: list = field(default_factory=list)

    # ── durability ────────────────────────────────────────────────────────────
    def as_dict(self) -> dict:
        return {"mission_id": self.mission_id,
                "account_fingerprint": self.account_fingerprint,
                "contract_id": self.contract_id,
                "authorization_fingerprint": self.authorization_fingerprint,
                "max_attempts": self.max_attempts,
                "attempt_count": self.attempt_count,
                "state": self.state,
                "candidate_fingerprint": self.candidate_fingerprint,
                "token_id": self.token_id, "token_spent": self.token_spent,
                "order_id": self.order_id, "position_state": self.position_state,
                "last_transition": self.last_transition,
                "transition_at": self.transition_at,
                "completion_state": self.completion_state,
                "venue_error_code": self.venue_error_code,
                "venue_error_message": self.venue_error_message,
                "session_id": self.session_id,
                "submitted_at": self.submitted_at,
                "acknowledged_at": self.acknowledged_at,
                "filled_quantity": self.filled_quantity,
                "fill_price": self.fill_price,
                "protective_order_ids": list(self.protective_order_ids),
                "exit_type": self.exit_type,
                "exit_price": self.exit_price,
                "exit_order_id": self.exit_order_id,
                "flat_confirmed_at": self.flat_confirmed_at,
                "history": list(self.history)}

    def save(self) -> str:
        """Atomic replace. A torn write must never read as a fresh mission."""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        directory = os.path.dirname(self.path)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".mission-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.as_dict(), fh, indent=2, default=str)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)          # atomic on POSIX and Windows
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return self.path

    def transition(self, new_state: str, note: str = "") -> str:
        self.history.append({"from": self.state, "to": new_state,
                             "at": _now(), "note": note})
        self.state = new_state
        self.last_transition = f"{note or new_state}"
        self.transition_at = _now()
        return self.save()

    # ── the irreversible step ─────────────────────────────────────────────────
    def consume_attempt(self, *, candidate_fingerprint: str, token_id: str) -> dict:
        """Persist ATTEMPT_CONSUMED and PROVE it landed, before any submit.

        Re-reads the file after writing: an attempt that is only in memory has
        not been consumed, and returning success without verifying would
        reintroduce the crash window.
        """
        if self.attempt_count >= self.max_attempts:
            raise MissionStateError(
                f"attempt allowance exhausted ({self.attempt_count}/{self.max_attempts})")
        if self.state in ATTEMPT_SPENT_STATES:
            raise MissionStateError(f"attempt already spent (state={self.state})")
        self.attempt_count += 1
        self.candidate_fingerprint = candidate_fingerprint
        self.token_id = token_id
        self.transition(ATTEMPT_CONSUMED, "attempt persisted before submission")

        verify = load(self.path)
        if verify is None or verify.state != ATTEMPT_CONSUMED or verify.attempt_count < 1:
            raise MissionStateError(
                "could not verify ATTEMPT_CONSUMED on disk; refusing to submit")
        return {"attempt_count": self.attempt_count, "state": self.state,
                "verified": True}

    # ── venue reality becoming durable reality ────────────────────────────────
    def _advance(self, new_state: str, note: str, *, evidence: str) -> str:
        """Move FORWARD along the lifecycle ladder, never backward.

        `evidence` is not decoration: every rung of this ladder is a claim about
        what the venue did, and a claim with no stated source is how a local
        guess turns into durable history.
        """
        here, there = lifecycle_rank(self.state), lifecycle_rank(new_state)
        if there is None:
            raise MissionStateError(f"{new_state} is not on the lifecycle ladder")
        if self.state in TERMINAL_STATES:
            raise MissionStateError(
                f"mission is terminal ({self.state}); it cannot advance to {new_state}")
        if here is not None and there < here:
            raise MissionStateError(
                f"refusing to walk the lifecycle backward: {self.state} -> {new_state}")
        if here is not None and there == here:
            return self.path                       # already there; idempotent
        return self.transition(new_state, f"{note} [{evidence}]")

    def _verify(self, expect: str, what: str) -> None:
        """Re-read from disk. In-memory state is not a durable record."""
        verify = load(self.path)
        if verify is None or verify.state != expect:
            raise MissionStateError(f"could not verify {what} on disk")

    def record_venue_acknowledgement(self, *, venue_order_id, session_id: str = "",
                                     authorization_fingerprint: str = "",
                                     submitted_at: str = "",
                                     evidence: str = "venue ack") -> dict:
        """The irreversible venue boundary, written the instant the venue answers.

        THE DEFECT THIS CLOSES. V13 submitted, the venue answered with order
        3391019204, the order filled and stopped out -- and the mission still
        read ATTEMPT_CONSUMED / order_id=null / token_spent=false, because no
        method existed that could write those fields on a SUCCESSFUL path. The
        only `self.order_id =` in this class was in `venue_rejected_zero_fill`.

        `token_spent` is set HERE, at the venue boundary, and not one step
        later. Once Topstep may have the request, the authority behind it is
        gone -- whether or not anything downstream succeeds. Tying it to a fill,
        or to a later reconciliation, would mean a crash in between leaves a
        record claiming the authority is still available.

        Raises rather than returning False. A caller that cannot make this write
        durable must fail closed: the order is live and unrecorded, which is the
        one situation where continuing is worse than halting.
        """
        if venue_order_id is None:
            raise MissionStateError(
                "a venue acknowledgement must name the order the venue returned")
        if self.state not in (ATTEMPT_CONSUMED, SUBMIT_UNKNOWN, VENUE_ACKNOWLEDGED):
            raise MissionStateError(
                f"cannot acknowledge from {self.state}; the attempt must be "
                "consumed before the venue can have seen anything")
        if (self.order_id is not None
                and str(self.order_id) != str(venue_order_id)):
            raise MissionStateError(
                f"mission already carries order {self.order_id}; refusing to "
                f"overwrite it with {venue_order_id}")
        self.order_id = venue_order_id
        self.token_spent = True
        self.acknowledged_at = _now()
        if submitted_at:
            self.submitted_at = submitted_at
        if session_id:
            self.session_id = session_id
        if authorization_fingerprint:
            self.authorization_fingerprint = authorization_fingerprint
        self._advance(VENUE_ACKNOWLEDGED, f"venue acknowledged order {venue_order_id}",
                      evidence=evidence)
        self._verify(VENUE_ACKNOWLEDGED, "VENUE_ACKNOWLEDGED")
        verify = load(self.path)
        if str(verify.order_id) != str(venue_order_id) or not verify.token_spent:
            raise MissionStateError(
                "acknowledgement did not persist order id and token_spent")
        return {"state": self.state, "order_id": self.order_id,
                "token_spent": self.token_spent, "verified": True}

    def observe_position_open(self, *, filled_quantity, fill_price=None,
                              protective_order_ids=None,
                              evidence: str = "venue position") -> dict:
        """A fill the VENUE reports. Never inferred from local intent."""
        if not filled_quantity:
            raise MissionStateError(
                "a position cannot be opened on a zero or absent fill quantity")
        self.filled_quantity = filled_quantity
        if fill_price is not None:
            self.fill_price = fill_price
        if protective_order_ids:
            self.protective_order_ids = _merge_ids(self.protective_order_ids,
                                                   protective_order_ids)
        self.position_state = "open"
        self._advance(POSITION_OPEN,
                      f"venue reports {filled_quantity} filled", evidence=evidence)
        self._verify(POSITION_OPEN, "POSITION_OPEN")
        return {"state": self.state, "filled_quantity": filled_quantity}

    def observe_protection(self, *, protective_order_ids,
                           evidence: str = "venue working orders") -> dict:
        """Working protective orders seen at the venue. Not a state change --
        protection is a FACT ABOUT an open position, not a rung of its own.

        ACCUMULATES, never replaces. A stop that filled and a target the venue
        then cancelled are both gone from the next tick's view, and overwriting
        with that view would erase the only two identities capable of saying
        which leg closed the trade. Leaving active discovery is a change of
        STATE, not a retraction of EXISTENCE, so terminal children keep their
        place in the mission's lineage.
        """
        self.protective_order_ids = _merge_ids(self.protective_order_ids,
                                               protective_order_ids)
        self.last_transition = f"protection observed [{evidence}]"
        self.transition_at = _now()
        return {"protective_order_ids": self.protective_order_ids,
                "path": self.save()}

    def observe_exit(self, *, exit_type: str, exit_price=None, exit_order_id=None,
                     evidence: str = "venue fill") -> dict:
        """The position is closing/closed at the venue; flat not yet proven."""
        self.exit_type = exit_type or ""
        self.exit_price = exit_price
        self.exit_order_id = exit_order_id
        self._advance(EXIT_PENDING_RECONCILIATION, f"exit observed ({exit_type})",
                      evidence=evidence)
        self._verify(EXIT_PENDING_RECONCILIATION, "EXIT_PENDING_RECONCILIATION")
        return {"state": self.state, "exit_type": self.exit_type}

    def reconcile_flat(self, *, positions: int = None, working_orders: int = None,
                       completion_state: str = "",
                       evidence: str = "venue flat") -> dict:
        """TERMINAL. Only the venue's own counts may end a mission.

        Mirrors `venue_rejected_zero_fill`: passing None means the venue was not
        asked, which is not the same as it answering zero.
        """
        if positions is None or working_orders is None:
            raise MissionStateError(
                "the venue must be asked for positions and working orders "
                "before a mission may be closed")
        if positions or working_orders:
            raise MissionStateError(
                f"venue is not flat ({positions} position(s), "
                f"{working_orders} working order(s)); mission stays open")
        if self.order_id is None:
            raise MissionStateError(
                "refusing to complete a mission that never recorded a venue "
                "order id; reconcile the submission ledger first")
        self.position_state = "flat"
        self.flat_confirmed_at = _now()
        self.completion_state = completion_state or self.exit_type or COMPLETE
        self._advance(COMPLETE, "flat reconciled at the venue", evidence=evidence)
        self._verify(COMPLETE, "COMPLETE")
        return {"state": self.state, "completion_state": self.completion_state,
                "order_id": self.order_id, "verified": True}

    # ── queries ───────────────────────────────────────────────────────────────
    def may_attempt_entry(self) -> tuple:
        if self.state == STATE_UNCERTAIN:
            return False, "durable state is uncertain; reconcile the venue first"
        if self.state in TERMINAL_STATES:
            return False, f"mission is terminal ({self.state})"
        if self.state in ATTEMPT_SPENT_STATES:
            return False, f"attempt already spent ({self.state})"
        if self.attempt_count >= self.max_attempts:
            return False, "attempt allowance exhausted"
        if self.state != ARMED:
            return False, f"mission is {self.state}, not ARMED"
        return True, None

    def must_reconcile(self) -> bool:
        return self.state in (ATTEMPT_CONSUMED, SUBMIT_UNKNOWN, VENUE_ACKNOWLEDGED,
                              POSITION_OPEN, EXIT_PENDING_RECONCILIATION,
                              STATE_UNCERTAIN)

    # ── the venue said no ─────────────────────────────────────────────────────
    def venue_rejected_zero_fill(self, *, venue_order_id, error_code=None,
                                 error_message: str = "", positions: int = None,
                                 working_orders: int = None) -> dict:
        """Close the mission on a POSITIVELY CONFIRMED zero-fill rejection.

        Refuses unless the venue was actually asked and answered flat. "I did
        not see a position" is not the same as "the venue reports no position",
        and only the second may end a mission.

        The rejection identity is written INTO the mission so a later reader
        never has to reconstruct it: order id, code and message all persist.
        """
        if positions is None or working_orders is None:
            raise MissionStateError(
                "the venue must be asked for positions and working orders "
                "before a mission may be closed as rejected")
        if positions or working_orders:
            raise MissionStateError(
                f"venue is not flat ({positions} position(s), "
                f"{working_orders} working order(s)); not a zero-fill rejection")
        if venue_order_id is None:
            raise MissionStateError(
                "a zero-fill rejection must name the venue order it refers to")
        self.order_id = venue_order_id
        self.completion_state = VENUE_REJECTED_ZERO_FILL
        self.venue_error_code = error_code
        self.venue_error_message = error_message
        self.transition(VENUE_REJECTED_ZERO_FILL,
                        f"venue rejected order {venue_order_id} with zero fill"
                        + (f": [{error_code}] {error_message}" if error_message else ""))
        verify = load(self.path)
        if verify is None or verify.state != VENUE_REJECTED_ZERO_FILL:
            raise MissionStateError(
                "could not verify VENUE_REJECTED_ZERO_FILL on disk")
        return {"state": self.state, "venue_order_id": venue_order_id,
                "error_code": error_code, "error_message": error_message,
                "verified": True}


def load(path: str) -> "MissionState | None":
    """Read durable state. Corruption yields STATE_UNCERTAIN, never UNARMED."""
    if not os.path.exists(path):
        return None
    try:
        data = json.load(open(path, encoding="utf-8"))
    except Exception:  # noqa: BLE001 — truncated, partial or unparseable
        st = MissionState(mission_id="unknown", account_fingerprint="",
                          contract_id="", authorization_fingerprint="", path=path)
        st.state = STATE_UNCERTAIN
        st.last_transition = "unreadable durable state"
        return st
    try:
        st = MissionState(
            mission_id=data["mission_id"],
            account_fingerprint=data["account_fingerprint"],
            contract_id=data["contract_id"],
            authorization_fingerprint=data.get("authorization_fingerprint", ""),
            path=path,
            max_attempts=int(data.get("max_attempts", 1)),
            attempt_count=int(data.get("attempt_count", 0)),
            state=str(data.get("state") or STATE_UNCERTAIN),
            candidate_fingerprint=data.get("candidate_fingerprint", "") or "",
            token_id=data.get("token_id", "") or "",
            token_spent=bool(data.get("token_spent")),
            order_id=data.get("order_id"),
            position_state=data.get("position_state", "flat"),
            last_transition=data.get("last_transition", ""),
            transition_at=data.get("transition_at", ""),
            completion_state=data.get("completion_state", ""),
            venue_error_code=data.get("venue_error_code"),
            venue_error_message=data.get("venue_error_message", "") or "",
            session_id=data.get("session_id", "") or "",
            submitted_at=data.get("submitted_at", "") or "",
            acknowledged_at=data.get("acknowledged_at", "") or "",
            filled_quantity=data.get("filled_quantity"),
            fill_price=data.get("fill_price"),
            protective_order_ids=list(data.get("protective_order_ids") or []),
            exit_type=data.get("exit_type", "") or "",
            exit_price=data.get("exit_price"),
            exit_order_id=data.get("exit_order_id"),
            flat_confirmed_at=data.get("flat_confirmed_at", "") or "",
            history=list(data.get("history") or []))
    except (KeyError, TypeError, ValueError):
        st = MissionState(mission_id="unknown", account_fingerprint="",
                          contract_id="", authorization_fingerprint="", path=path)
        st.state = STATE_UNCERTAIN
        st.last_transition = "durable state missing required fields"
        return st
    return st


def open_mission(*, path: str, mission_id: str, account_fingerprint: str,
                 contract_id: str, authorization_fingerprint: str,
                 max_attempts: int = 1) -> MissionState:
    """Load an existing mission or arm a new one. Identity is checked, not assumed.

    A record for a different account, contract or mission is refused rather than
    overwritten — silently replacing it would discard exactly the evidence that
    an attempt was already spent somewhere.
    """
    existing = load(path)
    if existing is None:
        st = MissionState(mission_id=mission_id, account_fingerprint=account_fingerprint,
                          contract_id=contract_id, max_attempts=max_attempts,
                          authorization_fingerprint=authorization_fingerprint, path=path)
        st.transition(ARMED, "mission armed")
        return st

    if existing.state == STATE_UNCERTAIN:
        return existing                       # caller must reconcile; never reset

    for field_name, expected, actual in (
            ("account fingerprint", account_fingerprint, existing.account_fingerprint),
            ("contract", contract_id, existing.contract_id),
            ("mission id", mission_id, existing.mission_id)):
        if expected and actual and expected != actual:
            existing.state = STATE_UNCERTAIN
            existing.last_transition = f"{field_name} mismatch on load"
            return existing
    return existing
