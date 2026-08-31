"""COMBINE-RISK-250 — Trading Combine risk doctrine and signed bracket geometry.

Two jobs, kept in one place because they are the same decision seen twice:

  1. Convert a Brain-authored structural invalidation into a bracket the venue
     will accept, with the SIGN proven rather than assumed.
  2. Refuse the trade when one contract of that geometry risks more than the
     Combine allows.

THE DIRECTION OF THE ARROW MATTERS. Risk is derived FROM the thesis; the thesis
is never derived from the risk budget:

    Brain-authored structural invalidation
            -> one-contract MNQ risk
            -> risk <= $250  ? eligible : REJECT

Nothing in this module widens, tightens or nudges an invalidation to make a
trade fit the budget. A trade that does not fit is refused, because moving the
invalidation would mean trading a level the Brain never chose — the thesis and
the stop would no longer be the same object.

SIGN CONVENTION — CORRECTED BY THE VENUE, 2026-08-05. The published example
shows unsigned ticks (`{"ticks": 10, "type": 4}`) and I read that as "distance,
side implied by the entry". The live gateway disagrees, in as many words:

    errorCode=2 "Invalid stop loss ticks (40).
                 Ticks should be less than zero when longing."

Bracket ticks are SIGNED, relative to the entry:

    LONG  (buy):  stopLossBracket.ticks NEGATIVE, takeProfitBracket.ticks POSITIVE
    SHORT (sell): stopLossBracket.ticks POSITIVE, takeProfitBracket.ticks NEGATIVE

The economic levels are unchanged by this — only their representation. The
wrong-side checks below still run first, because a sign convention cannot
rescue an invalidation that was on the wrong side of price to begin with.

    LONG  (side=buy=0):  stop BELOW entry, target ABOVE entry
    SHORT (side=sell=1): stop ABOVE entry, target BELOW entry
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from broker.topstepx_client import ORDER_SIDE, ORDER_TYPE, TopstepXContract

# Operator-declared Combine doctrine (2026-08-04). Not tunable at runtime.
# This is the FUTURE PRODUCTION ceiling, not today's limit.
MAX_RISK_PER_TRADE_USD = 250.00
SMOKE_MAX_CONTRACTS = 1
COMPOUNDING = False

# FIRST-DAY SMOKE LAW (operator authorization, 2026-08-05). The production cap
# is not active for the first execution smoke: proving the venue path does not
# require risking a production-sized loss. Both caps apply and the stricter one
# governs, so a future change to either can only ever tighten today's limit.
SMOKE_MAX_RISK_USD = 20.00
SMOKE_MAX_STOP_POINTS = 10.00          # NQ points; 40 MNQ ticks at 0.25
MNQ_DOLLARS_PER_POINT = 2.00           # 1 MNQ = $2.00 per NQ point
# RR-FLOOR-1.0 (2026-08-08). A SECOND authoritative floor on the same live path:
# the producer qualifies a candidate, then this gate sizes it. Leaving this at
# 1.5 while the producer moved to 1.0 would have killed every 1.0-1.49 trade at
# `reward_below_gate` -- the ruling would have looked applied and changed
# nothing. One doctrine, both gates.
MIN_REWARD_TO_RISK = 1.0               # floor when no stricter gate is authoritative

# ── PRODUCTION STOP DOCTRINE (operator, 2026-08-05) ───────────────────────────
# Two DISTINCT concepts. Neither is a stop distance — both are eligibility
# bounds. The stop itself is always the exact structural invalidation.
#
#   <= 35.0   normal qualification path
#   > 35.0 and <= 50.0   extended-volatility lane; the SETUP must justify the
#                        width with current evidence, not "the market is busy"
#   > 50.0    reject the setup outright
#
# Before this mission the resolved production ceiling was the SMOKE value
# (10.0 points) because build_bracket defaulted to it, and size was hard-capped
# at 1 contract. Both were smoke artifacts standing in for production doctrine.
#
# RISK-DOCTRINE-MIGRATION (operator, 2026-08-20). Ceiling 40.0 -> 50.0 and
# per-trade risk $250 -> $350.
#
# On 2026-08-20 at 11:03 Luna held a bearish thesis whose structural stop -- the
# 29470.25 protected high, measured from 29429.50 -- was 40.75 points. Three
# ticks over the ceiling, so the setup died on eligibility rather than on
# judgement. NQ can genuinely require that much structural room.
#
# 50.0 IS A VETO CEILING, NOT A TARGET. The preferred range is unchanged at
# 35.0, the stop is still exactly the structural invalidation, and nothing may
# widen a stop to consume budget. $350 likewise buys CONTRACTS at a structural
# stop; it never buys a wider one.
#
# This migration is NOT a repair for that day's graded discretionary miss. At
# the 11:04 actionable scan the protected-high stop was 31.00 points (29470.25
# from 29439.25) -- already legal under the old 40.0 ceiling and already
# fundable under the old $250 cap, which sized it at 3 MNQ. The ceiling change
# addresses 11:03 alone.
#
# (A separate 29.50-point figure belongs to the EXEC-PRICE-FRESHNESS-1 replay:
# 29470.25 from the 11:02 candle open at 29440.75. Different scan, different
# defect, and not this ruling's occasion.)
PREFERRED_MAX_STOP_POINTS = 35.0
ABSOLUTE_MAX_STOP_POINTS = 50.0
PRODUCTION_MAX_CONTRACTS = 15
PRODUCTION_MAX_RISK_USD = 350.00

NORMAL_STOP_RANGE = "NORMAL_STOP_RANGE"
EXTENDED_VOLATILITY_STOP_RANGE = "EXTENDED_VOLATILITY_STOP_RANGE"
STOP_DISTANCE_REJECTED = "STOP_DISTANCE_REJECTED"

# ── COST MODEL: MEASURED FIXED COSTS vs SLIPPAGE RESERVE ──────────────────────
# These are two different KINDS of number and are kept apart deliberately.
#
# FIXED ROUND-TRIP COSTS are MEASURED, from the live Mission C and F fills on
# this exact account and contract (Trade.fees and Trade.commissions, both sides):
#     fees        $0.72 per MNQ contract round trip
#     commissions $0.50 per MNQ contract round trip
#     total       $1.22 per MNQ contract round trip
#
# SLIPPAGE IS NOT MEASURED HERE. It cannot honestly be inferred from gross or net
# P&L, or from entry/exit prices — those confound slippage with market movement.
# Measuring it requires a captured executable quote at submit compared with the
# fill. Until that capture exists, this is an explicitly CONSERVATIVE RESERVE,
# labelled as such everywhere it is reported, and configurable.
FIXED_ROUND_TRIP_FEES_PER_CONTRACT = 0.72
FIXED_ROUND_TRIP_COMMISSIONS_PER_CONTRACT = 0.50
MEASURED_FIXED_ROUND_TRIP_TOTAL = 1.22
FIXED_COST_SOURCE = "measured: live Mission C/F Trade.fees + Trade.commissions, 2026-08-05"

# PROVISIONAL reserve, raised to 2 ticks per side (operator, 2026-08-05) until
# quote-to-fill evidence exists. 2 entry + 2 exit = 4 ticks = $2.00 per MNQ
# round trip. It is deliberately conservative: sizing down on an unmeasured
# assumption is recoverable, sizing up on one is not.
SLIPPAGE_RESERVE_TICKS_PER_SIDE = 2.0
SLIPPAGE_SOURCE = ("provisional conservative reserve, NOT measured; "
                   "awaiting quote-to-fill capture")


def friction_per_contract(contract: TopstepXContract,
                          slippage_reserve_ticks_per_side: float = SLIPPAGE_RESERVE_TICKS_PER_SIDE,
                          fixed_fees: float = FIXED_ROUND_TRIP_FEES_PER_CONTRACT,
                          fixed_commissions: float = FIXED_ROUND_TRIP_COMMISSIONS_PER_CONTRACT) -> dict:
    """Round-trip cost of ONE contract in dollars, with provenance attached.

    `fixed` is measured; `slippage_reserve` is not. The caller can see which is
    which, so a future quote-to-fill measurement can replace the reserve without
    disturbing the measured part.
    """
    fixed = float(fixed_fees) + float(fixed_commissions)
    slip = 2.0 * float(slippage_reserve_ticks_per_side) * float(contract.tick_value or 0.0)
    return {"fixed_round_trip": round(fixed, 4),
            "fees_round_trip": float(fixed_fees),
            "commissions_round_trip": float(fixed_commissions),
            "fixed_source": FIXED_COST_SOURCE,
            "slippage_reserve": round(slip, 4),
            "slippage_reserve_ticks_per_side": float(slippage_reserve_ticks_per_side),
            "slippage_source": SLIPPAGE_SOURCE,
            "slippage_is_measured": False,
            "total": round(fixed + slip, 4)}


def classify_stop_distance(stop_points: float,
                           preferred: float = PREFERRED_MAX_STOP_POINTS,
                           absolute: float = ABSOLUTE_MAX_STOP_POINTS) -> str:
    """Which lane a structural stop falls in. Classification only — never a cap."""
    d = float(stop_points)
    if d <= float(preferred):
        return NORMAL_STOP_RANGE
    if d <= float(absolute):
        return EXTENDED_VOLATILITY_STOP_RANGE
    return STOP_DISTANCE_REJECTED


def extended_volatility_supported(evidence: dict) -> tuple:
    """Does CURRENT evidence justify a stop wider than the preferred range?

    Reads the existing volatility/market-state authority — it does not model
    volatility itself. A generally busy market is not a licence for every setup
    to use the ceiling: the specific structure must need the width.
    """
    e = evidence or {}
    vol = str(e.get("volatility_state") or "").lower()
    expansion = str(e.get("expansion_state") or "").lower()
    elevated = vol in ("expansion", "elevated", "high", "expanding")
    expanding = expansion in ("expanding", "expansion", "mature_expansion")
    structural = bool(e.get("structural_level_identity"))
    if not (elevated or expanding):
        return False, ("current volatility state does not support a stop beyond the "
                       f"{PREFERRED_MAX_STOP_POINTS:g}-point preferred range")
    if not structural:
        return False, ("no named structural level justifies the extended width; "
                       "width must come from structure, not from volatility alone")
    return True, None


def size_for_risk(stop_points: float, contract: TopstepXContract, *,
                  max_risk_usd: float = PRODUCTION_MAX_RISK_USD,
                  max_contracts: int = PRODUCTION_MAX_CONTRACTS,
                  slippage_reserve_ticks_per_side: float = SLIPPAGE_RESERVE_TICKS_PER_SIDE) -> dict:
    """Largest whole MNQ quantity whose ALL-IN risk stays within the cap.

        contracts x (stop_points x $2.00 + friction_per_contract) <= max_risk

    Friction is inside the cap, never removed to make a trade fit. A stop wide
    enough that even one contract breaches the cap yields quantity 0, which the
    caller must treat as a rejection.
    """
    stop_points = float(stop_points)
    if stop_points <= 0:
        raise RiskRejection("zero_distance_stop", "stop distance must be positive")
    fr = friction_per_contract(contract, slippage_reserve_ticks_per_side)
    per_contract = stop_points * MNQ_DOLLARS_PER_POINT + fr["total"]
    qty = int(float(max_risk_usd) // per_contract) if per_contract > 0 else 0
    qty = max(0, min(qty, int(max_contracts)))
    return {"contracts": qty,
            "gross_stop_risk_per_contract": round(stop_points * MNQ_DOLLARS_PER_POINT, 2),
            "fixed_costs_per_contract": fr["fixed_round_trip"],
            "slippage_reserve_per_contract": fr["slippage_reserve"],
            "friction_per_contract": fr["total"], "friction_detail": fr,
            "all_in_risk_per_contract": round(per_contract, 2),
            "all_in_planned_risk": round(qty * per_contract, 2),
            "max_risk_usd": float(max_risk_usd), "max_contracts": int(max_contracts),
            "fits": qty >= 1}


def effective_max_risk_usd(production_cap: float = MAX_RISK_PER_TRADE_USD,
                           smoke_cap: float = SMOKE_MAX_RISK_USD) -> float:
    """min(production, smoke). The stricter cap always wins."""
    return min(float(production_cap), float(smoke_cap))


class RiskRejection(RuntimeError):
    """The trade is refused. Carries `reason` for evidence, never a suggestion
    to move the stop — there is no adjustment that makes a rejected trade
    acceptable."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


