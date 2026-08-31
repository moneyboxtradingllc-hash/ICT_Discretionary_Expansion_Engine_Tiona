"""Liquidity-objective validation and candidate staleness.

Two doctrines live here, and both exist to stop the same failure: submitting a
bracket that described a market which has already moved on.

LIQUIDITY-OBJECTIVE DOCTRINE. A take-profit is a *named place in the market*
that price is currently drawing toward — a prior session high, an unfilled
imbalance, a protected swing. It is never a number. So an objective carries its
identity, and a target whose liquidity has already been swept or materially
delivered is not a target any more, however attractive its arithmetic looks.

STALENESS DOCTRINE. A candidate is a photograph of a moment. When the moment
changes the photograph does not become wrong in a repairable way — it becomes a
photograph of somewhere else. Therefore:

    STALE CANDIDATE -> INVALIDATE -> DESTROY BRACKET -> RETURN TO WAITING

`assess` never returns a corrected bracket, and there is deliberately no
function in this module that moves a stop or a target. Repair is not a
permitted outcome, so the code offers no way to express it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

# Objective kinds the mechanical layer may enumerate. Luna chooses WHICH of
# these is the live draw; this layer only validates that the choice is real.
OBJECTIVE_KINDS = frozenset({
    "opposing_external_liquidity", "prior_session_high", "prior_session_low",
    "session_high", "session_low", "protected_swing", "equal_highs", "equal_lows",
    "overnight_high", "overnight_low", "london_high", "london_low",
    "previous_day_high", "previous_day_low", "imbalance_completion",
    "expansion_objective", "opposing_range_boundary", "htf_draw_on_liquidity",
})

# How much of the distance to the objective may already have been travelled
# before the remaining move is not the trade that was authorized.
MATERIAL_DELIVERY_FRACTION = 0.75

STALE_REASONS = (
    "objective_swept", "objective_materially_delivered", "invalidation_touched",
    "structure_changed", "entry_missed", "risk_above_cap", "reward_below_floor",
    "snapshot_superseded", "contract_changed", "data_stale", "brain_timeout",
    "window_closed", "account_state_changed", "manual_activity",
    "narrative_changed", "objective_unknown_kind", "objective_wrong_side",
    "objective_off_tick",
)


class CandidateStale(RuntimeError):
    """The candidate no longer describes the market. Never repairable."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class LiquidityObjective:
    """A named draw on liquidity — identity first, price second."""
    identity: str                 # e.g. "prior_session_high@29910.25"
    kind: str                     # one of OBJECTIVE_KINDS
    price: float
    created_at: datetime
    source: str = "luna"

    def evidence(self) -> dict:
        return {"identity": self.identity, "kind": self.kind, "price": self.price,
                "created_at": self.created_at.isoformat(), "source": self.source}


def validate_objective(objective: LiquidityObjective, *, direction: str,
                       entry_price: float, high_since: float, low_since: float,
                       current_price: float, tick_size: float,
                       max_age: timedelta = timedelta(minutes=30),
                       now: datetime = None) -> dict:
    """Prove the objective is real, unswept, undelivered and still reachable.

    `high_since` / `low_since` are the extremes since the objective was named —
    that is how "already swept" is detected without guessing.
    """
    now = now or datetime.now(timezone.utc)
    direction = (direction or "").lower()

    if objective.kind not in OBJECTIVE_KINDS:
        raise CandidateStale("objective_unknown_kind",
                             f"{objective.kind!r} is not an authorized objective kind")

    # 2. profitable side
    if direction == "bullish" and objective.price <= entry_price:
        raise CandidateStale("objective_wrong_side",
                             f"bullish objective {objective.price} at/below entry {entry_price}")
    if direction == "bearish" and objective.price >= entry_price:
        raise CandidateStale("objective_wrong_side",
                             f"bearish objective {objective.price} at/above entry {entry_price}")

    # 9. tick grid
    if tick_size > 0:
        steps = objective.price / tick_size
        if abs(steps - round(steps)) > 1e-6:
            raise CandidateStale("objective_off_tick",
                                 f"{objective.price} is not on the {tick_size} grid")

    # 3. already swept — price reached the objective while we deliberated
    if direction == "bullish" and high_since >= objective.price:
        raise CandidateStale(
            "objective_swept",
            f"price already traded {high_since} through the objective "
            f"{objective.price}. The draw is spent; do not move it farther away.")
    if direction == "bearish" and low_since <= objective.price:
        raise CandidateStale(
            "objective_swept",
            f"price already traded {low_since} through the objective "
            f"{objective.price}. The draw is spent; do not move it farther away.")

    # 4. materially delivered — most of the move already happened
    total = abs(objective.price - entry_price)
    if total > 0:
        travelled = ((current_price - entry_price) if direction == "bullish"
                     else (entry_price - current_price))
        fraction = travelled / total
        if fraction >= MATERIAL_DELIVERY_FRACTION:
            raise CandidateStale(
                "objective_materially_delivered",
                f"{fraction:.0%} of the move to {objective.price} already delivered; "
                f"entering now buys the remainder, not the trade that was authorized")
    else:
        fraction = 0.0

    # 5. not stale by age
    age = now - objective.created_at
    if age > max_age:
        raise CandidateStale("data_stale",
                             f"objective named {age.total_seconds():.0f}s ago")

    return {"objective": objective.evidence(), "delivered_fraction": round(fraction, 4),
            "remaining_points": round(abs(objective.price - current_price), 4),
            "age_seconds": round(age.total_seconds(), 1), "valid": True}


