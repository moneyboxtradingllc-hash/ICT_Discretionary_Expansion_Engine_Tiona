"""Topstep account limits — the trailing drawdown this bot did not model.

The risk model here was built for a self-funded NinjaTrader account, where the
only ceilings are the ones we choose: a per-trade budget and a daily realized
loss cap. A Topstep account adds a limit nothing in this codebase understood, and
it is the one that actually ends accounts.

THE MAXIMUM LOSS LIMIT (MLL)

Two halves that behave differently, and conflating them is the whole danger:

  RISES on END-OF-DAY balance only. Intraday unrealized profit does NOT move it.
       A trade that is +$2,000 open has not raised the threshold by a cent.
  BREACHES in REAL TIME on net P&L including UNREALIZED. An open loser can
       breach it mid-session and Topstep liquidates immediately.

So the threshold is slow to rise and instant to enforce. A model that trailed on
intraday equity would report far more room than exists; one that only checked
realized P&L would report a breach that had already happened.

It also LOCKS PERMANENTLY once it reaches the starting balance — after that the
account has a fixed floor and stops being a trailing product at all.

    threshold = min(starting_balance, highest_end_of_day_balance) - mll_amount
    breached  = (balance + unrealized) <= threshold

THE DAILY LOSS LIMIT is a softer thing: measured from the prior day's close, it
auto-liquidates for the session but is not a rule violation. Worth respecting
well before it triggers, because a forced flatten is not an exit the strategy
chose.

`highest_eod_balance` is DURABLE state. If it resets on restart the threshold
falls back with it and the bot believes it has room it does not have — the same
persistence defect that left this project's swing tracker rebuilding itself every
scan. It is persisted, and `load_state` refuses to silently invent a starting
value.

Figures below are Topstep's published Trading Combine / Express Funded numbers
(help.topstep.com, read 2026-07-28). They are DEFAULTS, not gospel — an operator
must confirm them against their own account, and every one is overridable.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Optional

__all__ = [
    "TopstepSpec", "TopstepState", "TopstepVerdict", "ACCOUNT_SPECS",
    "spec_for", "mll_threshold", "evaluate", "max_contracts_within_mll",
    "load_state", "save_state",
]

DEFAULT_STATE_PATH = Path("data/topstep/account_state.json")


@dataclass(frozen=True)
class TopstepSpec:
    """One account's published limits."""

    label: str
    starting_balance: float
    max_loss_limit: float          # the trailing MLL, e.g. 4500 on a 150K
    daily_loss_limit: float        # soft: liquidates the session, not a violation
    profit_target: float
    max_contracts: int             # minis; micros are typically 10x this

    def mll_floor(self) -> float:
        """The lowest the threshold can ever be — day one, before any profit."""
        return self.starting_balance - self.max_loss_limit


# help.topstep.com, read 2026-07-28. Confirm against the live account.
ACCOUNT_SPECS = {
    "50K":  TopstepSpec("50K", 50_000.0, 2_000.0, 1_000.0, 3_000.0, 5),
    "100K": TopstepSpec("100K", 100_000.0, 3_000.0, 2_000.0, 6_000.0, 10),
    "150K": TopstepSpec("150K", 150_000.0, 4_500.0, 3_000.0, 9_000.0, 15),
}


def spec_for(label: str) -> TopstepSpec:
    key = (label or "").strip().upper().replace("$", "").replace(",", "")
    if key.endswith("000") and len(key) > 3:      # "150000" -> "150K"
        key = f"{int(key) // 1000}K"
    if key not in ACCOUNT_SPECS:
        raise KeyError(f"unknown Topstep account size {label!r}; "
                       f"known: {', '.join(sorted(ACCOUNT_SPECS))}")
    return ACCOUNT_SPECS[key]


@dataclass
class TopstepState:
    """Durable per-account state. `highest_eod_balance` must survive a restart."""

    account_label: str
    highest_eod_balance: float
    prior_day_close: float
    current_day: str = ""

    def roll_day(self, closing_balance: float, new_day: str) -> "TopstepState":
        """End of session: the threshold may rise, and today's close becomes the
        baseline the daily limit is measured from tomorrow."""
        return replace(
            self,
            highest_eod_balance=max(self.highest_eod_balance, float(closing_balance)),
            prior_day_close=float(closing_balance),
            current_day=new_day,
        )


@dataclass(frozen=True)
class TopstepVerdict:
    """Per-component, never a single opaque boolean."""

    ok: bool
    mll_threshold: float
    mll_room: float                # net equity above the threshold
    mll_breached: bool
    mll_locked: bool               # threshold has reached the starting balance
    daily_room: float              # left before the daily limit liquidates
    daily_breached: bool
    reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return asdict(self)


