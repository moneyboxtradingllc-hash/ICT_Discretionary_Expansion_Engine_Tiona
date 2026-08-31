"""SESSION-PO3 AUTHORITY — the causal Power-of-Three lifecycle above the evidence.

LUNA-SESSION-PO3-AUTHORITY-1 (2026-08-29).

WHAT WAS PROVEN BROKEN. `po3_engine` answers "what does THIS scan's texture look
like on THIS timeframe" and answers it four times independently. That is evidence,
and it is good evidence. It is not a phase. It has no range, no birth, no
excursion, no resolution and no vote in whether a trade may exist — which is why
on 2026-08-25 Luna filled two practice entries at 14:48 and 14:49 UTC while
`po3.5m`, `po3.3m` and `po3.1m` all read `accumulation`.

WHAT THIS MODULE ADDS, AND WHAT IT DELIBERATELY DOES NOT. It adds ONE canonical
session lifecycle and the entry authority that belongs to it. It computes no new
market primitive: every input is an existing published fact — the per-timeframe
PO3 phases, `manipulation_detector`'s classification and direction, the settled
1m series, and the standing directional authority from `structure_hierarchy`.
`po3_engine` is untouched and remains the evidence producer.

THE LAW IT ENFORCES.

    ACCUMULATION            -> NO NEW ENTRY
    FIRST EXCURSION         -> NO CHASE; distribution vs manipulation UNRESOLVED
    FAILED EXCURSION
      + opposite ownership  -> MANIPULATION_CONFIRMED; reversal preferred
    SUSTAINED ESCAPE
      + compatible ownership-> DISTRIBUTION_ACTIVE
    RETURN TO ROTATION      -> REACCUMULATION

There is no clock in this file. Accumulation lasts exactly as long as the market
keeps it, and a genuine opening drive is never banned: a balance that was never
ESTABLISHED cannot be departed from, so a market that opens delivering produces
`UNKNOWN` and keeps full entry authority.

DETERMINISM, AND WHY THE PHASE IS RE-DERIVED RATHER THAN REMEMBERED. Live scans
arrive on a ~79s wall clock; a restart rebuild replays the tape bar by bar. Any
phase carried as scan-to-scan memory would therefore differ between the two and
"restart recovery" would be a fiction. So the phase is a PURE function of the
settled 1m series plus this scan's evidence. Carried state holds provenance only
(when a phase was first observed, and the transition log) and can never change
which phase is reported. That is the whole reason `derive()` is a module-level
function and `SessionPo3Authority` is a thin provenance wrapper around it.
"""
from __future__ import annotations

from structure import po3_config as cfg

SCHEMA = "session_po3.v1"

# ── The canonical states ──────────────────────────────────────────────────────
UNKNOWN = "UNKNOWN"
ACCUMULATION_FORMING = "ACCUMULATION_FORMING"
ACCUMULATION_ESTABLISHED = "ACCUMULATION_ESTABLISHED"
EXCURSION_UNRESOLVED = "EXCURSION_UNRESOLVED"
MANIPULATION_CONFIRMED = "MANIPULATION_CONFIRMED"
DISTRIBUTION_ACTIVE = "DISTRIBUTION_ACTIVE"
REACCUMULATION = "REACCUMULATION"

STATES = (UNKNOWN, ACCUMULATION_FORMING, ACCUMULATION_ESTABLISHED,
          EXCURSION_UNRESOLVED, MANIPULATION_CONFIRMED, DISTRIBUTION_ACTIVE,
          REACCUMULATION)

#: THE ENTRY LAW. Read by `entry_permission()` and by nothing else, so there is
#: exactly one place where "may Luna open a new position in this phase" is
#: answered. UNKNOWN is permissive on purpose: absence of a proven balance is not
#: evidence of one, and banning trade on absence would ban every opening drive.
_NEW_ENTRY_ALLOWED = {
    UNKNOWN:                  True,
    ACCUMULATION_FORMING:     False,
    ACCUMULATION_ESTABLISHED: False,
    EXCURSION_UNRESOLVED:     False,
    MANIPULATION_CONFIRMED:   True,
    DISTRIBUTION_ACTIVE:      True,
    REACCUMULATION:           False,
}

