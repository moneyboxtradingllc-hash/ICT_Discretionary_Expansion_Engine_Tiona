"""ATOMIC MARKET EVENTS — what happened, when, and on what evidence.

PHASE 1C / 4B-DETECTORS (2026-08-12).

Phase 4B was blocked because the producers published CURRENT STATE and threw the
event away:

    sweep_detected = True        # ...but WHEN? on WHAT level?
    bos = True                   # ...and MSS was a bare boolean with no side

Reading the producers showed the information was never missing. `analyze_liquidity`
and `analyze_structure` are LAST-BAR detectors -- they test `candles[-1]` against
swings drawn from the window -- so `sweep_detected: True` means "the newest bar
swept", and the event time is that bar's timestamp. The swept level is computed
as `ref_high`/`ref_low` and discarded. The detectors already knew; nobody asked.

WHY RECONSTRUCTION, NOT A LEDGER
--------------------------------
Events are recomputed from canonical history rather than accumulated in a store.
Both detectors are pure functions of the candles handed to them, so replaying
them over `history[:i+1]` yields the same events every time, and canonical
history stays the single authority. When continuity repair rewrites the tape the
events change with it -- there is no cached ledger to reconcile, and no stale
event can outlive the history that produced it.

NO LOOKAHEAD
------------
Every event at market time T is computed from `history[:T]` ONLY. The alternative
-- derive state from the full tape and stamp it backwards -- would bake future
knowledge into a timestamped record, which is worse than having no chronology at
all because it would look rigorous.

`find_swings` needs `lookback` bars AFTER a pivot to confirm it. That is not
lookahead: at time T it uses only bars at or before T, and a pivot that has not
yet been confirmed simply is not yet a swing. That is how a chart actually works.
"""
from __future__ import annotations

from contextvars import ContextVar

from structure.liquidity_engine import analyze_liquidity
from structure.structure_engine import analyze_structure
from toolbox.price_levels import find_fvgs
from market_data.evidence_continuity import evaluate as evaluate_continuity
from market_data.object_identity import (           # STEP 3F: ONE identity owner
    MarketObjectIdentityError, canonical_contract, canonical_instant,
    market_object_id, row_contract, assert_aligned_bucket, is_aligned_bucket)

#: STEP 4B §7/§10 — every real-tape claim states which history it rests on.
#: Reconstruction runs on retrospective normalized history; without
#: `persisted_at` on legacy rows the engine's as-of knowledge is unrecoverable,
#: and saying UNKNOWN is the only honest answer.
_HISTORY_BASIS = "RETROSPECTIVE_NORMALIZED"
_AS_OF_AVAILABILITY = "AS_OF_AVAILABILITY_UNKNOWN"

LIQUIDITY_SWEEP = "LIQUIDITY_SWEEP"
BOS = "BOS"
MSS = "MSS"
FVG = "FVG"

#: A bar cannot author a settled event unless the bar itself is settled.
_SETTLED_OK = ("settled", "unknown")


def _bar_time(candle: dict) -> str:
    return str((candle or {}).get("timestamp") or "")


def _temporal(candle: dict) -> str:
    return str((candle or {}).get("temporal_status") or "unknown")


def annotate_temporal(candles: list, tf: str) -> list:
    """Attach `temporal_status` to a raw timeframe series, once, before replay.

    `build_timeframes` emits `complete`/`members`; `temporal_status` is applied
    later by `snapshot_builder`. Reconstructing from the raw series therefore saw
    no status at all and published EVERY event as `unknown` -- the temporal
    authority above was inert until this was wired.

    The rule is not reimplemented here. `snapshot_builder._temporal_status` stays
    the single owner, so the S/F/I/U split (including "only the newest bucket may
    be forming") cannot drift between the snapshot and the event stream.
    """
    from market_data.snapshot_builder import _temporal_status
    out = []
    for c in candles or []:
        if c.get("temporal_status"):
            out.append(c)
            continue
        out.append({**c, **_temporal_status(candles, c, tf)})
    return out


#: WEAKEST EVIDENCE WINS. An event is only as settled as the least settled bar
#: it rests on.
#:
#:   forming               → the evidence can still change; not a settled claim
#:   historical_incomplete → finished, but assembled across a hole
#:   unknown               → completeness never recorded. CONTINUITY-2D policy is
#:                           preserved exactly: unknown does not BLOCK (it is
#:                           treated as settled by `_bucket_is_settled`), but it
#:                           is still PUBLISHED as unknown rather than collapsed
#:                           into a confident "settled".
#:   settled               → every source bar closed with full membership
_TEMPORAL_RANK = {"forming": 0, "historical_incomplete": 1, "unknown": 2, "settled": 3}

#: The complete legal set. A value outside it is a CODE defect -- a typo, a
#: schema drift, a renamed constant -- and must never be silently absorbed into
#: `unknown`. "We do not know whether this bar was complete" and "our own string
#: is malformed" are different failures, and only the first is a fact about the
#: market. `.get(s, 2)` would quietly rank `historical_incomplte` as UNKNOWN and
#: let a bug wear the costume of epistemic humility.
VALID_TEMPORAL_STATES = frozenset(_TEMPORAL_RANK)
INVALID_TEMPORAL_STATE = "invalid_temporal_state"


def _normalise_state(state) -> str:
    s = str(state or "unknown")
    return s if s in VALID_TEMPORAL_STATES else INVALID_TEMPORAL_STATE


def _rank(state: str) -> int:
    # An invalid value sorts BELOW forming: it is the least trustworthy thing a
    # source can report, and it must surface rather than hide.
    return _TEMPORAL_RANK.get(state, -1)


def _continuity_fields(bars_or_stamps: list, tf: str) -> dict:
    """The SECOND evidence axis: was the supporting series actually contiguous?

    Per-bar S/F/I/U describes the observations that EXIST. It cannot say whether
    observations that SHOULD exist are missing between them. Measured on the real
    15m tape: 10 of 23 swings rest on non-contiguous evidence, the worst spanning
    70 hours across 7 "confirming" bars -- every one of them settled.

    Absence may never masquerade as continuity.
    """
    c = evaluate_continuity(bars_or_stamps, tf)
    return {"source_continuity_class": c["continuity_class"],
            "source_continuity_issues": c["continuity_issues"],
            "source_observation_count": c["observation_count"],
            "source_elapsed_minutes": c["elapsed_minutes"],
            "source_gaps": c["gaps"]}


def _evidence_summary(states: list) -> dict:
    """The FULL evidence condition, not just its weakest rank.

    A scalar rank is a useful authority summary but it is LOSSY. Evidence of
    `[historical_incomplete, settled, forming]` ranks as `forming`, and a reader
    would reasonably take that as "not authoritative yet -- wait for the close".
    But when that bar closes the permanent historical damage is still there. The
    two defects are ORTHOGONAL, not two rungs on one ladder, so both are kept.
    """
    seen = {_normalise_state(s) for s in (states or [])}
    # §14: a malformed value is a CODE defect, not a market condition. It must
    # not sit beside settled/forming/incomplete as though the venue emitted it.
    # Code health and market health are different reports.
    schema_errors = sorted(raw for raw in {str(s) for s in (states or [])}
                           if raw not in VALID_TEMPORAL_STATES)
    market = sorted(seen - {INVALID_TEMPORAL_STATE}, key=_rank)
    return {"evidence_temporal_classes": market,
            "all_evidence_settled": market == ["settled"] and not schema_errors,
            "evidence_schema_errors": schema_errors}


def _weakest_temporal(candles: list) -> str:
    """The temporal class of an event resting on ALL of `candles`.

    A first version published `_temporal(last_bar)` alone. For a three-candle FVG
    that is wrong: c1 and c2 can be historical_incomplete while c3 is settled,
    and the gap would have claimed settled evidence it does not have. An event
    inherits the weakest bar it depends on.
    """
    states = [_normalise_state(_temporal(c)) for c in candles if c]
    if not states:
        return "unknown"
    return min(states, key=_rank)


#: STEP 3F — PRODUCER CARDINALITY, audited before any id was chosen.
#:
#: The question for every type: can the producer emit TWO objects of this kind
#: for one contract, timeframe and instant? If not, that triple already names a
#: unique slot and everything else is state.
#:
#:   LIQUIDITY_SWEEP   `analyze_liquidity` returns ONE `sweep_direction` per
#:                     call -> one per (tf, bar). `side` is the answer.
#:   BOS / MSS         `analyze_structure` returns ONE `bos`/`bos_direction`
#:                     per call -> one per (tf, transition bar). `direction`
#:                     and `broken_level` are the answer.
#:   MAGNITUDE_WITNESS `detect_displacement` returns ONE `conviction_candle`
#:                     per call -> one per (tf, assessment). The selected
#:                     candle is the RESULT of the largest-body scan, not the
#:                     identity of the scan.
#:   FOLLOW_THROUGH_RUN  one run per call. `direction` and `run_length` are the
#:                     answer -- and were in the id, so repairing history until
#:                     a run read 2 instead of 3 minted a second fact.
#:   DISPLACEMENT_ASSESSMENT  one per (tf, scan).
#:
#:   FVG               THE EXCEPTION. `find_fvgs` can return SEVERAL gaps from
#:                     one window, and two can complete on the same bar in
#:                     opposite directions. Its true occurrence key is Step 4's
#:                     job; until then it keeps its geometry discriminators,
#:                     which are at least immutable given fixed evidence.
#:
#: Literal names, not the constants: several of those are defined further down
#: the module and this table has to exist before `_event_id` does.
_SINGLE_PER_TF_INSTANT = frozenset({
    "LIQUIDITY_SWEEP", "BOS", "MSS", "MAGNITUDE_WITNESS", "FOLLOW_THROUGH_RUN",
    "DISPLACEMENT_ASSESSMENT", "CANDLE_REFERENCE"})


def _event_id(event_type: str, tf: str, when: str, *parts,
              contract=None) -> str:
    """Deterministic identity from immutable evidence, via the ONE owner.

    No UUIDs and no process time: the same factual event must carry the same ID
    on scan N and scan N+1, or chronology cannot be diffed and a tool can never
    reference the event that produced it.

    STEP 3F: every id is contract-scoped and instant-canonical, and for a type
    whose producer emits at most ONE object per (tf, instant) the trailing
    `parts` are DROPPED -- they were the answer, not the identity. Only FVG,
    which genuinely emits several per bar, keeps its discriminators.
    """
    keep = () if event_type in _SINGLE_PER_TF_INSTANT else parts
    return market_object_id(event_type, contract=contract or _active_contract(),
                            timeframe=tf, instant=when, discriminators=keep)


#: STEP 3G §6 — WHERE AN OBJECT'S CONTRACT CAME FROM.
#:
#: "This is U26 because its source bars prove U26" and "this is U26 because the
#: caller asserted U26" are both legitimate in different paths, and they are not
#: the same claim. Published so a reader can tell them apart.
EVIDENCE_DERIVED = "EVIDENCE_DERIVED"
TRUSTED_BOUNDARY_SUPPLIED = "TRUSTED_BOUNDARY_SUPPLIED"