# ── the one bracket sign convention ───────────────────────────────────────────
#
# Topstep reads bracket legs as SIGNED offsets from the entry, and refuses the
# order outright when the sign is wrong:
#
#     errorCode 2 — "Invalid stop loss ticks (40). Ticks should be less than
#                    zero when longing."   (live, 2026-08-10)
#
# The production geometry always signed them correctly; the smoke harness sent
# unsigned ticks and was rejected before it could test anything else. These two
# functions exist so there is exactly ONE definition of the convention for both
# paths to read. A second, independently-written copy is how the two drift.
def sign_stop_ticks(direction: str, stop_ticks: int) -> int:
    """Venue-signed stop ticks: negative for a long, positive for a short."""
    return -int(stop_ticks) if direction == "bullish" else int(stop_ticks)


def sign_target_ticks(direction: str, target_ticks: int) -> int:
    """Venue-signed target ticks: positive for a long, negative for a short."""
    return int(target_ticks) if direction == "bullish" else -int(target_ticks)


@dataclass(frozen=True)
class BracketGeometry:
    direction: str            # "bullish" | "bearish"
    side: str                 # "buy" | "sell"
    side_code: int            # 0 bid / 1 ask
    entry_price: float
    stop_price: float
    target_price: float
    stop_points: float        # positive distance
    target_points: float      # positive distance
    stop_ticks: int
    target_ticks: int
    size: int
    risk_usd: float
    reward_usd: float
    #: The ceilings that ACTUALLY governed this geometry. Unset means nobody
    #: told us, and `evidence()` then says smoke rather than inventing a claim.
    governing_max_risk_usd: float = None
    governing_max_stop_points: float = None
    governing_lane: str = ""

    def governed_by(self, *, max_risk_usd: float, max_stop_points: float,
                    lane: str) -> "BracketGeometry":
        """A COPY carrying the ceilings this geometry was actually judged by.

        This dataclass is frozen on purpose -- a geometry that could be edited
        after sizing is a geometry the risk gate cannot vouch for -- so this
        returns a new instance rather than mutating in place.
        """
        return dataclasses.replace(self,
                                   governing_max_risk_usd=float(max_risk_usd),
                                   governing_max_stop_points=float(max_stop_points),
                                   governing_lane=lane)

    def signed_stop_ticks(self) -> int:
        """Venue-signed stop ticks: negative for a long, positive for a short."""
        return sign_stop_ticks(self.direction, self.stop_ticks)

    def signed_target_ticks(self) -> int:
        """Venue-signed target ticks: positive for a long, negative for a short."""
        return sign_target_ticks(self.direction, self.target_ticks)

    def stop_is_correct_side(self) -> bool:
        return (self.stop_price < self.entry_price if self.direction == "bullish"
                else self.stop_price > self.entry_price)

    def target_is_correct_side(self) -> bool:
        return (self.target_price > self.entry_price if self.direction == "bullish"
                else self.target_price < self.entry_price)

    def as_order_payload(self, account_id: int, contract_id: str,
                         custom_tag: str = None) -> dict:
        """Exactly the /api/Order/place body, so evidence shows what was sent."""
        return {
            "accountId": int(account_id),
            "contractId": contract_id,
            "type": ORDER_TYPE["market"],
            "side": self.side_code,
            "size": int(self.size),
            "limitPrice": None, "stopPrice": None, "trailPrice": None,
            "customTag": custom_tag,
            "stopLossBracket": {"ticks": self.signed_stop_ticks(),
                                "type": ORDER_TYPE["stop"]},
            "takeProfitBracket": {"ticks": self.signed_target_ticks(),
                                  "type": ORDER_TYPE["limit"]},
        }

    def evidence(self) -> dict:
        return {"direction": self.direction, "side": self.side, "side_code": self.side_code,
                "entry_price": self.entry_price, "stop_price": self.stop_price,
                "target_price": self.target_price,
                "stop_points": self.stop_points, "target_points": self.target_points,
                "stop_ticks": self.stop_ticks, "target_ticks": self.target_ticks,
                "signed_stop_ticks": self.signed_stop_ticks(),
                "signed_target_ticks": self.signed_target_ticks(),
                "size": self.size, "risk_usd": self.risk_usd, "reward_usd": self.reward_usd,
                "stop_correct_side": self.stop_is_correct_side(),
                "target_correct_side": self.target_is_correct_side(),
                "reward_to_risk": (round(self.reward_usd / self.risk_usd, 3)
                                   if self.risk_usd else None),
                # Both caps, so evidence can never imply the production ceiling
                # governed a smoke trade it did not govern.
                #
                # PROD-20260811-V13: this block did the EXACT OPPOSITE of what
                # that comment promised. `effective_max_risk_usd()` returns
                # min(production, smoke) with no mode check, and max_stop_points
                # was the literal SMOKE_MAX_STOP_POINTS -- so every production
                # submission recorded effective_cap_usd=20.0 / max_stop=10.0
                # while enforcement correctly used 250.0 / 40.0. A $112.50 trade
                # sat in the record above a $20 ceiling it was never judged by.
                #
                # The governing values now come from whoever actually judged the
                # trade. Unset still reports the smoke defaults, because a
                # geometry nobody claimed is a smoke geometry.
                "production_cap_usd": MAX_RISK_PER_TRADE_USD,
                "smoke_cap_usd": SMOKE_MAX_RISK_USD,
                "effective_cap_usd": (self.governing_max_risk_usd
                                      if self.governing_max_risk_usd is not None
                                      else effective_max_risk_usd()),
                "max_stop_points": (self.governing_max_stop_points
                                    if self.governing_max_stop_points is not None
                                    else SMOKE_MAX_STOP_POINTS),
                "governing_lane": self.governing_lane or "smoke",
                "governing_caps_declared": self.governing_max_risk_usd is not None}