_BLOCK_REASON = {
    ACCUMULATION_FORMING: "session accumulation is forming — the range is not yet "
                          "resolved and no new entry is authorized",
    ACCUMULATION_ESTABLISHED: "session accumulation is established — no new entry "
                              "until the range resolves",
    EXCURSION_UNRESOLVED: "price has left the accumulation range but neither "
                          "manipulation nor distribution is proven — no chase",
    REACCUMULATION: "price returned to two-sided rotation — re-accumulation is "
                    "unresolved and no new entry is authorized",
}

#: Which playbook families the phase PREFERS. A preference is not a permission:
#: mechanical sufficiency, geometry and risk law still decide, and an empty
#: opportunity set produces no trade (S7).
_PREFERRED = {
    MANIPULATION_CONFIRMED: ("liquidity_sweep_reversal",
                             "manipulation_to_distribution",
                             "failed_breakout_reversal"),
    DISTRIBUTION_ACTIVE:    ("trend_continuation", "manipulation_to_distribution"),
}

#: Timeframes whose PO3 texture may corroborate that a balance is accumulation.
#: 15m is deliberately absent: it is context for the session, not the session.
_BALANCE_TFS = ("5m", "3m", "1m")
#: Minimum corroborating timeframes.
_BALANCE_MIN_TFS = 2

#: Settled 1m bars a candidate balance must survive before it is ESTABLISHED.
#: Reuses the window VECTOR-3 already sized for "enough tape to mean something".
MIN_RANGE_BARS = cfg.SIG_WINDOW          # 12

#: Bars that unconditionally SEED a candidate balance. A range is a region;
#: it cannot be inferred from one candle, and seeding from one made the very
#: next bar look like a departure on ordinary two-sided tape.
SEED_BARS = 3

#: Below this a balance is too young to be called even FORMING. Without it a
#: three-bar pause inside a delivery leg would block new entries, which is the
#: opposite failure to the one this unit exists to fix: an authority that bans
#: everything is not an authority, it is an outage.
MIN_FORMING_BARS = MIN_RANGE_BARS // 2

#: Consecutive settled closes beyond a boundary before an escape counts as
#: ACCEPTANCE. One close is a poke; one displacement is one candle. Neither
#: proves the market repriced (doctrine §7: no single close, no hindsight).
ACCEPTANCE_BARS = 3

#: Timeframes consulted for the manipulation confluence verdict, HTF first so a
#: 15m confirmation outranks a 1m one when both exist.
_MANIP_TFS = ("15m", "5m", "3m", "1m")
#: Timeframes whose MSS may stand as "opposite reversal evidence is forming".
_MSS_TFS = ("5m", "3m", "1m")

_BULL, _BEAR = "bullish", "bearish"
_OPPOSITE = {_BULL: _BEAR, _BEAR: _BULL}


# ── small readers ─────────────────────────────────────────────────────────────

def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _ts(bar) -> str:
    return str((bar or {}).get("timestamp") or (bar or {}).get("t") or "")


def _floor() -> float:
    """A departure must clear the same absolute magnitude floor VECTOR-3 already
    requires of displacement on 1m. A tick past a boundary is not an excursion."""
    return cfg.f_disp("1m")


def entry_permission(phase: str) -> tuple:
    """(allowed, reason). THE single answer to 'may a new entry exist here'."""
    allowed = _NEW_ENTRY_ALLOWED.get(phase, True)
    return allowed, (None if allowed
                     else _BLOCK_REASON.get(phase, f"session PO3 phase {phase}"))


# ── evidence readers over the existing engines ────────────────────────────────