#: The contract the current reconstruction is scoped to. Set explicitly by the
#: caller; there is deliberately NO module-level production default, because a
#: low-level id builder that supplies one would stamp MNQ onto foreign bars.
#: STEP 4B.1 §7 — A CONTEXTVAR, NOT A MODULE-GLOBAL LIST.
#:
#: The first version was a plain `list` at module scope. Push/pop made it
#: correct under nesting and exceptions, and WRONG under concurrency: the
#: provider owns a `threading.Lock`, so this runtime really is multi-threaded,
#: and two threads reconstructing different contracts would have read each
#: other's scope. A serial U26/MES/Z26 test cannot see that.
#:
#: `ContextVar` isolates per thread AND per async task, and its token-based
#: reset restores exactly the prior value rather than assuming the stack is
#: balanced. Ambient scope remains an internal convenience -- published object
#: provenance passes its contract EXPLICITLY (see `_fvgs_at`), so exact
#: references never depend on invisible state.
_CONTRACT_SCOPE: "ContextVar" = ContextVar("market_events_contract_scope",
                                           default=())


def _active_contract():
    stack = _CONTRACT_SCOPE.get()
    return stack[-1][0] if stack else None


def _active_provenance():
    stack = _CONTRACT_SCOPE.get()
    return stack[-1][1] if stack else None


class contract_scope:
    """Bind every id minted inside this block to one canonical contract."""

    def __init__(self, contract, provenance=TRUSTED_BOUNDARY_SUPPLIED):
        self.contract = canonical_contract(contract, where="contract_scope")
        self.provenance = provenance
        self._token = None

    def __enter__(self):
        self._token = _CONTRACT_SCOPE.set(
            _CONTRACT_SCOPE.get() + ((self.contract, self.provenance),))
        return self.contract

    def __exit__(self, *exc):
        _CONTRACT_SCOPE.reset(self._token)
        return False


def resolve_contract(candles: list, explicit=None, *,
                     where: str = "reconstruction") -> tuple:
    """(contract, provenance). STEP 3G §4.

    AN EXPLICIT CLAIM MAY FILL ABSENCE. IT MAY NEVER ERASE CONTRADICTION.

    A caller parameter is how an aggregated series -- whose bars once lost the
    field in transformation -- gets its scope back at a deliberate boundary. But
    if the bars themselves prove U26 and the caller says Z26, letting the caller
    win would mint flawless-looking ids for falsely scoped evidence. Two
    authorities disagreeing is a contradiction to surface, exactly as a declared
    `epistemic_layer` that fights the registry is.
    """
    evidence = _contract_in(candles)
    if evidence and explicit and str(explicit) != evidence:
        raise MarketObjectIdentityError(
            f"{where}: the bars prove contract {evidence!r} but the caller "
            f"asserted {str(explicit)!r}. An explicit scope may supply missing "
            f"provenance; it may not overrule the evidence.")
    if evidence:
        return evidence, EVIDENCE_DERIVED
    if explicit:
        return canonical_contract(explicit, where=where), TRUSTED_BOUNDARY_SUPPLIED
    raise MarketObjectIdentityError(
        f"{where}: the bars carry no contract and none was supplied. "
        f"Identity is required, never inferred.")


def _contract_in(candles: list) -> "str | None":
    """The single contract these bars prove. None if ALL silent; raise if mixed
    OR partially silent.

    STEP 3H §11 -- the same question `_bucket_contract` had. A series of

        U26 bar, U26 bar, anonymous bar

    does not prove the same thing as three U26 bars. One identified member does
    not identify its anonymous neighbours, and the reconstruction level must not
    be more permissive than the aggregation level it consumes.
    """
    named, silent = set(), 0
    for c in candles or []:
        if isinstance(c, dict):
            # §3: a row declaring both `contract` and `contractId` with
            # different values is refused rather than resolved by field order.
            v = row_contract(c, where="candle series")
            if v:
                named.add(v)
            else:
                silent += 1
    if len(named) > 1:
        raise MarketObjectIdentityError(
            f"bars span multiple contracts {sorted(named)}; one reconstruction "
            f"cannot mint identities for two markets.")
    if named and silent:
        raise MarketObjectIdentityError(
            f"{silent} of {silent + sum(1 for c in candles or [] if isinstance(c, dict) and (c.get('contract') or c.get('contractId')))} "
            f"bars carry no instrument while the rest prove "
            f"{next(iter(named))!r}. Partial provenance is schema damage, not "
            f"uncertainty -- it may not be completed from its neighbours.")
    return named.pop() if named else None


def contract_from_evidence(candles: list, *, where: str = "reconstruction") -> str:
    """The contract the DATA ITSELF proves. STEP 3F §4.

    Canonical store rows carry their own `contract`, so identity does not have
    to be guessed and must not be. A low-level default of PRODUCTION_CONTRACT
    would stamp `CON.F.US.MNQ.U26` onto MES bars whose caller forgot to say so
    -- mislabelling foreign data as production data at the one layer nobody
    re-checks. Absent provenance is a failure.

    Aggregated series lose the field (`timeframe_builder._aggregate` rebuilds a
    bar from OHLCV alone), so a caller working on 3m/5m/15m passes `contract=`
    explicitly. That is the boundary where identity is minted, and it is
    supposed to be explicit there.
    """
    seen = set()
    for c in candles or []:
        if isinstance(c, dict):
            v = str(c.get("contract") or c.get("contractId") or "").strip()
            if v:
                seen.add(v)
    if len(seen) == 1:
        return seen.pop()
    if not seen:
        raise MarketObjectIdentityError(
            f"{where}: the bars carry no contract and none was supplied. "
            f"Identity is required, never inferred -- pass contract=... rather "
            f"than letting this layer assume the production instrument.")
    raise MarketObjectIdentityError(
        f"{where}: bars span multiple contracts {sorted(seen)}; one "
        f"reconstruction cannot mint identities for two markets.")


def _sweep_at(window: list, tf: str) -> "dict | None":
    """A sweep authored by the NEWEST bar of `window`, or None.

    `reclaimed` is an ATTRIBUTE, never its own event. The producer sets
    `reclaim_detected` in the same branch as the sweep -- one bar pierced a level
    and closed back through it. Emitting a separate RECLAIM row referencing a
    sweep would invent an ontology this detector does not have; a genuine
    multi-bar reclaim would need its own detector before it earns its own event.
    """
    # STEP 4B.12 §10 — EXPLICIT LEGACY OPT-IN, mirroring `find_fvgs`.
    #
    # This caller supplies no cadence, so `analyze_liquidity` would otherwise
    # withhold every prior-close-dependent fact. It bridges to the array
    # neighbour instead, which is exactly the synthetic adjacency the production
    # path now refuses -- so the bridge has to be requested out loud rather than
    # inherited by omission.
    #
    # Tolerable ONLY because this module is proven NONCANONICAL: repo-wide, no
    # file under `src/` imports `market_events`; its only consumers are
    # tests/test_market_events.py and tests/test_evidence_continuity.py. If a
    # production importer ever appears, this line is the first thing to revisit.
    liq = analyze_liquidity(window, allow_uncadenced=True)
    if not liq.get("sweep_detected"):
        return None
    last = window[-1]
    side = liq.get("sweep_direction")
    level = (liq.get("nearest_buy_side_liquidity") if side == "above_high"
             else liq.get("nearest_sell_side_liquidity"))
    when = _bar_time(last)
    return {"event_id": _event_id(LIQUIDITY_SWEEP, tf, when, side),
            "event_type": LIQUIDITY_SWEEP, "event_time": when, "source_tf": tf,
            "sweep_side": side, "swept_level": level,
            "reclaimed": bool(liq.get("reclaim_detected")),
            "failed_breakout": bool(liq.get("failed_breakout")),
            # Evidence = the pierce/close-back bar AND the prior close it is
            # measured against; the producer reads candles[-2] as `prior`.
            "temporal_class": _weakest_temporal(window[-2:]),
            **_evidence_summary([_temporal(c) for c in window[-2:]]),
            "source_bars": [_bar_time(c) for c in window[-2:]],
            **_continuity_fields(window[-2:], tf),
            "source_bar": when}


def _broken_swing(window: list, direction: str, tf: str = None) -> "dict | None":
    """The exact swing object `analyze_structure` compared against.

    It uses `highs[-1]` for a bullish break and `lows[-1]` for a bearish one --
    the newest confirmed swing on that side -- so the same selection is made here
    against the detailed objects. No re-derivation of the pivot rule.
    """
    from structure.structure_engine import find_swings_detailed
    # NONCANONICAL module (no `src/` importer); legacy semantics stated aloud.
    highs, lows = find_swings_detailed(window, tf, allow_uncadenced=True)
    pool = highs if direction == "bullish" else lows
    return pool[-1] if pool else None


def _swing_temporal(swing: "dict | None") -> str:
    """A level is only as settled as the bars that formed and confirmed it."""
    if not swing:
        return "unknown"
    states = [_normalise_state(x) for x in (swing.get("source_temporal_states") or [])]
    if not states:
        return "unknown"
    return min(states, key=_rank)


def _legacy_uncadenced_transition(window: list) -> dict:
    """NONCANONICAL COMPATIBILITY ONLY — local to this module.

    STEP 4B.12 §4 UNIT 2 made a break an EVENT, which requires the close of the
    previous EXPECTED market bucket. This module has no cadence and no venue
    calendar, so it cannot supply one; without a transition it would emit ZERO
    structural events forever and its provenance/continuity tests would become
    vacuous rather than wrong.

    So it treats its own supplied sequence as locally adjacent -- the same
    already-declared legacy posture as its `allow_uncadenced=True` swing calls.

    THREE THINGS THIS IS NOT:
      * it is NOT canonical evidence and claims no venue-cadence authority
      * it does NOT widen `allow_uncadenced`, which keeps meaning legacy SWING
        geometry and never authorises transition evidence
      * it does NOT restore "beyond the level == event". The minimum event
        theorem still applies: `analyze_structure` receives a previous close and
        requires a CROSSING. Remaining beyond a level is still a state here too.

    Tolerable only because this module is proven noncanonical: repo-wide, no file
    under `src/` imports `market_events`. That claim is pinned by test.
    """
    if len(window or []) < 2:
        return {"state": "UNEVALUABLE_PREVIOUS_SLOT"}
    return {"state": "EVALUABLE",
            "previous_close": window[-2].get("close"),
            "current_bucket": str(window[-1].get("timestamp") or ""),
            "authority": "LEGACY_UNCADENCED_LOCAL_SEQUENCE"}