def ticks_between(a: float, b: float, contract: TopstepXContract,
                  round_away: bool = False) -> int:
    """Whole ticks between two prices.

    `round_away=True` rounds UP (away from entry) — the stop convention under
    the first-day smoke law. A stop rounded TOWARD entry sits inside the
    structural level, so it can be taken out while the Luna thesis is still
    valid; that is a losing trade the thesis never called for. Paying up to one
    extra tick to stay outside the level is the correct trade, and the $20 cap
    is then applied to the rounded distance, so the widening can never smuggle
    risk past the gate.

    `round_away=False` rounds DOWN — used for the target, where overstating
    reward would flatter the reward-to-risk gate.
    """
    if contract.tick_size <= 0:
        raise RiskRejection("invalid_tick_metadata",
                            f"contract {contract.id} reports tickSize={contract.tick_size}")
    import math
    raw = abs(a - b) / contract.tick_size
    ticks = math.ceil(raw - 1e-9) if round_away else int(raw + 1e-9)
    return max(1, ticks)


def risk_for(ticks: int, size: int, contract: TopstepXContract) -> float:
    """Dollar risk of `ticks` against `size` contracts at this contract's tick value."""
    if contract.tick_value <= 0:
        raise RiskRejection("invalid_tick_metadata",
                            f"contract {contract.id} reports tickValue={contract.tick_value}")
    return round(ticks * contract.tick_value * size, 2)