def _accumulation_evidence(po3: dict) -> dict:
    """The EXISTING per-TF PO3 texture, read as corroboration only.

    It may witness that a balance is accumulation. It may NOT declare that one
    has resolved — that is what made accumulation non-load-bearing in the first
    place, and the segmentation below owns resolution.
    """
    po3 = po3 or {}
    tfs = [tf for tf in _BALANCE_TFS
           if str(((po3.get(tf) or {}).get("phase") or "")).lower() == "accumulation"]
    return {"timeframes": tfs, "count": len(tfs),
            "sufficient": len(tfs) >= _BALANCE_MIN_TFS,
            "alignment": (po3 or {}).get("alignment")}


def _manipulation_verdict(liquidity: dict) -> dict:
    """The confluence detector's OWN classification and direction.

    Both were being computed and thrown away: `po3_engine` consumes the numeric
    `score` and nothing consumed `classification` or `direction` at all, so
    `manipulation_possible` and `manipulation_confirmed` were indistinguishable
    downstream, and PO3's manipulation_direction was derived from a different
    field (`sweep_direction`) that is frequently absent while the detector holds
    a direction. This reads what the detector actually said.
    """
    liquidity = liquidity or {}
    best = {"classification": "none", "direction": None, "source_tf": None,
            "score": 0, "conflicted": False, "directions_by_tf": {}}
    seen = {}
    for tf in _MANIP_TFS:
        block = ((liquidity.get(tf) or {}).get("manipulation") or {})
        if not isinstance(block, dict) or not block:
            continue
        cls = str(block.get("classification") or "none")
        d = block.get("direction")
        if d in (_BULL, _BEAR):
            seen[tf] = d
        if (cls == "manipulation_confirmed"
                and best["classification"] != "manipulation_confirmed"):
            best.update(classification=cls, direction=d, source_tf=tf,
                        score=int(block.get("score") or 0))
        elif cls == "manipulation_possible" and best["classification"] == "none":
            best.update(classification=cls, direction=d, source_tf=tf,
                        score=int(block.get("score") or 0))
    best["directions_by_tf"] = seen
    # S16 — two timeframes may report confirmed manipulation in OPPOSITE
    # directions on the same scan (measured live 2026-08-25: 15m bearish, 1m
    # bullish). The canonical phase must not manufacture certainty out of that;
    # it is recorded as conflicted and the direction test below cannot pass on a
    # conflicted read.
    best["conflicted"] = len(set(seen.values())) > 1
    return best


def _ownership(authority: dict) -> dict:
    """Directional ownership, from the repo's standing authority.

    `htf_authority` is the existing answer to "who owns direction": liquidity
    draw first, PO3 delivery second, structure never. PO3 does not write it and
    must not — that is the circular-writer rule.
    """
    a = authority or {}
    bias = str(a.get("bias") or "neutral").lower()
    intact = bool(a.get("intact"))
    return {"direction": bias if (intact and bias in (_BULL, _BEAR)) else None,
            "bias": bias, "intact": intact, "source": a.get("source")}


def _mss_present(structure: dict) -> list:
    structure = structure or {}
    return [tf for tf in _MSS_TFS if (structure.get(tf) or {}).get("mss")]


# ── the segmentation: where a range comes from ────────────────────────────────