def mll_threshold(spec: TopstepSpec, highest_eod_balance: float) -> float:
    """The live floor. Never above the starting balance — it locks there."""
    trailed = float(highest_eod_balance) - spec.max_loss_limit
    return min(trailed, spec.starting_balance)


def evaluate(spec: TopstepSpec, state: TopstepState, *, balance: float,
             unrealized: float = 0.0) -> TopstepVerdict:
    """Where the account stands right now.

    `unrealized` is included deliberately: Topstep enforces the MLL on net P&L in
    real time, so an open loser counts against it even though an open winner
    cannot raise it.
    """
    threshold = mll_threshold(spec, state.highest_eod_balance)
    net_equity = float(balance) + float(unrealized)
    mll_room = net_equity - threshold
    mll_breached = mll_room <= 0.0
    locked = threshold >= spec.starting_balance

    day_pnl = float(balance) - float(state.prior_day_close)
    daily_room = spec.daily_loss_limit + day_pnl      # positive == still allowed
    daily_breached = daily_room <= 0.0

    reasons = []
    if mll_breached:
        reasons.append(
            f"MLL BREACHED: net equity {net_equity:,.2f} at or below threshold "
            f"{threshold:,.2f}. Topstep closes the account on this.")
    if daily_breached:
        reasons.append(
            f"daily loss limit hit: {day_pnl:,.2f} against a {spec.daily_loss_limit:,.2f} "
            f"limit. Session liquidates; not a violation.")
    return TopstepVerdict(
        ok=not (mll_breached or daily_breached),
        mll_threshold=threshold, mll_room=mll_room, mll_breached=mll_breached,
        mll_locked=locked, daily_room=daily_room, daily_breached=daily_breached,
        reasons=tuple(reasons),
    )


#: Fraction of the REMAINING buffer a single trade's worst case may consume.
#: 0.125 is not invented — it is the operator's own practice: a $250 stop on a
#: 50K Combine, whose Maximum Loss Limit is $2,000. The notional account size is
#: irrelevant to that decision; a "50K Combine" is a $2,000 risk account, and
#: 250/2000 = 1/8. Eight consecutive full stops to the floor.
#: It scales by construction — the same fraction on a 150K's $4,500 buffer is
#: $562.50 — so the rule survives an account upgrade without being re-derived.
DEFAULT_BUFFER_FRACTION = 0.125


def max_contracts_within_mll(spec: TopstepSpec, state: TopstepState, *,
                             balance: float, stop_points: float,
                             point_value: float, unrealized: float = 0.0,
                             buffer_fraction: float = DEFAULT_BUFFER_FRACTION) -> int:
    """Largest size whose FULL STOP still leaves the account alive.

    This is the pre-trade question the bot never asked. Percent-of-equity sizing
    is blind to a trailing floor because it reads the notional balance: 0.35% of
    a 50K Combine is $175, which sounds conservative against $50,000 and is 8.75%
    of the $2,000 that actually exists.

    `buffer_fraction` reserves part of the remaining room rather than betting all
    of it on one trade. Returns 0 when even one contract would risk more than
    that — a refusal, not an error.
    """
    if stop_points <= 0 or point_value <= 0:
        return 0
    verdict = evaluate(spec, state, balance=balance, unrealized=unrealized)
    if verdict.mll_breached:
        return 0
    allowed_loss = verdict.mll_room * max(0.0, min(1.0, buffer_fraction))
    risk_per_contract = stop_points * point_value
    return max(0, int(allowed_loss // risk_per_contract))


# ── durable state ─────────────────────────────────────────────────────────────
def _path(path: Optional[Path] = None) -> Path:
    return Path(path or os.getenv("TOPSTEP_STATE_PATH", "") or DEFAULT_STATE_PATH)


def save_state(state: TopstepState, path: Optional[Path] = None) -> None:
    p = _path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(state), indent=1), encoding="utf-8")


def load_state(spec: TopstepSpec, path: Optional[Path] = None) -> TopstepState:
    """Read durable state, or start a fresh account at its published balance.

    A missing file is treated as day one — highest_eod_balance = starting balance,
    which is the STRICTEST possible threshold. Guessing high here would raise the
    floor and refuse valid trades; guessing low would lower it and hide a breach.
    Day one is the only safe assumption when nothing is known.
    """
    p = _path(path)
    if not p.exists():
        return TopstepState(account_label=spec.label,
                            highest_eod_balance=spec.starting_balance,
                            prior_day_close=spec.starting_balance)
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("account_label") != spec.label:
        raise ValueError(
            f"state file {p} belongs to a {data.get('account_label')!r} account but "
            f"the configured account is {spec.label!r}. Refusing to carry one "
            f"account's drawdown history into another.")
    return TopstepState(
        account_label=data["account_label"],
        highest_eod_balance=float(data["highest_eod_balance"]),
        prior_day_close=float(data["prior_day_close"]),
        current_day=data.get("current_day", ""),
    )