def _structure_at(window: list, tf: str) -> list:
    """BOS and, when the break opposes the prevailing bias, MSS.

    MSS DIRECTION PROVENANCE: `analyze_structure` computes `bos_dir` from THIS
    call's `last_close` against THIS call's swings, and derives `mss` from that
    same `bos_dir`. The side is therefore witnessed by the break that authors the
    MSS -- not read from a stored or previous `bos_direction`. That distinction
    is small in code and total in ontology, and `test_mss_direction_comes_from_
    its_own_break` pins it.
    """
    # NONCANONICAL: local legacy adjacency, event theorem intact.
    st = analyze_structure(window, allow_uncadenced=True,
                           transition=_legacy_uncadenced_transition(window))
    if not st.get("bos"):
        return []
    last = window[-1]
    when, direction = _bar_time(last), st.get("bos_direction")
    # STEP 2C — A BREAK IS ONLY AS TRUSTWORTHY AS THE LEVEL IT BROKE.
    #
    # `analyze_structure` compares `last_close` against `highs[-1]` / `lows[-1]`,
    # so the broken level is the newest confirmed swing on that side. Recovering
    # that exact swing object gives the event its second evidentiary leg: when
    # the level formed, what confirmed it, and whether that evidence was settled.
    #
    # Previously this published `level_evidence_temporal_class: "unknown"`, which
    # was honest but conflated two different things -- history whose completeness
    # was never recorded, and provenance our own code discarded. The second is
    # sensor debt, not market uncertainty, and it is now paid.
    swing = _broken_swing(window, direction, tf)
    common = {"event_time": when, "source_tf": tf, "direction": direction,
              "broken_level": st.get("broken_level"),
              "break_close": st.get("break_close"),
              # BOTH legs. `temporal_class` is the weaker of the break bar and
              # the broken level's own evidence: a settled close breaking a level
              # built on a damaged bucket is not a settled structural event.
              "break_temporal_class": _temporal(last),
              "level_temporal_class": _swing_temporal(swing),
              "temporal_class": min(
                  (_normalise_state(_temporal(last)), _swing_temporal(swing)),
                  key=_rank),
              **_evidence_summary([_temporal(last)]
                                  + list((swing or {}).get("source_temporal_states") or [])),
              # §16: an unscoped id (`swing_high:unspecified_tf:...`) may never
              # become canonical market identity. No timeframe, no id published.
              "broken_swing_id": ((swing or {}).get("swing_id")
                                  if (swing or {}).get("source_tf") else None),
              "broken_swing_pivot_time": (swing or {}).get("pivot_time"),
              "broken_swing_confirmed_at": (swing or {}).get("confirmed_at"),
              # The multi-bar evidence behind a structural event IS its level's
              # evidence, so it is published under BOTH the uniform key every
              # event family uses and a `level_`-prefixed alias that names whose
              # continuity it describes.
              **_continuity_fields((swing or {}).get("source_bars") or [], tf),
              **{f"level_{k}": v for k, v in
                 _continuity_fields((swing or {}).get("source_bars") or [], tf).items()},
              "source_bar": when}
    out = [{"event_id": _event_id(BOS, tf, when, direction,
                                  st.get("broken_level")),
            "event_type": BOS, **common}]
    if st.get("mss"):
        out.append({"event_id": _event_id(MSS, tf, when, direction,
                                          st.get("broken_level")),
                    "event_type": MSS, "prevailing_bias": st.get("bias"),
                    **common})
    return out


_TF_MINUTES_FOR_BUCKET = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60}