def _segment(bars: list, floor: float) -> dict:
    """Split the settled 1m tape into balances and the excursions that ended them.

    One pass, causal: no bar is ever judged using a later one. A balance is
    SEEDED by `SEED_BARS` bars (a region cannot be inferred from a single
    candle), then absorbs every bar whose CLOSE stays inside it, widening to that
    bar's high and low. So a new local extreme that closes back inside is a range
    EXTENSION, never a departure (S2/S3). A close beyond a boundary by at least
    the magnitude floor ENDS that balance; the next bar seeds the next one.

    Returns the segment list and, separately, the most recent segment whose
    balance actually reached establishment — the only kind of balance a market
    can be said to have departed from.
    """
    segments = []
    if not bars:
        return {"segments": [], "anchor": None}

    usable = [b for b in bars
              if _num(b.get("high")) is not None and _num(b.get("low")) is not None
              and _num(b.get("close")) is not None]

    def seed(idx):
        window = usable[idx:idx + SEED_BARS]
        if not window:
            return None
        return {"start": idx,
                "high": max(_num(c["high"]) for c in window),
                "low": min(_num(c["low"]) for c in window),
                "birth": _ts(window[0]),
                "last_extension": _ts(window[-1]),
                "bars": len(window)}

    idx = 0
    while idx < len(usable):
        bal = seed(idx)
        if bal is None:
            break
        i = idx + bal["bars"]
        departed = None
        while i < len(usable):
            bar = usable[i]
            hi, lo, close = _num(bar["high"]), _num(bar["low"]), _num(bar["close"])
            if close > bal["high"] + floor or close < bal["low"] - floor:
                departed = i
                break
            if hi > bal["high"] or lo < bal["low"]:
                bal["high"] = max(bal["high"], hi)
                bal["low"] = min(bal["low"], lo)
                bal["last_extension"] = _ts(bar)
            bal["bars"] += 1
            i += 1

        if departed is None:
            segments.append({"balance": bal, "excursion": None})
            break

        bar = usable[departed]
        side = "above" if _num(bar["close"]) > bal["high"] else "below"
        exc = {"side": side,
               "direction": _BULL if side == "above" else _BEAR,
               "boundary": bal["high"] if side == "above" else bal["low"],
               "birth": _ts(bar),
               "peak": _num(bar["high"]) if side == "above" else _num(bar["low"]),
               "bars_outside": 0, "consecutive_outside": 0,
               "reentered": False, "reentry_at": None, "bars_since": 0}
        for c in usable[departed:]:
            chi, clo, cc = _num(c["high"]), _num(c["low"]), _num(c["close"])
            exc["bars_since"] += 1
            if side == "above":
                exc["peak"] = max(exc["peak"], chi)
                outside = cc > bal["high"]
            else:
                exc["peak"] = min(exc["peak"], clo)
                outside = cc < bal["low"]
            if outside:
                exc["bars_outside"] += 1
                exc["consecutive_outside"] += 1
            else:
                exc["consecutive_outside"] = 0
                if not exc["reentered"] and bal["low"] <= cc <= bal["high"]:
                    exc["reentered"] = True
                    exc["reentry_at"] = _ts(c)
        segments.append({"balance": bal, "excursion": exc})
        idx = departed

    # THE ANCHOR. Only a balance that was ESTABLISHED can be departed from, so
    # the session's controlling balance is the most recent established one. When
    # none exists the market never built a session range and PO3 says so rather
    # than inventing one.
    anchor = None
    for seg in reversed(segments):
        if seg["balance"]["bars"] >= MIN_RANGE_BARS:
            anchor = seg
            break
    if anchor is None and segments:
        anchor = segments[-1]
    return {"segments": segments, "anchor": anchor}


# ── the lifecycle ─────────────────────────────────────────────────────────────