@dataclass
class CandidateSnapshot:
    """Everything a candidate claimed, so drift can be detected rather than assumed."""
    candidate_id: str
    snapshot_id: str
    direction: str
    entry_price: float
    invalidation_price: float
    objective: LiquidityObjective
    contract_id: str
    account_fingerprint: str
    created_at: datetime
    narrative: str = ""
    account_state_digest: str = ""
    extras: dict = field(default_factory=dict)

    def fingerprint(self) -> str:
        """Identity of the THESIS, not just the order.

        A token bound to this cannot authorize a different direction, stop,
        objective or narrative — changing any of them changes the fingerprint.
        """
        import hashlib
        raw = "|".join([
            self.snapshot_id, self.direction, f"{self.entry_price}",
            f"{self.invalidation_price}", self.objective.identity,
            f"{self.objective.price}", self.contract_id, self.account_fingerprint,
            self.narrative])
        return "cand:" + hashlib.sha256(raw.encode()).hexdigest()[:16]

    def evidence(self) -> dict:
        return {"candidate_id": self.candidate_id, "candidate_fingerprint": self.fingerprint(),
                "snapshot_id": self.snapshot_id, "direction": self.direction,
                "entry_price": self.entry_price,
                "invalidation_price": self.invalidation_price,
                "objective": self.objective.evidence(),
                "contract_id": self.contract_id,
                "created_at": self.created_at.isoformat(),
                "narrative": self.narrative}


def assess(candidate: CandidateSnapshot, *, current_price: float,
           high_since: float, low_since: float, tick_size: float,
           snapshot_id: str, contract_id: str, account_fingerprint: str,
           account_state_digest: str, data_age_seconds: float,
           in_window: bool, manual_activity: bool, narrative: str = None,
           max_data_age: float = 90.0, now: datetime = None) -> dict:
    """Full pre-submit freshness verdict. Raises CandidateStale on any drift.

    Ordered so the cheapest, most decisive refusals come first — a superseded
    snapshot or a changed account makes every later check irrelevant.
    """
    now = now or datetime.now(timezone.utc)

    if not in_window:
        raise CandidateStale("window_closed", "outside the decision window")
    if contract_id != candidate.contract_id:
        raise CandidateStale("contract_changed",
                             f"active contract is {contract_id}, candidate used "
                             f"{candidate.contract_id}")
    if account_fingerprint != candidate.account_fingerprint:
        raise CandidateStale("account_state_changed", "account fingerprint differs")
    if snapshot_id != candidate.snapshot_id:
        raise CandidateStale("snapshot_superseded",
                             f"snapshot {snapshot_id} superseded {candidate.snapshot_id}")
    if manual_activity:
        raise CandidateStale(
            "manual_activity",
            "operator activity changed the account after this candidate was approved")
    if (candidate.account_state_digest
            and account_state_digest != candidate.account_state_digest):
        raise CandidateStale("account_state_changed",
                             "positions, orders or capacity changed since approval")
    if data_age_seconds is None or data_age_seconds > max_data_age:
        raise CandidateStale("data_stale", f"market data age {data_age_seconds}s")
    if narrative is not None and candidate.narrative and narrative != candidate.narrative:
        raise CandidateStale("narrative_changed",
                             "the candidate no longer belongs to the active narrative")

    # invalidation touched — the thesis already failed while we waited
    if candidate.direction == "bullish" and low_since <= candidate.invalidation_price:
        raise CandidateStale("invalidation_touched",
                             f"price traded {low_since} to/through the invalidation "
                             f"{candidate.invalidation_price}")
    if candidate.direction == "bearish" and high_since >= candidate.invalidation_price:
        raise CandidateStale("invalidation_touched",
                             f"price traded {high_since} to/through the invalidation "
                             f"{candidate.invalidation_price}")

    objective = validate_objective(
        candidate.objective, direction=candidate.direction,
        entry_price=candidate.entry_price, high_since=high_since, low_since=low_since,
        current_price=current_price, tick_size=tick_size, now=now)

    return {"fresh": True, "candidate": candidate.evidence(),
            "objective_validation": objective,
            "assessed_at": now.isoformat()}