def _bucket_end(bucket_start, tf: str) -> "str | None":
    """The market interval boundary. ARITHMETIC, not knowledge.

    A 5m bucket starting 17:10 closes 17:15. That is a fact about the market
    interval and says nothing about when the engine possessed the final bar.
    """
    from datetime import datetime, timedelta
    minutes = _TF_MINUTES_FOR_BUCKET.get(tf)
    if not minutes:
        return None
    try:
        dt = datetime.fromisoformat(str(bucket_start).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return canonical_instant((dt + timedelta(minutes=minutes)).isoformat())


#: STEP 4B.9 §2/§3 — the two dimensions, kept apart.
GEOMETRY_PROVEN = "PROVEN"
GEOMETRY_UNPROVEN_BOUNDARY_INCOMPLETE = "UNPROVEN_BOUNDARY_EVIDENCE_INCOMPLETE"
GEOMETRY_PROVISIONAL_FORMING = "PROVISIONAL_FORMING_BOUNDARY"
HEALTH_CLEAN = "ALL_MEMBERS_SETTLED"
HEALTH_DEGRADED_MIDDLE = "DEGRADED_MIDDLE_MEMBER"
HEALTH_DEGRADED_BOUNDARY = "DEGRADED_BOUNDARY_MEMBER"
HEALTH_FORMING = "FORMING_MEMBER_PRESENT"


def _geometry_authority(c1: dict, c3: dict) -> str:
    """Can the inequality itself be trusted? Only c1/c3 extrema decide."""
    states = {_temporal(c1), _temporal(c3)}
    if "forming" in states:
        # FORMING and HISTORICAL_INCOMPLETE are NOT the same state (§4): the
        # first may legitimately revise as the market moves on; the second is
        # evidence that was never observed and cannot be recovered.
        return GEOMETRY_PROVISIONAL_FORMING
    if "historical_incomplete" in states:
        return GEOMETRY_UNPROVEN_BOUNDARY_INCOMPLETE
    return GEOMETRY_PROVEN


def _triple_health(c1: dict, c2: dict, c3: dict) -> str:
    """The provenance health of the whole canonical source triple."""
    s1, s2, s3 = _temporal(c1), _temporal(c2), _temporal(c3)
    if "forming" in (s1, s2, s3):
        return HEALTH_FORMING
    if "historical_incomplete" in (s1, s3):
        return HEALTH_DEGRADED_BOUNDARY
    if s2 == "historical_incomplete":
        return HEALTH_DEGRADED_MIDDLE
    return HEALTH_CLEAN


def _fvgs_at(window: list, tf: str, *, observed_at: str = None,
             history_basis: str = None, as_of_availability: str = None) -> list:
    """FVG instances whose THIRD candle is the newest bar.

    Direction comes from the gap's own geometry -- `c1.high < c3.low` is a
    bullish gap, `c1.low > c3.high` a bearish one, and the two tests are
    mutually exclusive on the same three candles. Nothing here consults
    displacement, structure bias or any supplied label: an FVG proves its own
    side or it is not an FVG.
    """
    out = []
    if len(window) < 3:
        return out
    formed_index = len(window) - 3          # this gap's c3 is the newest bar
    _c1, _c2, _c3 = window[formed_index], window[formed_index + 1], window[-1]
    # STEP 4B.2 §5 — THE PROVENANCE CALCULATION NAMES THE EVIDENCE IT VALIDATES.
    #
    # This was `_contract_in(window[-3:])`, which selects the same three bars
    # under today's implementation and would silently stop doing so if the
    # triple were ever chosen differently. The claim is about c1/c2/c3, so the
    # computation is about c1/c2/c3.
    #
    # §6 — the ambient fallback has exactly ONE legitimate meaning: all three
    # source bars are genuinely silent (an aggregated series that lost the field
    # in transformation) and a trusted boundary supplied scope. Mixed, partial
    # and self-contradicting rows all RAISE inside `_contract_in` rather than
    # returning None, so this `or` can never launder a refusal into a guess.
    _evidence_contract = _contract_in([_c1, _c2, _c3])
    resolved = _evidence_contract or _active_contract()
    _contract_provenance = (EVIDENCE_DERIVED if _evidence_contract
                            else TRUSTED_BOUNDARY_SUPPLIED)
    last = window[-1]
    when = _bar_time(last)
    for direction in ("bullish", "bearish"):
        for gap in find_fvgs(window, direction, _TF_MINUTES_FOR_BUCKET.get(tf)):
            if gap.get("index") != formed_index:
                continue                    # older gap, already emitted at its own bar
            c1, c2, c3 = _c1, _c2, _c3
            out.append({
                # STEP 4 — IDENTITY IS THE COMPLETION SLOT.
                #
                # `find_fvgs` walks `i` over array-consecutive triples
                # (i, i+1, i+2), so for a completion index j there is exactly
                # one i = j-2: ONE triple per completion bar. And on well-formed
                # candles the two predicates are mutually exclusive --
                #
                #   bullish ⟹ c1.low ≤ c1.high < c3.low ≤ c3.high ⟹ c1.low <
                #   c3.high ⟹ ¬bearish
                #
                # -- verified exhaustively (0 of 100 well-formed combinations
                # satisfy both) and measured on the real tape (0 collisions
                # across 1m/3m/5m/15m on unique ordered history).
                #
                # So `contract + tf + completion bucket` already names exactly
                # one occurrence. `direction`, `gap_low`, `gap_high` and
                # `gap_size` are RECONSTRUCTED FROM c1/c3 OHLC -- history repair
                # can change them, and putting them in the id would mint a twin
                # on every revision instead of revising one object.
                # §7: the slot must be a bucket this timeframe can actually
                # have. Validated BEFORE the id is minted, not after.
                "event_id": _event_id(FVG, tf, assert_aligned_bucket(
                    when, tf, where="FVG completion slot")),
                "event_type": FVG, "event_time": when, "source_tf": tf,
                "epistemic_layer": "MARKET_EVENTS",
                # ── STEP 4B §4/§5: BUCKET TIME IS NOT KNOWLEDGE TIME ──
                #
                # `when` is c3's BUCKET START. On 5m that bucket spans
                # 17:10->17:15, so `c1.high < c3.low` cannot be a settled fact
                # at 17:10 -- c3's low is still moving. The slot is legitimately
                # identified by the bucket; the KNOWLEDGE is not.
                #
                # `event_time` keeps the bucket start for chronology ordering
                # and compatibility, and every other clock is named separately
                # rather than collapsed into it.
                "completion_bucket": canonical_instant(when),
                "completion_bucket_start": canonical_instant(when),
                "completion_bucket_end": _bucket_end(when, tf),
                # STEP 4B.2 §1/§2 — WHOSE CLOCK IS THIS?
                #
                # On LIVE_CURRENT this really is the moment the running system
                # observed the geometry. On RETROSPECTIVE_NORMALIZED it is only
                # the simulated scan at which THIS RECONSTRUCTION evaluated the
                # object -- the original engine's possession of those source
                # revisions is unrecoverable without `persisted_at`.
                #
                # One field cannot honestly carry both, so the reconstruction
                # clock is named for what it is, and the perception clock is
                # published only when the basis can support it.
                "assessed_at": canonical_instant(observed_at or when),
                "engine_observed_at": (canonical_instant(observed_at)
                                       if (observed_at and history_basis == "LIVE_CURRENT")
                                       else None),
                "engine_observation_known": history_basis == "LIVE_CURRENT",
                # §6: c3 settled means the geometry rests on a closed bucket.
                # A FORMING c3 can show geometry NOW that price erases two
                # minutes later -- real live state, never a settled historical
                # formation.
                # ── STEP 4B.9 §1/§2 — GEOMETRY AUTHORITY vs SOURCE HEALTH ──
                #
                # The inequality is `c1.high < c3.low` (bullish) or
                # `c1.low > c3.high` (bearish). c2's OHLC NEVER participates --
                # it is a member of the canonical source triple and of its
                # provenance, but its extrema establish nothing.
                #
                # So the two questions must be answered separately:
                #
                #   c2 historical_incomplete  -> geometry still PROVEN from
                #                                trustworthy c1/c3; the triple's
                #                                evidence health is DEGRADED
                #   c1 or c3 incomplete       -> the missing constituent could
                #                                change the very extremum the
                #                                inequality consumes, so the
                #                                settled geometry is NOT proven
                #
                # Neither direction of laundering is allowed: a computable gap
                # is not a clean object, and a degraded middle member does not
                # erase a provable fact.
                "geometry_source_fields": ("c1.high", "c3.low") if direction == "bullish"
                                          else ("c1.low", "c3.high"),
                "geometry_authority": _geometry_authority(c1, c3),
                "source_evidence_health": _triple_health(c1, c2, c3),
                "c1_temporal_status": _temporal(c1),
                "c2_temporal_status": _temporal(c2),
                "c3_temporal_status": _temporal(last),
                "formation_settled": _temporal(last) == "settled",
                # STEP 4B.1 §2 — `settled_confirmation_at = bucket_start` was
                # the exact backdating bug this step exists to kill: a 5m bar
                # beginning at 17:10 cannot have final OHLC at 17:10.
                #
                # THREE CLOCKS, NEVER ONE:
                #   bucket_start   identity time     17:10
                #   bucket_end     market interval   17:15  (arithmetic)
                #   settled_observed_at  knowledge   UNKNOWN on retrospective
                #                                    history with no persisted_at
                #
                # Even a proven 17:15 bucket close does not prove the ENGINE
                # held the final bar at 17:15, so this stays null rather than
                # being filled with a plausible-looking timestamp.
                "settled_observed_at": (canonical_instant(observed_at)
                                        if (observed_at and _temporal(last) == "settled"
                                            and as_of_availability == "AS_OF_AVAILABILITY_PROVEN")
                                        else None),
                "geometry_may_still_revise": _temporal(last) == "forming",
                # §7: without `persisted_at` on legacy rows, retrospective
                # replay can reconstruct the geometry but not prove when the
                # engine learned it.
                "history_basis": history_basis,
                "as_of_availability": as_of_availability,
                # ── reconstructed state ──
                "direction": direction, "gap_low": gap["low"], "gap_high": gap["high"],
                "gap_size": gap["size"],
                # ── exact three-candle evidence ──
                # STEP 4B.1 §8/§9 — EXPLICIT SCOPE AT CONSTRUCTION.
                #
                # `resolved` is the contract each of c1/c2/c3 individually
                # PROVED (via `row_contract`, which refuses a row whose
                # `contract` and `contractId` disagree) and which `_contract_in`
                # then required to be unanimous -- no mixed, no partial. Only
                # after that is it used to build the ids. Order matters: prove
                # the sources, THEN scope them; never choose a contract and
                # stamp it onto contradictory candles.
                #
                # Passed explicitly rather than inherited from ambient scope, so
                # a published reference carries its own proof.
                "c1_id": candle_reference_id(tf, _bar_time(c1), contract=resolved),
                "c2_id": candle_reference_id(tf, _bar_time(c2), contract=resolved),
                "c3_id": candle_reference_id(tf, when, contract=resolved),
                "contract": resolved,
                "contract_provenance": _contract_provenance,
                "c1_time": _bar_time(c1), "c2_time": _bar_time(c2), "c3_time": when,
                # The array index is DIAGNOSTIC ONLY -- a position in a list is
                # not a market identity and shifts the moment history is
                # repaired.
                "producer_index": gap.get("index"),
                "source_bars": [_bar_time(c1), _bar_time(c2), when],
                # ALL THREE candles are the evidence, not just c3. c1 and c2 can
                # be historical_incomplete while c3 is settled, and publishing
                # only c3's class would claim evidence the gap does not have.
                "temporal_class": _weakest_temporal(
                    window[formed_index:formed_index + 3]),
                **_evidence_summary(
                    [_temporal(c) for c in window[formed_index:formed_index + 3]]),
                **_continuity_fields(window[formed_index:formed_index + 3], tf),
                "source_bar": when})
    return out


def reconstruct_events(candles: list, tf: str, *, lookback_bars: int = None,
                       contract=None) -> list:
    """Every atomic event the detectors witness in `candles`, oldest first.

    `candles` must be canonical, ascending, and contain nothing after the moment
    being reconstructed. Each bar is judged on `candles[:i+1]` -- the market as it
    stood then.
    """
    events = []
    n = len(candles or [])
    if n == 0:
        return events
    if contract or not _active_contract():
        # STEP 3F: every id minted below is scoped to ONE canonical contract.
        resolved, _prov = resolve_contract(candles, contract,
                                          where="reconstruct_events")
        with contract_scope(resolved):
            return reconstruct_events(candles, tf, lookback_bars=lookback_bars)
    candles = annotate_temporal(candles, tf)
    start = 0 if not lookback_bars else max(0, n - int(lookback_bars))
    # TRANSITIONS, NOT CONDITIONS.
    #
    # `analyze_structure` tests `last_close < last_swing_low`, which stays true
    # for every bar price remains below the level -- so a single break was
    # emitted once per bar. Measured on the Aug-12 afternoon: 104 BOS "events",
    # most of them the SAME break restated, `broken=29877.5` repeating across
    # nine consecutive minutes. A condition holding is not an event recurring.
    #
    # An event is therefore published when its identity CHANGES from the
    # previous bar's reading of the same event type. The comparison is against
    # bar i-1 only, so this stays strictly no-lookahead.
    previous = {}
    for i in range(start, n):
        window = candles[:i + 1]            # <= T. never the full tape sliced back.
        if len(window) < 4:
            continue
        # ONE-SHOT: each bar independently proves the whole proposition, so a
        # repeat on the next bar is a SECOND occurrence, not the first one
        # persisting. `analyze_liquidity` tests candles[-1] against candles[-2]:
        # this bar pierced a level and this bar closed back through it. Two
        # consecutive bars raiding 29888 are two raids.
        sweep = _sweep_at(window, tf)
        if sweep:
            events.append(sweep)
        # An FVG is likewise one-shot: emitted only on the bar completing its
        # three-candle geometry.
        events.extend(_fvgs_at(window, tf, observed_at=_bar_time(window[-1]),
                               history_basis=_HISTORY_BASIS,
                               as_of_availability=_AS_OF_AVAILABILITY))
        # PERSISTENT CONDITIONS: the transition is the event.
        # `bos` is `last_close` beyond a swing -- true for every bar price stays
        # there. `mss` is a function of that same persistent `bos` plus `bias`,
        # so it persists too. Publishing one per bar restated a single break 104
        # times on the Aug-12 afternoon.
        struct = {e["event_type"]: e for e in _structure_at(window, tf)}
        for kind in (BOS, MSS):
            event = struct.get(kind)
            key = None if event is None else _continuity_key(event)
            if event is not None and key != previous.get(kind):
                events.append(event)
            previous[kind] = key
    return events


def _continuity_key(event: dict) -> tuple:
    """What makes this the SAME occurrence as the bar before.

    FOR PERSISTENT-CONDITION EVENTS ONLY (BOS, MSS). Deliberately excludes
    `event_time`: a break of the same level in the same direction is one event
    that persists, not a new one each minute.

    It must NEVER be applied to one-shot events. A first version used it for
    sweeps too, which would have merged 19:15 and 19:16 raids of 29888 into a
    single occurrence -- collapsing two real market events because one dedupe
    rule was reused across two different ontologies.
    """
    return (event.get("event_type"), event.get("source_tf"),
            event.get("direction"), event.get("broken_level"))


def reconstruct_all(candles_by_tf: dict, *, lookback_bars: dict = None,
                    contract=None) -> list:
    """One canonical chronology across every timeframe, ordered by MARKET time.

    Ordering is by `event_time`, never by detector execution order, dictionary
    order or timeframe priority. Ties keep a deterministic secondary key so two
    runs agree, without claiming precedence the evidence does not support.
    """
    out = []
    for tf, candles in (candles_by_tf or {}).items():
        limit = (lookback_bars or {}).get(tf)
        out.extend(reconstruct_events(candles, tf, lookback_bars=limit,
                                      contract=contract))
    return sorted(out, key=lambda e: (e["event_time"], e["source_tf"],
                                      e["event_type"], e["event_id"]))


#: STEP 3A/3B — THREE LAYERS, DELIBERATELY NOT ONE.
#:
#: The first reconstruction published 67 "displacement events" over 45 bars, 42
#: of them on 1m alone. That density was the tell. Reading the producer settled
#: it: `detect_displacement` scores `candles[-LOOKBACK:]`, a FIXED TRAILING
#: 10-BAR WINDOW with no leg detection and no start-of-move anchoring -- so one
#: conviction candle keeps it answering yes for up to ten consecutive bars.
#:
#: 3A split assessment from occurrence. 3B settled what the composite IS. The
#: audit found 89% of readings with no magnitude witness, 55 of them classified
#: `displacement_confirmed`, and zero anchored 15m readings across 250 bars.
#: That is not a market-event detector wearing the wrong label; it is a
#: MECHANICAL ASSESSMENT ENGINE, and the honest fix was to demote the composite
#: to its true jurisdiction rather than change trading doctrine to fit an event
#: ontology.
#:
#:   ATOMIC MARKET FACT       CANDLE_REFERENCE, FVG, BOS/MSS, LIQUIDITY_SWEEP
#:                            physical geometry, exact identity, own event_time
#:   MARKET OBSERVATION       FOLLOW_THROUGH_RUN -- a rolling state, not an event
#:   DERIVED ASSESSMENT       DISPLACEMENT_ASSESSMENT -- mechanical opinion
#:
#: A weighted window assessment is not an atomic market event. A conviction
#: candle is not automatically an entire displacement leg.
DISPLACEMENT_ASSESSMENT = "DISPLACEMENT_ASSESSMENT"
FOLLOW_THROUGH_RUN = "FOLLOW_THROUGH_RUN"

#: STEP 3C — `CONVICTION_CANDLE` WAS TWO CLAIMS WEARING ONE TIMESTAMP.
#:
#: 3B published one object stamped at the anchor candle's own time carrying both
#: its OHLC and its ATR multiple, and called the whole thing an atomic market
#: fact. Only half of that is anchor-time knowledge.
#:
#:     "a candle with this body opened and closed here at 16:35"
#:         -> TRUE AT 16:35. Physical. Nothing later can change it.
#:
#:     "that body is 1.56x ATR, therefore conviction"
#:         -> authored by whichever ATR divided it. `snapshot_builder` computes
#:            `calculate_atr(settled)`, a trailing 14-period SMA ending at the
#:            NEWEST settled bar, so the denominator is ASSESSMENT-time. The
#:            anchor may sit up to LOOKBACK-1 bars behind it.
#:
#: A falling ATR can therefore make an OLD body cross the threshold for the
#: first time, and stamping that verdict at the old candle's timestamp would
#: move knowledge backwards through time. So the two are split, and only the
#: physical half keeps the candle's own event_time.
#:
#: STEP 3D — AND THE NOUN CARRIED THE ROLE BACKWARDS TOO.
#:
#: The physical half was first called ANCHOR_CANDLE. Its geometry is a
#: candle-time fact, but "anchor" is a RELATIONSHIP assigned later, when a
#: trailing assessment happened to select it as the largest qualifying body.
#: The same candle is not an anchor before that selection and stops being one
#: when it falls out of the window. Removing the backdated ATR while keeping
#: the backdated noun would have left the defect half-fixed.
#:
#: So the physical object asserts only: this TF bucket printed this geometry at
#: this timestamp. The SELECTION lives on the witness that made it.
CANDLE_REFERENCE = "CANDLE_REFERENCE"
MAGNITUDE_WITNESS = "MAGNITUDE_WITNESS"

#: Repeated window assessments that referenced the SAME conviction candle. The
#: name is long on purpose. It licenses exactly one claim --
#:
#:     "these rolling assessments all pointed at this one candle"
#:
#: -- and NOT "this is the canonical identity of the market's displacement leg",
#: which the producer cannot establish and this module must not imply.
MAGNITUDE_ANCHORED_ASSESSMENT_EPISODE = "MAGNITUDE_ANCHORED_ASSESSMENT_EPISODE"

#: The classifier's own thresholds. NOT epistemic synonyms for possible/confirmed
#: MARKET events -- see the producer docstring.
STATUS_POSSIBLE = "POSSIBLE"
STATUS_CONFIRMED = "CONFIRMED"

#: PRESENCE is a SEPARATE AXIS from attainment. `status = CONFIRMED` alone was
#: made to mean both "this once crossed the threshold" and "this is still here",
#: which is the same scalar-collapse defect temporal quality and continuity each
#: had to be rescued from. Historical attainment is permanent; presence is not.
PRESENCE_ACTIVE = "ACTIVE"
PRESENCE_ENDED = "ENDED"

_CLASSIFICATION_STATUS = {"displacement_confirmed": STATUS_CONFIRMED,
                          "displacement_possible": STATUS_POSSIBLE}

#: STEP 3E §12 — ALL SIX components, not the two that happened to be noticed.
#:
#: The goal is exact truth, not maximal object count. A scalar that fully
#: explains its own component needs no object, and manufacturing one would add
#: ceremony without adding provenance:
#:
#:   EXACT_OBJECT_REFERENCE  the component points at a real derived-fact id
#:   INLINE_SCALAR           the component's value IS its provenance; there is
#:                           no separate market object to reference
#:   INCOMPLETE              a real object exists (or should) and is not linked
_COMPONENT_REFERENCE_PROVENANCE = {
    # threaded in 3E: the witness and the run are real objects with ids
    "displacement_magnitude": "EXACT_OBJECT_REFERENCE",
    "follow_through": "EXACT_OBJECT_REFERENCE",
    # STEP 4B.2: closed. The gaps now carry their exact c1/c2/c3 stamps, so
    # each resolves to its canonical FVG completion slot.
    #
    # EXACT_OBJECT_REFERENCE means "we know exactly WHICH FVG objects this
    # component consulted". It does NOT mean the label `imbalance_created`
    # became causally true -- see `imbalance_semantic_basis`.
    "imbalance_created": "EXACT_OBJECT_REFERENCE",
    # BOS/MSS are canonical MARKET_EVENTS; the assessment carries two booleans.
    "structure_break": "INCOMPLETE",
    # `directional_efficiency` is a single ratio computed by `detect_expansion`
    # over its own window. It has no occurrence and no identity -- it is a
    # measurement, and its value is published inline. Minting an id for it would
    # be ceremony, not provenance.
    "directional_efficiency": "INLINE_SCALAR",
    # Likewise: a share of opposing candles inside the scored window.
    "no_hesitation": "INLINE_SCALAR",
}


def candle_reference_id(tf: str, timestamp, instrument=None, contract=None) -> str:
    """IDENTITY IS THE BUCKET. STEP 3D §2 / 3E §8-§9 / 3F.

    `contract + source_tf + canonical bucket instant` and nothing else.

    Direction was briefly part of this id, which made a repaired close that
    flips bullish->bearish look like a DIFFERENT market object -- and would have
    left the stale one alive beside its own replacement. The 5m bucket at 16:35
    is the same bucket whatever its OHLC turns out to be.

    Identity is not state.
    """
    return market_object_id(CANDLE_REFERENCE,
                            contract=contract or _active_contract(),
                            instrument=instrument, timeframe=tf,
                            instant=timestamp)


def _candle_reference_at(d: dict, tf: str) -> "dict | None":
    """The PHYSICAL half: this TF bucket printed this geometry at this time.

    STEP 3C §2 / 3D §1. Carries OHLC, body and the candle's own open/close
    direction -- every one true at the candle's own timestamp and unchangeable
    by anything later. `event_time` is the candle's own time, correct here
    precisely BECAUSE the object is the candle.

    IT CARRIES NO ATR, NO QUALIFICATION AND NO ROLE. The ATR ratio lives on
    MAGNITUDE_WITNESS stamped when it was computed, and so does the SELECTION --
    "largest qualifying body in the assessment window" is a relationship a later
    window asserted, not something true of the candle when it printed.

    Direction is an ATTRIBUTE here, never identity.
    """
    cc = d.get("conviction_candle")
    if not cc or not cc.get("timestamp"):
        return None
    when = str(cc["timestamp"])
    return {"event_id": candle_reference_id(tf, when),
            "event_type": CANDLE_REFERENCE, "source_tf": tf,
            "epistemic_layer": "MARKET_OBSERVATIONS",
            "species": EVENT_SPECIES[CANDLE_REFERENCE],
            "instrument": _active_contract(),
            "contract_provenance": _active_provenance(),
            "event_time": when, "source_bar": when,
            "bucket_timestamp": when,
            # Direction from the candle's OWN open/close. No vote, no window.
            "direction": cc.get("direction"),
            "open": cc.get("open"), "high": cc.get("high"),
            "low": cc.get("low"), "close": cc.get("close"),
            "body": cc.get("body"),
            "source_bars": [when]}


def _magnitude_witness_at(d: dict, tf: str, observed_at: str,
                          annotated: list = None) -> "dict | None":
    """The DERIVED half: "that body is N x ATR, therefore conviction".

    STEP 3C §1-§3. MEASURED, not assumed: over the Aug-12 replay, 4 of 10
    anchors did NOT clear MAGNITUDE_ATR_MULT against the ATR knowable at their
    own timestamp. The worst was the 5m candle at 16:35 --

        16:35   atr 28.39   body/atr = 1.15   does NOT qualify
        17:14   atr 21.05   body/atr = 1.56   qualifies

    -- the same body, 39 minutes later, promoted by a FALLING ATR. Stamping
    that verdict at 16:35 would have moved knowledge backwards through time.

    So `event_time` is when the ratio was COMPUTED, and the denominator carries
    its own as-of time. A metric without a denominator's provenance is not a
    fact, it is a number.
    """
    cc = d.get("conviction_candle")
    if not cc or not cc.get("timestamp"):
        return None
    anchor = str(cc["timestamp"])
    # WHEN THE JUDGEMENT WAS MADE = the scan that made it, NOT the producer's
    # newest settled bar. On a 5m timeframe those differ by up to five minutes,
    # and taking the settled bar's time would backdate the verdict by exactly
    # the amount this whole step exists to prevent -- a smaller version of the
    # same error. The settled bar is what the ATR RESTS on, and it keeps its own
    # field (`atr_as_of`).
    when = str(observed_at or cc.get("qualified_at") or anchor)
    # STEP 3D §3/§4 — TWO EVIDENCE LEGS.
    #
    #     body / atr = 1.52
    #     ────┬───   ─┬─
    #         │        └── the ATR SOURCE WINDOW
    #         └────────── the selected candle
    #
    # A first version named only the anchor as `source_bars`, which published
    # half a proposition: repair any bar in the ATR window and the ratio moves.
    # Evidence health is therefore computed over BOTH legs -- a clean anchor
    # cannot make a witness settled when its denominator rests on a damaged or
    # discontinuous window.
    atr_bars = list(cc.get("atr_source_candles") or [])
    if annotated and atr_bars:
        known = {_bar_time(c): c for c in annotated}
        atr_bars = [known.get(_bar_time(c)) or c for c in atr_bars]
    atr_stamps = [_bar_time(c) for c in atr_bars] or list(cc.get("atr_source_bars") or [])
    anchor_bar = ({_bar_time(c): c for c in annotated}.get(anchor)
                  if annotated else None) or {}
    atr_continuity = _continuity_fields(atr_bars or atr_stamps, tf)
    # STEP 3E §1/§2 — TWO ROLES, ONE OBSERVATION.
    #
    # The selected candle is usually ALSO a member of the ATR window: pick the
    # largest body in the last ten bars and divide by an ATR whose window ends
    # at the newest of those same bars. Publishing `source_bars = [anchor] +
    # atr_stamps` therefore listed one physical candle twice, produced a
    # duplicated non-monotonic array (the anchor prepended to a chronological
    # window it already sat inside), and inflated the evidence count.
    #
    # Two evidentiary roles never create two market observations. Roles are kept
    # separately; the generic physical list is identity-deduped and ordered.
    anchor_canonical = canonical_instant(anchor)
    atr_canonical = [canonical_instant(s) for s in atr_stamps]
    inside = anchor_canonical in atr_canonical
    unique_stamps = sorted(set(atr_canonical) | {anchor_canonical})
    unique_bars = ([anchor_bar] if anchor_bar and not inside else []) + atr_bars
    return {"event_id": _event_id(MAGNITUDE_WITNESS, tf, when, anchor),
            "event_type": MAGNITUDE_WITNESS, "source_tf": tf,
            "epistemic_layer": "DERIVED_FACTS",
            "species": EVENT_SPECIES[MAGNITUDE_WITNESS],
            # WHEN THE JUDGEMENT WAS MADE, never when the candle printed.
            "event_time": when, "observed_at": when,
            # ── leg 1: the numerator ──
            "selected_candle_id": candle_reference_id(tf, anchor),
            "selected_candle_time": anchor,
            # §1 — the ROLE lives here, on the judgement that assigned it.
            "selection_role": "largest qualifying body in the assessment window",
            "body": cc.get("body"),
            # ── leg 2: the denominator ──
            "atr": cc.get("atr"),
            "atr_multiple": cc.get("atr_multiple"),
            "atr_as_of": cc.get("atr_as_of"),
            "atr_source": cc.get("atr_source"),
            "atr_source_tf": tf,
            "atr_period": cc.get("atr_period"),
            "atr_source_bars": atr_stamps,
            "atr_source_observation_count": len(atr_stamps),
            "atr_temporal_class": _weakest_temporal(atr_bars),
            "atr_continuity_class": atr_continuity["source_continuity_class"],
            "atr_continuity_issues": atr_continuity["source_continuity_issues"],
            "atr_source_gaps": atr_continuity["source_gaps"],
            # The newest SETTLED bar the producer scored. <= observed_at, and on
            # a higher timeframe strictly less.
            "producer_settled_through": cc.get("qualified_at"),
            "threshold_atr_multiple": cc.get("threshold_atr_multiple"),
            "evidence_is_older_than_judgement": anchor != when,
            # ── role provenance: which leg each source served ──
            "numerator_source_bar": anchor_canonical,
            "denominator_source_bars": atr_canonical,
            "numerator_is_inside_atr_window": inside,
            "logical_evidence_reference_count": 1 + len(atr_canonical),
            "unique_physical_observation_count": len(unique_stamps),
            # ── aggregate: BOTH legs, never the anchor alone ──
            "temporal_class": _weakest_temporal(unique_bars),
            **_evidence_summary([_temporal(c) for c in unique_bars]),
            # GENERIC PHYSICAL EVIDENCE: unique identities, chronological.
            "source_bars": unique_stamps,
            "source_bar": anchor_canonical}


def _follow_through_run_at(d: dict, tf: str, observed_at: str,
                           annotated: list = None) -> "dict | None":
    """The consecutive-candle run as a ROLLING OBSERVATION, not an event.

    STEP 3B §4C, audited: `_follow_through` reads `window[-1]`'s direction and
    walks backwards, so the run it reports is recomputed from scratch on every
    bar and grows, shrinks or flips as the newest candle changes. That is a
    CURRENT STATE, exactly like the persistent BOS condition -- forcing event
    identity onto it would repeat the mistake this whole step exists to undo.

    So it is published as an observation stamped with when it was observed.
    """
    direction, run = d.get("follow_through_observed_direction"), d.get("follow_through_run")
    if not direction or not run:
        return None
    # STEP 3C §4 — THE EXACT RUN BARS, not the newest one and not the whole
    # 10-bar assessment window. A four-candle run is a claim about four
    # observations, and publishing `run_length: 4` beside a single source bar
    # let the evidence for a multi-bar fact vanish -- the same defect swing
    # provenance had before 2C. Observation count may never masquerade as
    # evidence provenance.
    candles = d.get("follow_through_run_candles") or []
    stamps = [str(t) for t in (d.get("follow_through_run_bars") or []) if t]
    # The producer receives `settled` STRAIGHT FROM `build_timeframes`, which
    # emits `complete`/`members` but never `temporal_status`. Reading the run
    # candles as handed back therefore made every single run report `unknown`
    # temporal evidence -- 970/970 measured, which looked like a market finding
    # and was a plumbing artifact. The labels are recovered from the annotated
    # series by timestamp; `annotate_temporal` stays the single owner of the
    # rule, so nothing is re-derived here.
    if annotated:
        known = {_bar_time(c): c for c in annotated}
        candles = [known.get(s) or c for s, c in zip(stamps, candles)]
    out = {"event_id": _event_id(FOLLOW_THROUGH_RUN, tf, observed_at, direction, run),
            "event_type": FOLLOW_THROUGH_RUN, "source_tf": tf,
            "epistemic_layer": "DERIVED_FACTS",
            "species": EVENT_SPECIES[FOLLOW_THROUGH_RUN],
            "event_time": observed_at, "observed_at": observed_at,
            "direction": direction,
            # STEP 3D §6/§7 — ARRAY ADJACENCY IS NOT MARKET CONTINUITY.
            #
            # Measured: 32 multi-bar runs on the real tape hold a venue-open
            # bucket with no observation between their members. The producer's
            # claim is unchanged and untuned, but the Brain-facing noun is no
            # longer the bare "N consecutive candles" -- what it observed is N
            # same-direction ARRAY NEIGHBOURS, and whether those neighbours were
            # market-contiguous is a separate published fact.
            "observed_run_length": run,
            "run_length": run,              # compatibility, same number
            "array_adjacent": True,
            "market_continuity": None,      # filled from the run's own evidence
            "voted": bool(d.get("follow_through_direction")),
            "vote_threshold": _FOLLOW_THROUGH_AT(),
            "source_bars": stamps,
            # §6 — temporal quality of the RUN's own bars.
            "temporal_class": _weakest_temporal(candles),
            **_evidence_summary([_temporal(c) for c in candles]),
            # §5 — continuity of the RUN's own bars. Three array-neighbours
            # separated by an absent venue-open bucket are still reported by the
            # producer as a three-candle run; that stays true, and the
            # discontinuity is published beside it rather than instead of it.
            **_continuity_fields(candles or stamps, tf),
            "source_bar": stamps[-1] if stamps else observed_at}
    out["market_continuity"] = out["source_continuity_class"]
    # A one-bar run has no interval to assess -- that is not a defect, and it
    # must not read as one.
    out["market_continuity_assessable"] = run >= 2
    return out


def _FOLLOW_THROUGH_AT():
    from structure.displacement_detector import FOLLOW_THROUGH_AT
    return FOLLOW_THROUGH_AT


def _independent_direction(d: dict) -> tuple:
    """(direction, conflicted) from INDEPENDENT witnesses only.

    STEP 4B.3 §5. Only `_magnitude` and `_follow_through` name a side from price
    without being handed one first. `_imbalance` is excluded because it returns
    the leg it was given. NONE is a legitimate answer and is never forced into a
    direction -- "no independent answer" and "an opposing independent answer"
    are different facts.
    """
    from structure.direction_vote import resolve_direction_vote
    return resolve_direction_vote([w for w in (d.get("magnitude_direction"),
                                               d.get("follow_through_direction")) if w])


def _displacement_at(snapshot: dict, series: list, tf: str, *,
                     observed_at: str = None) -> "dict | None":
    """ONE ROLLING MECHANICAL ASSESSMENT, honestly labelled. Never an occurrence.

    Everything factual is taken from the producer's own published fields rather
    than recomputed here -- the previous version rebuilt the window with
    `series[-look:]` and published its left edge as `start_time`, inventing a
    leg start the detector never claimed.

    DIRECTION IS INTRINSIC, verified voter by voter: `_magnitude` names the side
    from the largest-BODY candle's own OHLC and `_follow_through` from
    consecutive candle directions, while `_structure_break`, `_efficiency` and
    `_no_hesitation` all return direction `None`. No BOS, no structure bias, no
    mechanical recommendation and no Terra direction reaches it.
    """
    d = ((snapshot.get("expansion") or {}).get(tf) or {}).get("displacement") or {}
    status = _CLASSIFICATION_STATUS.get(d.get("classification"))
    if status is None:
        return None
    # STEP 4B.12 §3 — A PUBLISHED REF CARRIES EVIDENCE-PROVEN SCOPE, OR NONE.
    #
    # The first version read `_contract_in(series) or _active_contract()`, and
    # that `or` was the whole defect. Measured: a contractless series inside a
    # `CON.F.US.MES.U26` ambient scope minted
    #
    #     FVG:CON.F.US.MES.U26:1m:2026-08-12T17:02:00+00:00
    #
    # on zero source evidence -- a flawless-looking canonical reference whose
    # instrument came from surrounding execution state, not from the bars.
    #
    # ContextVar solved CONCURRENCY. It never made ambient scope evidentiary
    # authority. Those are different questions, and published provenance answers
    # the second one.
    #
    # `_contract_in` still refuses mixed, partial and self-contradicting source
    # rows, so a value here is unanimous across the series that produced it.
    # When the series proves nothing, no exact reference is published at all --
    # a named absence beats a confident wrong id.
    _ref_contract = _contract_in(series)
    _refs_publishable = _ref_contract is not None
    look = int(d.get("lookback") or 0) or 1
    window = [c for c in series
              if str(c.get("temporal_status") or "settled") != "forming"][-look:]
    when = observed_at or d.get("window_end_time") or _bar_time(window[-1] if window else {})
    anchor = d.get("magnitude_anchor_time")
    return {
        # AN ASSESSMENT IS IDENTIFIED BY WHEN IT WAS MADE. Two assessments of
        # the same anchor at different times are two different assessments and
        # must not collide. `event_time` is `observed_at` and NEVER the anchor
        # candle's time -- borrowing that would date mechanical opinion to
        # before the mechanics had formed it.
        "event_id": _event_id(DISPLACEMENT_ASSESSMENT, tf, when, anchor or "unanchored"),
        "event_type": DISPLACEMENT_ASSESSMENT, "source_tf": tf,
        "epistemic_layer": "DERIVED_ASSESSMENTS",
        "event_time": when, "observed_at": when,
        # THE CLASSIFIER'S OPINION, labelled as such.
        "status": status, "classification": d.get("classification"),
        "classification_is_mechanical_opinion": True,
        "score": d.get("score"),
        # WHY IT SCORED WHAT IT SCORED (§5) -- and how far that goes (3C §9).
        #
        # SCORE PROVENANCE is COMPLETE: every component's points, threshold and
        # underlying value are here, so the arithmetic is fully reconstructible.
        #
        # EXACT EVENT-REFERENCE PROVENANCE is NOT. `structure_evidence` is two
        # booleans, not the BOS/MSS event IDs that supplied them, and the gaps
        # are the producer's own geometry rather than canonical FVG object
        # references. Both are real debts, named rather than papered over with
        # fabricated IDs. Step 4 closes the FVG side.
        "components": d.get("components"),
        "imbalance_gaps": d.get("imbalance_gaps") or [],
        "imbalance_semantic_basis": d.get("imbalance_semantic_basis"),
        "imbalance_direction_role": d.get("imbalance_direction_role"),
        "imbalance_conditioned_on_leg": d.get("imbalance_conditioned_on_leg"),
        # §24: BOTH-side inventory. A handed legacy direction may not hide
        # opposite-side physical FVG facts from the reader.
        "fvg_bullish_count": d.get("fvg_bullish_count"),
        "fvg_bearish_count": d.get("fvg_bearish_count"),
        "imbalance_opposite_side_count": d.get("imbalance_opposite_side_count"),
        "imbalance_directionally_permissive": d.get("imbalance_directionally_permissive"),
        "fvg_bullish_refs": [_event_id(FVG, tf, g["c3_time"], contract=_ref_contract)
                             if (g.get("c3_time") and _refs_publishable) else None
                             for g in (d.get("fvg_bullish_gaps") or [])],
        "fvg_bearish_refs": [_event_id(FVG, tf, g["c3_time"], contract=_ref_contract)
                             if (g.get("c3_time") and _refs_publishable) else None
                             for g in (d.get("fvg_bearish_gaps") or [])],
        "ref_contract": _ref_contract,
        "ref_contract_provenance": (EVIDENCE_DERIVED if _refs_publishable
                                    else "NO_SOURCE_CONTRACT_EVIDENCE"),
        "exact_refs_publishable": _refs_publishable,
        "imbalance_semantic_note": d.get("imbalance_semantic_note"),
        "structure_evidence": d.get("structure_evidence") or {},
        "directional_efficiency": d.get("directional_efficiency"),
        "score_arithmetic_provenance": "COMPLETE",
        "component_event_reference_provenance": (
            "INCOMPLETE" if any(v == "INCOMPLETE"
                                for v in _COMPONENT_REFERENCE_PROVENANCE.values())
            else "COMPLETE"),
        "component_reference_provenance": dict(_COMPONENT_REFERENCE_PROVENANCE),
        # §11 — the exact derived-fact objects THIS assessment leaned on. They
        # existed but were left dangling: building provenance objects and then
        # not connecting them to the score that used them is half a job.
        "magnitude_witness_ref": (
            _event_id(MAGNITUDE_WITNESS, tf, when, anchor) if anchor else None),
        "follow_through_run_ref": (
            _event_id(FOLLOW_THROUGH_RUN, tf, when,
                      d.get("follow_through_observed_direction"),
                      d.get("follow_through_run"))
            if d.get("follow_through_observed_direction") else None),
        "structure_event_refs": None,     # debt, named rather than fabricated
        # STEP 4B.2 §9 — EXACT, resolved from each gap's own c3 completion
        # bucket. Not by direction, not by timeframe alone, not by price
        # proximity, not by family. A gap whose source stamps are missing gets
        # None rather than a guess.
        #
        # §10 — these name WHICH FVG objects the legacy component consulted.
        # They do NOT make its "created" label causally true: `_imbalance` scans
        # the whole trailing window, so a referenced gap may predate this leg
        # entirely. `imbalance_semantic_basis` stays beside them.
        "imbalance_event_refs": [
            _event_id(FVG, tf, g["c3_time"], contract=_ref_contract)
            if (g.get("c3_time") and _refs_publishable) else None
            for g in (d.get("imbalance_gaps") or [])],
        # §9: THE CARDINALITY THEOREM, MADE EXECUTABLE.
        #
        # "same completion bucket therefore same FVG" is what the theorem
        # PREDICTS. Publishing the full producer triple lets a consumer ASSERT
        # it against the canonical object's c1/c2/c3 instead of trusting it --
        # and a mismatch is then a loud failure rather than a silent wrong ref.
        "imbalance_ref_triples": [
            {"ref": (_event_id(FVG, tf, g["c3_time"], contract=_ref_contract)
                     if (g.get("c3_time") and _refs_publishable) else None),
             "c1_time": g.get("c1_time"), "c2_time": g.get("c2_time"),
             "c3_time": g.get("c3_time")}
            for g in (d.get("imbalance_gaps") or [])],
        "event_reference_gaps": [k for k, v in _COMPONENT_REFERENCE_PROVENANCE.items()
                                 if v == "INCOMPLETE"],
        # THE OCCURRENCE ANCHOR, or None. Without it this reading cannot be tied
        # to any market object and can never be promoted to an occurrence.
        "anchor_time": anchor, "anchor_body": d.get("magnitude_anchor_body"),
        "anchored": anchor is not None,
        # The scored span is a detector artefact. Named as one.
        "window_start_time": d.get("window_start_time"),
        "window_end_time": d.get("window_end_time"),
        "window_is_trailing_artifact": True,
        "lookback_bars": d.get("lookback"),
        # DIRECTION: consensus and net travel, side by side, unreconciled.
        "direction": d.get("direction"),
        "direction_vote": d.get("direction_vote"),
        "direction_basis": d.get("direction_basis"),
        "direction_conflicted": bool(d.get("direction_conflicted")),
        "direction_consistency": d.get("direction_consistency"),
        "net_travel": d.get("net_travel"),
        "net_travel_direction": d.get("net_travel_direction"),
        "magnitude_direction": d.get("magnitude_direction"),
        "follow_through_direction": d.get("follow_through_direction"),
        "follow_through_observed_direction": d.get("follow_through_observed_direction"),
        "follow_through_run": d.get("follow_through_run"),
        "directional_witnesses": d.get("directional_witnesses") or {},
        "witnesses_conflict": bool(d.get("witnesses_conflict")),
        "imbalance_vote_echoes_leg": d.get("imbalance_vote_echoes_leg"),
        "leg_direction": d.get("leg_direction"),
        "leg_provenance": d.get("leg_provenance"),
        # §5: the legacy result and the independent evidence, side by side.
        # `independent_witness_direction` is NONE when independent evidence has
        # no answer -- which is a different fact from an opposing answer.
        "legacy_component_direction": d.get("direction"),
        "independent_witness_direction": _independent_direction(d)[0],
        "independent_witness_conflict": _independent_direction(d)[1],
        "independent_directional_witnesses": [
            w for w in (d.get("magnitude_direction"),
                        d.get("follow_through_direction")) if w],
        "magnitude_atr": d.get("magnitude_atr"),
        "imbalance_count": d.get("imbalance_count"),
        # Substrate recomputed from THIS reading's exact evidence window.
        "temporal_class": _weakest_temporal(window),
        **_evidence_summary([_temporal(c) for c in window]),
        **_continuity_fields(window, tf),
        "source_bars": [_bar_time(c) for c in window],
        "source_bar": when,
    }


def _status_transitions(seq: list) -> list:
    """Only the readings where the reported state actually CHANGED."""
    out, prev = [], object()
    for s in seq:
        now = (s.get("status"), s.get("direction"), s.get("direction_consistency"))
        if now == prev:
            continue
        prev = now
        out.append({"observed_at": s.get("observed_at"), "status": s.get("status"),
                    "score": s.get("score"), "direction": s.get("direction"),
                    "direction_consistency": s.get("direction_consistency")})
    return out


SEGMENTED_ON_OPPORTUNITY = "ASSESSMENT_OPPORTUNITY"
SEGMENTED_ON_OUTPUT_ONLY = "OBSERVED_OUTPUT_ONLY"


def fold_displacement_occurrences(observations: list, *,
                                  final_observed_at: str = None,
                                  opportunity_slots: dict = None) -> list:
    """Rolling assessments -> MAGNITUDE-ANCHORED ASSESSMENT EPISODES.

    NOT displacement occurrences. STEP 3B: identity here licenses exactly one
    claim -- that these repeated window assessments all referenced the same
    conviction candle. It does NOT establish that the market performed one
    displacement leg with that identity, which the producer cannot know.

    IDENTITY = (source_tf, magnitude_anchor_time). The window's edges slide, the
    score drifts and the classification is a threshold crossing, so none of
    those may mint identity.

    A reading with no anchor is NOT promoted. It stays a perfectly usable
    assessment and makes no claim about a market object at all -- 89% of real
    readings are in that class, and inventing an anchor for them (from the FVG
    geometry, say) would be fake precision: an FVG is a real object but is not
    the identity of the move that produced it.

    TWO ORTHOGONAL AXES (§8).

        ever_confirmed / highest_classification / confirmed_at
            HISTORICAL ATTAINMENT. Permanent. A later drop to POSSIBLE does not
            erase that the threshold was once crossed.

        currently_observed / presence_state / last_observed_at
            CURRENT PRESENCE. Not permanent. An episode that stopped being
            reported is ENDED, whatever it once attained.

    Collapsing those into one `status = CONFIRMED` made it read as "currently
    confirmed displacement" long after reporting stopped.

    CONFIRMATION IS NEVER BACKDATED. `confirmed_at` is the time confirmation was
    first OBSERVED, not the anchor candle's timestamp -- the engine did not know
    at the anchor bar what it learned four bars later.
    """
    # STEP 3G §7/§8 — ABSENCE INSIDE A LIFECYCLE MAY NOT MASQUERADE AS
    # CONTINUITY.
    #
    # Magnitude qualification is `body / CURRENT ATR >= 1.5`, and the ATR moves
    # every scan while the body never does. So one selected candle can qualify,
    # stop qualifying as ATR rises, and qualify again as ATR falls -- all while
    # it is still inside LOOKBACK. Grouping purely by anchor would then publish
    #
    #     T0 present, T1 present, T2 ABSENT, T3 present
    #
    # as one uninterrupted episode spanning T0->T3. That is the same continuity
    # lie as a "3-candle run" assembled across a missing bucket.
    #
    # MODEL B: SEGMENTATION. The episode id already carries
    # `first_observed_at`, and the ontology is "the RUN of assessments that
    # referenced this candle" -- an interrupted run is two runs. A gap is
    # detected against the timeframe's OWN assessment timeline (every scan that
    # produced any reading), so "absent" means the engine looked and did not
    # report it, never merely that no scan happened.
    # STEP 3H — SEGMENT AGAINST OPPORTUNITY, NOT OUTPUT.
    #
    # 3G derived this timeline from `observations`, which holds only POSITIVE
    # readings. A scan whose classifier returned "none" left no entry, so
    #
    #     T0 anchor A   T1 detector ran, said nothing   T2 anchor A
    #
    # read as T0 adjacent to T2 and stayed one unbroken episode -- while T1 is
    # the STRONGEST evidence the anchor was absent. The caller now supplies the
    # ledger of scans at which each timeframe's detector was actually
    # evaluated.
    if opportunity_slots:
        basis = SEGMENTED_ON_OPPORTUNITY
        timeline = {tf: set(str(t) for t in ts)
                    for tf, ts in opportunity_slots.items()}
    else:
        # No ledger: absence cannot be proven, and saying so is better than
        # quietly segmenting on a timeline that omits the silent scans.
        basis = SEGMENTED_ON_OUTPUT_ONLY
        timeline = {}
        for o in observations or []:
            timeline.setdefault(o.get("source_tf"), set()).add(str(o.get("observed_at")))
    positions = {tf: {t: i for i, t in enumerate(sorted(ts))}
                 for tf, ts in timeline.items()}

    grouped = {}
    for o in observations or []:
        if o.get("anchored"):
            grouped.setdefault((o.get("source_tf"), o.get("anchor_time")), []).append(o)

    by_key, order = {}, []
    for (tf, anchor), rows in grouped.items():
        rows.sort(key=lambda x: str(x.get("observed_at")))
        seats = positions.get(tf, {})
        segment, previous_seat = 0, None
        for o in rows:
            seat = seats.get(str(o.get("observed_at")))
            # A HOLE: the engine ran between these two readings and did NOT
            # report this anchor. That interruption ends one episode.
            if (previous_seat is not None and seat is not None
                    and seat - previous_seat > 1):
                segment += 1
            previous_seat = seat
            key = (tf, anchor, segment)
            if key not in by_key:
                by_key[key] = []
                order.append(key)
            by_key[key].append(o)

    out = []
    for key in order:
        seq = sorted(by_key[key], key=lambda x: str(x.get("observed_at")))
        tf, anchor, segment = key
        first, last = seq[0], seq[-1]
        confirmed = next((s for s in seq if s.get("status") == STATUS_CONFIRMED), None)
        # AXIS 1 — historical attainment. Permanent.
        highest = STATUS_CONFIRMED if confirmed is not None else STATUS_POSSIBLE
        # AXIS 2 — current presence. Independent of what was once attained.
        still_here = not (final_observed_at
                          and str(last.get("observed_at")) < str(final_observed_at))
        out.append({
            # STEP 3F §9 — THE ONE PLACE THE SELECTED CANDLE IS IDENTITY.
            # This object's whole ontology is "the run of assessments that
            # referenced THIS candle", so the candle is what distinguishes one
            # episode from another and the producer can hold several at once
            # per (tf, instant). On an individual assessment the same candle is
            # merely the answer, which is why it is state there and identity
            # here. `instant` is the episode's first observation; the anchor
            # rides as an immutable discriminator.
            "occurrence_id": market_object_id(
                MAGNITUDE_ANCHORED_ASSESSMENT_EPISODE,
                contract=_active_contract(), timeframe=tf,
                instant=first.get("observed_at"),
                discriminators=(canonical_instant(anchor),)),
            # §8: which run of assessments this is for that candle. 0 unless
            # the anchor stopped being reported and later came back.
            "episode_segment": segment,
            "segmented_from_earlier_episode": segment > 0,
            # §3: WHAT absence was measured against. A caller with no
            # opportunity ledger cannot prove absence, and the object says so
            # rather than implying a rigour it does not have.
            "segmentation_basis": basis,
            "event_type": MAGNITUDE_ANCHORED_ASSESSMENT_EPISODE, "source_tf": tf,
            "epistemic_layer": "DERIVED_ASSESSMENTS",
            # §10 — NOT the anchor time. The episode is a run of mechanical
            # assessments, and it began when the first one was MADE. The anchor
            # candle keeps its own time on its own CANDLE_REFERENCE event.
            "event_time": first.get("observed_at"),
            "anchor_time": anchor, "anchor_body": first.get("anchor_body"),
            "selected_candle_id": candle_reference_id(tf, str(anchor)),
            # ── attainment ──
            "highest_classification": highest,
            "ever_confirmed": confirmed is not None,
            "confirmed_at": (confirmed or {}).get("observed_at"),
            # ── presence ──
            "currently_observed": still_here,
            "presence_state": PRESENCE_ACTIVE if still_here else PRESENCE_ENDED,
            "current_classification": last.get("status"),
            "first_observed_at": first.get("observed_at"),
            "last_observed_at": last.get("observed_at"),
            "observation_count": len(seq),
            # §9: the FINAL endpoint is not enough. An episode that vanished
            # mid-life and returned must not read as one unbroken stretch, so
            # the run is proven contiguous against the timeframe's own
            # assessment timeline rather than merely spanning first->last.
            "observation_run_is_contiguous": True,
            # THE FACTUAL STATE-TRANSITION HISTORY. Four POSSIBLE readings and a
            # CONFIRMED one are one object's history, never five events. Only
            # CHANGES are listed -- an unchanged restatement is preserved in
            # `observation_count`, not repeated as a transition.
            "status_history": _status_transitions(seq),
            # Current canonical state = the LATEST reading. Earlier readings are
            # preserved above rather than overwritten.
            **{k: last.get(k) for k in
               ("direction", "direction_vote", "direction_basis",
                "direction_conflicted", "direction_consistency", "net_travel",
                "net_travel_direction", "magnitude_direction",
                "follow_through_direction", "follow_through_observed_direction",
                "follow_through_run", "directional_witnesses",
                "witnesses_conflict", "imbalance_vote_echoes_leg",
                "magnitude_atr", "imbalance_count", "score", "classification",
                "temporal_class", "evidence_temporal_classes",
                "all_evidence_settled", "evidence_schema_errors",
                "source_continuity_class", "source_continuity_issues",
                "source_observation_count", "source_elapsed_minutes",
                "source_gaps", "source_bars")},
        })
    return sorted(out, key=lambda e: (str(e["event_time"]), e["source_tf"],
                                      e["occurrence_id"]))


#: STEP 3B §15 — the epistemic species a reader must never confuse.
#: STEP 3C §7 — plus the one for things we cannot classify at all.
#: STEP 3E §4 — plus the one that was missing, which was distorting the rest.
#:
#: Three layers forced deterministic ARITHMETIC into MARKET_OBSERVATIONS. The
#: venue never printed "1.52x ATR" or "a run of 3"; mechanics computed both from
#: candles. Stretching the word "observation" over them blurred the exact line
#: the whole rebuild exists to draw:
#:
#:   MARKET_OBSERVATIONS   what the venue printed          candle OHLCV
#:   MARKET_EVENTS         occurrences derived by a        sweep, BOS/MSS, FVG
#:                         detector from observations
#:   DERIVED_FACTS         deterministic propositions      body/ATR ratio,
#:                         mechanics can PROVE             run length, continuity
#:   DERIVED_ASSESSMENTS   weighted interpretation         displacement score
#:
#: The middle two are both derived, but an EVENT says "this happened at this
#: price" while a FACT says "this quantity has this value". A DERIVED_FACT can
#: be recomputed from the same observations forever; a MARKET_EVENT is anchored
#: to a moment. Neither is opinion, and neither is raw.
EPISTEMIC_LAYERS = ("MARKET_OBSERVATIONS", "MARKET_EVENTS", "DERIVED_FACTS",
                    "DERIVED_ASSESSMENTS", "UNCLASSIFIED")

#: EXHAUSTIVE REGISTRY. Every event type this module can emit is named here
#: exactly once, and anything absent is a SCHEMA failure rather than a member of
#: whichever layer happened to be the fallback.
#:
#: The first version routed known facts and known observations, then swept
#: `else` into DERIVED_ASSESSMENTS. A typo (`CONVICTON_CANDLE`) or a newly added
#: factual type nobody registered would have been silently relabelled as
#: mechanical opinion -- the exact defect `_normalise_state` already had to be
#: rescued from, where `.get(s, 2)` let a malformed string wear the costume of
#: epistemic humility. Unknown schema is not mechanical opinion.
EVENT_LAYER_REGISTRY = {
    # WHAT THE VENUE PRINTED. STEP 3E §3: a candle does NOT become a market
    # event because a later assessment happened to select it. It printed whether
    # any detector ever cared. Promoting it to MARKET_EVENTS put an ordinary
    # observation in the same species as a sweep, and made the chronology's
    # factual layer a function of what mechanics noticed.
    CANDLE_REFERENCE: "MARKET_OBSERVATIONS",
    # OCCURRENCES a detector derived: exact geometry, own identity, own time
    LIQUIDITY_SWEEP: "MARKET_EVENTS",
    BOS: "MARKET_EVENTS",
    MSS: "MARKET_EVENTS",
    FVG: "MARKET_EVENTS",
    # DETERMINISTIC PROPOSITIONS. Not printed, not opinion -- computed, and
    # recomputable to the same value forever from the same observations.
    MAGNITUDE_WITNESS: "DERIVED_FACTS",
    FOLLOW_THROUGH_RUN: "DERIVED_FACTS",
    # mechanical opinion
    DISPLACEMENT_ASSESSMENT: "DERIVED_ASSESSMENTS",
    MAGNITUDE_ANCHORED_ASSESSMENT_EPISODE: "DERIVED_ASSESSMENTS",
}

#: What each registered type actually IS, so the classification is auditable
#: rather than implied by which bucket it fell into.
EVENT_SPECIES = {
    CANDLE_REFERENCE: "RAW OBSERVATION (canonical timeframe bucket)",
    LIQUIDITY_SWEEP: "ATOMIC MARKET EVENT (pierce + close-back at a level)",
    BOS: "ATOMIC MARKET EVENT (structural break of a confirmed swing)",
    MSS: "ATOMIC MARKET EVENT (break against prevailing bias)",
    FVG: "ATOMIC MARKET EVENT (three-candle geometric imbalance)",
    MAGNITUDE_WITNESS: "DERIVED FACT (body / ATR ratio + threshold predicate)",
    FOLLOW_THROUGH_RUN: "DERIVED FACT (same-direction array run + continuity)",
    DISPLACEMENT_ASSESSMENT: "MECHANICAL ASSESSMENT (weighted confluence score)",
    MAGNITUDE_ANCHORED_ASSESSMENT_EPISODE: "MECHANICAL ASSESSMENT (episode fold)",
}

UNCLASSIFIED = "UNCLASSIFIED"


class UnregisteredEventType(ValueError):
    """An event type with no epistemic layer. A CODE defect, never a market fact."""


def layered_chronology(events: list, *, strict: bool = True) -> dict:
    """Split a mixed stream into its epistemic layers, exhaustively.

    A SWEEP, a BOS, an FVG and a CANDLE_REFERENCE are physical occurrences. A
    FOLLOW_THROUGH_RUN and a MAGNITUDE_WITNESS are current states. A
    DISPLACEMENT_ASSESSMENT is mechanical opinion. Presenting all three as one
    undifferentiated chronology is what let `displacement_confirmed` read like a
    market fact, so the split is structural rather than a naming convention a
    caller may ignore.

    `strict=True` (the default) RAISES on an unregistered type. `strict=False`
    routes it to UNCLASSIFIED so a diagnostic caller can see everything at once
    -- but it never lands in a real layer either way.
    """
    out = {k: [] for k in EPISTEMIC_LAYERS}
    for e in events or []:
        t = e.get("event_type")
        layer = EVENT_LAYER_REGISTRY.get(t)
        if layer is None:
            if strict:
                raise UnregisteredEventType(
                    f"event_type {t!r} has no epistemic layer; register it in "
                    f"EVENT_LAYER_REGISTRY rather than letting it default")
            layer = UNCLASSIFIED
        # STEP 3D §9 — THE OBJECT'S OWN CLAIM MUST AGREE WITH THE REGISTRY.
        #
        # Objects publish `epistemic_layer` themselves. Routing by the registry
        # and ignoring a contradictory field would let the router quietly REPAIR
        # a producer that emits `event_type=FVG, epistemic_layer=DERIVED_
        # ASSESSMENT` -- normalising away exactly the schema defect that needs
        # to surface. Contradiction is reported, never smoothed.
        declared = e.get("epistemic_layer")
        if declared and layer is not UNCLASSIFIED and declared != layer:
            if strict:
                raise UnregisteredEventType(
                    f"event_type {t!r} is registered as {layer} but the object "
                    f"declares epistemic_layer={declared!r}")
            layer = UNCLASSIFIED
        out[layer].append(e)
    for layer in out.values():
        layer.sort(key=lambda e: (str(e.get("event_time")), str(e.get("source_tf")),
                                  str(e.get("event_id") or e.get("occurrence_id"))))
    return out


def reconstruct_displacement(candles_1m: list, timeframes: tuple = ("1m", "3m", "5m", "15m"),
                             *, lookback_bars: int = 90, contract=None) -> dict:
    """Replay displacement through the REAL production pipeline.

    Returns BOTH ontologies explicitly:

        {"observations": [...], "occurrences": [...], "unanchored": N}

    A dict rather than a list on purpose -- every caller must now name which one
    it wants, so no future reader can mistake a rolling assessment for a market
    event the way the first version's flat list invited.

    `detect_displacement` needs a settled ATR and the expansion block, both of
    which `build_snapshot` owns. Recomputing them here would be a second
    interpretation of the producer, so the snapshot is rebuilt per bar instead --
    strictly no-lookahead, `candles_1m[:i+1]` only.

    Slower than the candle-only detectors (~0.2s per bar) and therefore an
    OFFLINE reconstruction tool. Live production already computes displacement
    once per scan inside `build_snapshot`; nothing here runs in that path.
    """
    from data_feed.timeframe_builder import build_timeframes
    from market_data.snapshot_builder import build_snapshot

    if contract or not _active_contract():
        resolved, prov = resolve_contract(candles_1m, contract,
                                          where="reconstruct_displacement")
        with contract_scope(resolved, provenance=prov):
            return reconstruct_displacement(candles_1m, timeframes,
                                            lookback_bars=lookback_bars)
    observations, last_seen, slots = [], None, {}
    conviction, witnesses, runs, seen_ids = [], [], [], set()
    n = len(candles_1m or [])
    if n == 0:
        return {"observations": [], "occurrences": [], "unanchored": 0,
                "candle_references": [], "magnitude_witnesses": [],
                "follow_through_runs": []}
    start = max(0, n - int(lookback_bars))
    for i in range(start, n):
        history = candles_1m[:i + 1]          # <= T, never the full tape
        if len(history) < 20:
            continue
        tfs = build_timeframes(history)
        snap = build_snapshot(tfs, symbol="MNQ")
        observed_at = _bar_time(history[-1])
        last_seen = observed_at
        for tf in timeframes:
            series = annotate_temporal(tfs.get(tf) or [], tf)
            d_block = ((snap.get("expansion") or {}).get(tf) or {}).get("displacement")
            obs = _displacement_at(snap, series, tf, observed_at=observed_at)
            # NOT DEDUPED, DELIBERATELY. A rolling assessment restated on the
            # next bar IS a second assessment -- "at 18:56 the engine still saw
            # this" is a fact, and the transition dedupe used for BOS would
            # destroy it. Collapsing an unchanged run here also silently broke
            # EXPIRED detection, which needs to know the LAST bar a reading
            # still stood. The collapsing belongs one layer up, where anchors
            # turn readings into occurrences.
            # STEP 3H — THE OBSERVATION-OPPORTUNITY LEDGER.
            #
            # `observations` only ever receives a POSITIVE reading: when the
            # classifier says "none", `_displacement_at` returns None and this
            # scan leaves no trace. A timeline built from that list therefore
            # cannot distinguish
            #
            #     T1 the detector ran and reported nothing
            #     T1 the detector never ran
            #
            # and the 3G segmentation was built on exactly that list -- so it
            # still bridged an absence whenever the intervening scan produced no
            # displacement at all. That is the same defect as the halt-window
            # denominator: silence is evidence only when there was an
            # opportunity to speak.
            #
            # The detector ran for this timeframe iff `build_snapshot` published
            # a displacement block for it, so THAT is what is recorded -- never
            # inferred from whether the block said anything interesting.
            if isinstance(d_block, dict):
                slots.setdefault(tf, []).append(observed_at)
            if obs is not None:
                observations.append(obs)
            # ATOMIC FACTS, emitted alongside but NEVER folded into the opinion.
            d = d_block or {}
            cc = _candle_reference_at(d, tf)
            # ONE-SHOT: the same candle stays the largest body for many bars,
            # but it only PRINTED once. Deduped on its own identity, which is
            # the candle's timestamp -- not on the bar that noticed it.
            if cc and cc["event_id"] not in seen_ids:
                seen_ids.add(cc["event_id"])
                conviction.append(cc)
            # The QUALIFICATION is a separate, later, repeatable observation.
            mw = _magnitude_witness_at(d, tf, observed_at, series)
            if mw:
                witnesses.append(mw)
            run = _follow_through_run_at(d, tf, observed_at, series)
            if run:
                runs.append(run)
    observations.sort(key=lambda e: (e["event_time"], e["source_tf"], e["event_id"]))
    conviction.sort(key=lambda e: (e["event_time"], e["source_tf"], e["event_id"]))
    return {"observations": observations,
            "occurrences": fold_displacement_occurrences(
                observations, final_observed_at=last_seen,
                opportunity_slots=slots),
            "assessment_opportunities": {k: list(v) for k, v in slots.items()},
            "unanchored": sum(1 for o in observations if not o.get("anchored")),
            "candle_references": conviction,
            "magnitude_witnesses": witnesses,
            "follow_through_runs": runs}