def derive(*, settled_1m: list, po3: dict = None, liquidity: dict = None,
           structure: dict = None, authority: dict = None) -> dict:
    """The canonical session PO3 state. PURE — same inputs, same answer, always.

    Nothing here reads a clock, a session label, a scan counter or any carried
    memory, which is precisely why a restart that replays the same settled tape
    reconstructs the same phase.
    """
    bars = [b for b in (settled_1m or []) if isinstance(b, dict)]
    floor = _floor()
    accum = _accumulation_evidence(po3)
    manip = _manipulation_verdict(liquidity)
    own = _ownership(authority)
    mss = _mss_present(structure)

    state = {
        "schema": SCHEMA,
        "phase": UNKNOWN,
        "range": None,
        "excursion": None,
        "manipulation": manip,
        "distribution_direction": None,
        "ownership": own,
        "accumulation_evidence": accum,
        "preferred_playbook_families": [],
        "reason": "insufficient settled history to establish a session balance",
        "evidence": [],
        "settled_bars": len(bars),
    }

    def finish(phase: str) -> dict:
        state["phase"] = phase
        state["new_entry_allowed"], state["block_reason"] = entry_permission(phase)
        return state

    if len(bars) < MIN_FORMING_BARS:
        return finish(UNKNOWN)

    seg = _segment(bars, floor)["anchor"]
    if not seg:
        return finish(UNKNOWN)
    bal, exc = seg["balance"], seg["excursion"]

    rng = {"high": bal["high"], "low": bal["low"], "birth": bal["birth"],
           "last_extension": bal["last_extension"], "age_bars": bal["bars"],
           "established": bal["bars"] >= MIN_RANGE_BARS}
    state["range"] = rng

    # ── no excursion: the balance is still the market ────────────────────────
    if exc is None:
        if not accum["sufficient"]:
            # A quiet stretch is not automatically accumulation. Without the
            # existing PO3 texture corroborating it this is UNKNOWN and entry
            # authority is untouched — which is what keeps a slow directional
            # drift from being mislabelled as balance.
            state["reason"] = ("balance candidate present but per-timeframe PO3 does "
                               "not corroborate accumulation")
            state["evidence"] = [f"accumulation_tfs={accum['timeframes']}"]
            return finish(UNKNOWN)
        state["reason"] = (f"{bal['bars']} settled 1m bars held inside "
                           f"{rng['low']}-{rng['high']}; PO3 accumulation on "
                           f"{','.join(accum['timeframes']) or 'no timeframe'}")
        state["evidence"] = [f"range_age_bars={bal['bars']}",
                             f"accumulation_tfs={accum['timeframes']}"]
        if rng["established"]:
            return finish(ACCUMULATION_ESTABLISHED)
        if bal["bars"] >= MIN_FORMING_BARS:
            return finish(ACCUMULATION_FORMING)
        state["reason"] = (f"only {bal['bars']} bars of balance — too young to call "
                           "accumulation")
        return finish(UNKNOWN)

    # ── an excursion exists ──────────────────────────────────────────────────
    state["excursion"] = {k: exc[k] for k in
                          ("side", "direction", "boundary", "birth", "peak",
                           "bars_outside", "consecutive_outside", "reentered",
                           "reentry_at", "bars_since")}

    # A BALANCE THAT WAS NEVER ESTABLISHED CANNOT BE DEPARTED FROM. This is the
    # opening-drive safety valve (S11): a market that delivers from the bell
    # produces a short candidate and an immediate break, which is not an
    # excursion from anything and must never block.
    if not rng["established"]:
        state["reason"] = ("no established session balance — the candidate range was "
                           f"only {bal['bars']} bars old when price left it")
        state["evidence"] = [f"range_age_bars={bal['bars']}",
                             f"min_range_bars={MIN_RANGE_BARS}"]
        return finish(UNKNOWN)

    opposite = _OPPOSITE[exc["direction"]]

    # ── TRUE DISTRIBUTION: acceptance outside + compatible ownership ─────────
    accepted = (not exc["reentered"]) and exc["consecutive_outside"] >= ACCEPTANCE_BARS
    if accepted and own["direction"] == exc["direction"]:
        state["distribution_direction"] = exc["direction"]
        state["preferred_playbook_families"] = list(_PREFERRED[DISTRIBUTION_ACTIVE])
        state["reason"] = (f"{exc['consecutive_outside']} consecutive settled closes "
                           f"{exc['side']} {exc['boundary']} with {own['direction']} "
                           f"ownership intact — the market repriced")
        state["evidence"] = [f"consecutive_outside={exc['consecutive_outside']}",
                             f"acceptance_bars={ACCEPTANCE_BARS}",
                             f"ownership={own['direction']} via {own['source']}"]
        return finish(DISTRIBUTION_ACTIVE)

    # ── MANIPULATION: the excursion FAILED and the other side is forming ────
    # Three independent propositions, all required. A score alone proves none of
    # them, which is why `classification` (not `score`) is read here.
    failed = exc["reentered"]
    confirmed = (manip["classification"] == "manipulation_confirmed"
                 and manip["direction"] == opposite
                 and not manip["conflicted"])
    opposing_ownership = (own["direction"] == opposite) or bool(mss)
    if failed and confirmed and opposing_ownership:
        state["preferred_playbook_families"] = list(_PREFERRED[MANIPULATION_CONFIRMED])
        state["reason"] = (f"excursion {exc['side']} {exc['boundary']} was rejected and "
                           f"re-entered at {exc['reentry_at']}; confluence confirms "
                           f"{opposite} manipulation on {manip['source_tf']}")
        state["evidence"] = [f"reentry_at={exc['reentry_at']}",
                             f"manipulation={manip['classification']}"
                             f"/{manip['direction']}@{manip['source_tf']}",
                             (f"ownership={own['direction']}"
                              if own["direction"] == opposite else f"mss_tfs={mss}")]
        return finish(MANIPULATION_CONFIRMED)

    # ── RANGE EXTENSION: it came back and proved nothing ─────────────────────
    if failed:
        state["reason"] = ("price left the range and returned without proving "
                           "manipulation — the balance absorbed the excursion")
        state["evidence"] = [f"reentry_at={exc['reentry_at']}",
                             f"manipulation={manip['classification']}"
                             f"/{manip['direction'] or 'no direction'}",
                             f"conflicted={manip['conflicted']}",
                             f"opposing_ownership={opposing_ownership}"]
        # The re-accumulation range contains what the excursion reached: the
        # market showed us that price, so the balance is wider than it was.
        if exc["side"] == "above":
            rng["high"] = max(rng["high"], exc["peak"])
        else:
            rng["low"] = min(rng["low"], exc["peak"])
        rng["last_extension"] = exc["birth"]
        return finish(REACCUMULATION)

    # ── still out there, nothing proven ──────────────────────────────────────
    why = []
    if not accepted:
        why.append(f"only {exc['consecutive_outside']} of {ACCEPTANCE_BARS} "
                   "consecutive closes outside")
    if own["direction"] != exc["direction"]:
        why.append(f"ownership is {own['direction'] or 'unproven'}, not "
                   f"{exc['direction']}")
    state["reason"] = ("price is outside the range but neither manipulation nor "
                       "distribution is proven: " + "; ".join(why))
    state["evidence"] = [f"consecutive_outside={exc['consecutive_outside']}",
                         f"ownership={own['direction']}",
                         f"manipulation={manip['classification']}"]
    return finish(EXCURSION_UNRESOLVED)