def build_production_bracket(*, direction: str, entry_price: float,
                             invalidation_level, target_price,
                             contract: TopstepXContract, evidence: dict = None,
                             max_risk_usd: float = PRODUCTION_MAX_RISK_USD,
                             max_contracts: int = PRODUCTION_MAX_CONTRACTS,
                             min_reward_to_risk: float = MIN_REWARD_TO_RISK) -> dict:
    """The production path: exact structural stop, adaptive size, 40-pt ceiling.

    Deliberately a SEPARATE entry point from `build_bracket`. The smoke caps
    live on that function's defaults, and a production caller that forgot an
    argument would silently inherit a 10-point ceiling and a 1-contract cap.
    Here the production doctrine is the only thing reachable.

    Returns the geometry plus its sizing and classification. Raises
    RiskRejection — it never adjusts a level to make a setup fit.
    """
    geo = build_bracket(direction=direction, entry_price=entry_price,
                        invalidation_level=invalidation_level,
                        target_price=target_price, contract=contract, size=1,
                        # EXPLICIT production cap. Passing None here would fall
                        # through to effective_max_risk_usd(), which returns the
                        # $20 SMOKE cap — the exact leak this mission removes.
                        max_risk_usd=max_risk_usd,
                        max_stop_points=ABSOLUTE_MAX_STOP_POINTS,
                        min_reward_to_risk=min_reward_to_risk,
                        max_contracts=max_contracts)

    lane = classify_stop_distance(geo.stop_points)
    if lane == STOP_DISTANCE_REJECTED:
        raise RiskRejection(
            "stop_distance_above_absolute_ceiling",
            f"structural stop {geo.stop_points:g} pts exceeds the "
            f"{ABSOLUTE_MAX_STOP_POINTS:g}-point absolute ceiling. The invalidation is "
            f"the thesis and is not adjustable — the setup is rejected, not resized.")
    if lane == EXTENDED_VOLATILITY_STOP_RANGE:
        ok, why = extended_volatility_supported(evidence)
        if not ok:
            raise RiskRejection("extended_volatility_unsupported", why)

    sizing = size_for_risk(geo.stop_points, contract, max_risk_usd=max_risk_usd,
                           max_contracts=max_contracts)
    if not sizing["fits"]:
        raise RiskRejection(
            "risk_above_cap",
            f"even one MNQ risks ${sizing['all_in_risk_per_contract']:,.2f} all-in "
            f"(stop {geo.stop_points:g} pts + friction), above the "
            f"${max_risk_usd:,.2f} cap. Friction is not removed to make it fit.")

    sized = build_bracket(direction=direction, entry_price=entry_price,
                          invalidation_level=invalidation_level,
                          target_price=target_price, contract=contract,
                          size=sizing["contracts"], max_risk_usd=max_risk_usd,
                          max_stop_points=ABSOLUTE_MAX_STOP_POINTS,
                          min_reward_to_risk=min_reward_to_risk,
                          max_contracts=max_contracts)
    return {"geometry": sized, "stop_range": lane, "sizing": sizing,
            "reward_to_risk": round(sized.reward_usd / sized.risk_usd, 3),
            "preferred_max_stop_points": PREFERRED_MAX_STOP_POINTS,
            "absolute_max_stop_points": ABSOLUTE_MAX_STOP_POINTS}