class SessionPo3Authority:
    """Provenance wrapper. Adds WHEN, never WHAT.

    Constructed once per session and called every scan, exactly like
    `Po3StabilityManager`. It records phase birth and the transition log so an
    operator can read the session's story; it cannot change the phase `derive()`
    returned, so a one-shot caller that never persists an instance gets the
    identical phase — and so does a restart that replays the tape.
    """

    MAX_TRANSITIONS = 40

    def __init__(self) -> None:
        self._phase = None
        self._phase_birth = None
        self.transitions: list = []

    def update(self, *, settled_1m: list, po3: dict = None, liquidity: dict = None,
               structure: dict = None, authority: dict = None,
               observed_at: str = None) -> dict:
        state = derive(settled_1m=settled_1m, po3=po3, liquidity=liquidity,
                       structure=structure, authority=authority)
        phase = state["phase"]
        at = observed_at or (_ts(settled_1m[-1]) if settled_1m else None)
        changed = phase != self._phase
        if changed:
            self.transitions.append({"from": self._phase, "to": phase, "at": at,
                                     "reason": state.get("reason"),
                                     "evidence": list(state.get("evidence") or [])})
            del self.transitions[:-self.MAX_TRANSITIONS]
            self._phase, self._phase_birth = phase, at
        state["phase_birth"] = self._phase_birth
        state["phase_changed"] = changed
        state["last_transition"] = self.transitions[-1] if self.transitions else None
        state["transition_count"] = len(self.transitions)
        return state