def build_bracket(*, direction: str, entry_price: float, invalidation_level,
                  target_price, contract: TopstepXContract, size: int = 1,
                  max_risk_usd: float = None,
                  max_stop_points: float = SMOKE_MAX_STOP_POINTS,
                  min_reward_to_risk: float = MIN_REWARD_TO_RISK,
                  max_contracts: int = SMOKE_MAX_CONTRACTS) -> BracketGeometry:
    """Turn a Brain thesis into a venue bracket, or refuse it. Never adjusts.

    `invalidation_level` is the Brain's structural invalidation — the price at
    which its thesis is wrong. It becomes the stop unmodified.
    """
    # Default to the STRICTER of the two caps rather than the production one.
    # A caller that forgets to pass a cap gets today's $20 smoke limit, not a
    # $250 production limit — the safe direction for a default to fail.
    if max_risk_usd is None:
        max_risk_usd = effective_max_risk_usd()

    direction = (direction or "").strip().lower()
    if direction not in ("bullish", "bearish"):
        raise RiskRejection("non_directional_thesis",
                            f"direction={direction!r} cannot author an entry")
    if size < 1:
        raise RiskRejection("invalid_size", f"size={size!r}")
    if size > int(max_contracts):
        raise RiskRejection("size_above_cap",
                            f"size={size} exceeds the {int(max_contracts)}-contract cap")
    try:
        entry = float(entry_price)
        stop = float(invalidation_level)
    except (TypeError, ValueError):
        raise RiskRejection("missing_invalidation",
                            "a directional thesis must name a numeric invalidation level") from None
    if entry <= 0:
        raise RiskRejection("stale_or_invalid_price", f"entry_price={entry_price!r}")

    if stop == entry:
        raise RiskRejection("zero_distance_stop",
                            "invalidation equals entry; there is no risk to size")

    side = "buy" if direction == "bullish" else "sell"
    stop_below = stop < entry
    if direction == "bullish" and not stop_below:
        raise RiskRejection("wrong_side_stop",
                            f"bullish thesis with invalidation {stop} at/above entry {entry}")
    if direction == "bearish" and stop_below:
        raise RiskRejection("wrong_side_stop",
                            f"bearish thesis with invalidation {stop} at/below entry {entry}")

    if target_price is None:
        raise RiskRejection("missing_target", "no draw/target price supplied")
    try:
        target = float(target_price)
    except (TypeError, ValueError):
        raise RiskRejection("missing_target", f"target_price={target_price!r}") from None
    if direction == "bullish" and target <= entry:
        raise RiskRejection("wrong_side_target",
                            f"bullish target {target} at/below entry {entry}")
    if direction == "bearish" and target >= entry:
        raise RiskRejection("wrong_side_target",
                            f"bearish target {target} at/above entry {entry}")

    # Stop rounds AWAY from entry (never inside the structural level); target
    # rounds TOWARD entry so reward is never overstated to the R gate.
    stop_ticks = ticks_between(entry, stop, contract, round_away=True)
    target_ticks = ticks_between(entry, target, contract, round_away=False)
    risk = risk_for(stop_ticks, size, contract)
    reward = risk_for(target_ticks, size, contract)

    stop_points = stop_ticks * contract.tick_size
    if max_stop_points is not None and stop_points > float(max_stop_points):
        raise RiskRejection(
            "stop_distance_above_cap",
            # PROD-20260810: this said "smoke limit" while reporting the
            # PRODUCTION 40-point ceiling, so a live refusal read as a smoke
            # artefact in every forensic report. The number was always right;
            # the noun was left over from when this path was smoke-only.
            f"stop distance {stop_points:g} points exceeds the "
            f"{float(max_stop_points):g}-point "
            f"{'absolute production stop ceiling' if float(max_stop_points) >= PREFERRED_MAX_STOP_POINTS else 'smoke stop ceiling'}"
            f". The invalidation is the Brain's and is not adjustable — "
            f"wait for a candidate whose structure is closer.")

    if risk > max_risk_usd:
        raise RiskRejection(
            "risk_above_cap",
            f"one-contract risk ${risk:,.2f} exceeds the ${max_risk_usd:,.2f} cap "
            f"({stop_ticks} ticks x ${contract.tick_value}/tick). The invalidation is the "
            f"Brain's and is not adjustable — the trade is refused instead.")

    if min_reward_to_risk is not None and risk > 0:
        rr = reward / risk
        if rr < float(min_reward_to_risk):
            raise RiskRejection(
                "reward_below_gate",
                f"reward-to-risk {rr:.2f} is below the {float(min_reward_to_risk):.2f} gate. "
                f"Neither the stop nor the target may be moved to manufacture it — "
                f"the candidate is refused.")

    geo = BracketGeometry(
        direction=direction, side=side, side_code=ORDER_SIDE[side],
        entry_price=entry, stop_price=stop, target_price=target,
        stop_points=round(abs(entry - stop), 6), target_points=round(abs(target - entry), 6),
        stop_ticks=stop_ticks, target_ticks=target_ticks, size=size,
        risk_usd=risk, reward_usd=reward)

    # Belt and braces: the geometry must agree with itself before it is returned.
    if not geo.stop_is_correct_side():
        raise RiskRejection("wrong_side_stop", "post-construction sign check failed")
    if not geo.target_is_correct_side():
        raise RiskRejection("wrong_side_target", "post-construction sign check failed")
    return geo
