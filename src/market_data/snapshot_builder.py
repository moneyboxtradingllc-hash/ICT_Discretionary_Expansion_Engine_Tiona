from datetime import datetime, timezone
from market_data.candle_normalizer import normalize_candles
from market_data.object_identity import canonical_instant
from market_data.session_engine import get_session_label
from structure.structure_engine import analyze_structure, compute_alignment
from structure.liquidity_engine import analyze_liquidity
from volatility.atr_engine import calculate_atr
from volatility.volatility_classifier import classify_volatility
from volatility_authority.volatility_authority import compose_authority
from volatility.expansion_detector import detect_expansion
from structure.po3_engine import analyze_po3_snapshot, reconcile_phase
from structure.manipulation_detector import detect_manipulation
from structure.displacement_detector import detect_displacement

#: STEP 4B.5 — minutes per timeframe, so FVG source triples can be checked for
#: canonical market adjacency rather than mere array adjacency.
_TF_MINUTES_4B5 = {"1m": 1, "3m": 3, "5m": 5, "15m": 15}
from structure.market_context import analyze_market_context
from regime_classification.structure_hierarchy import (
    htf_authority, classify_relationship,
)
from market_commander.market_commander import build_market_commander_matrix  # MC Phase B1 (observe-only)
from ai_layer.narrative_builder import build_narrative
from ai_layer.confidence_engine import score_confidence
from ai_layer.ai_snapshot_formatter import format_for_ai
from qualification.trade_qualification_engine import qualify_trade
from playbooks.playbook_classifier import classify_playbook
from risk.risk_governor import evaluate_risk
from toolbox.toolbox_engine import run_toolbox
# TIER-2A (2026-07-10) — legacy AI wrapper (discretionary_ai / debate / fusion)
# retired. The sovereign ECU Brain is the single AI; its thesis exercises
# authority upstream (qualification/playbook/toolbox direction).
from regime_classification.regime_classifier import classify_regime
from regime_authority.regime_permission_matrix import evaluate_regime_permissions
# ── Phase PIPE-1 — evidence layers the canonical Brain authors from. These were
# previously built in scan_loop AFTER build_snapshot, starving the consumed ECU
# thesis. They are now assembled inside build_snapshot BEFORE the single Brain call.
from narrative_authority.narrative_engine import build_narrative as build_narrative_authority
from narrative_authority.protected_swings import ProtectedSwingTracker
from shared_context.shared_market_context import build_shared_market_context

TIMEFRAMES = ["15m", "5m", "3m", "1m"]

#: CANONICAL RETENTION per timeframe — a FACT-STORE property, not a view.
#:
#: Sized to the widest consumer window so no reader is starved before it asks.
#: Each timeframe's span reflects the job it does rather than one convenient
#: uniform number:
#:
#:     1m  90 bars = 90 minutes     execution delivery
#:     3m  60 bars = 3 hours        setup development
#:     5m  80 bars = 6h40           essentially the whole NY session
#:     15m 32 bars = 8 hours        session plus premarket context
#:
#: Consumers narrow this; nothing widens it. A consumer that wants less says so
#: itself (see `price_levels._ZONE_LOOKBACK_BARS`).
CANONICAL_RETAINED_BARS = {"1m": 90, "3m": 60, "5m": 80, "15m": 32}


# CONTINUITY-2G — a full bucket's constituent count, for series that predate
# `expected_members` (hand-built fixtures, older archives). Never used to
# OVERRIDE a value the producer supplied.
_EXPECTED_MEMBERS = {"1m": 1, "3m": 3, "5m": 5, "15m": 15}

SETTLED = "settled"
FORMING = "forming"
UNKNOWN = "unknown"
#: PHASE 4B (2026-08-12). `complete` is a MEMBERSHIP COUNT
#: (`len(bars) == n_minutes`), not a temporal claim. A historical bucket that
#: never obtained full membership because the canonical series has a hole was
#: therefore published as FORMING -- measured at the 15:43 scan, 7 of 32 15m
#: bars, including 2026-08-11 15:00 built from FIVE of fifteen minutes.
#:
#: "Currently accumulating in real time, its close will still change" and
#: "finished, but assembled from partial evidence" are different propositions.
#: The first is realtime context; the second is damaged history. Collapsing them
#: told Terra a prior-day candle was live.
HISTORICAL_INCOMPLETE = "historical_incomplete"


def _previous_slot_close(settled: list, raw_series: list, tf_minutes) -> dict:
    """Thin delegate. STEP 4B.12 §4 UNIT 2 moved this resolver into
    `market_data.swing_evidence` so the STRUCTURE lane can consume the very same
    previous-expected-bucket authority the liquidity lane already uses, without
    a second calendar owner and without importing this module upward."""
    from market_data.swing_evidence import previous_slot_close
    return previous_slot_close(settled, raw_series, tf_minutes)


def _swing_evidence(settled: list, raw_series: list, tf_minutes: int) -> dict:
    """Thin delegate. STEP 4B.12 §4 UNIT 1 moved the resolver into
    `market_data.swing_evidence` so detector modules can obtain projected
    evidence without importing this module's internals upward."""
    from market_data.swing_evidence import build_swing_evidence
    return build_swing_evidence(settled, raw_series, tf_minutes)


def _terminal_constituent_observed(bucket: dict, terminal: str) -> bool:
    """Thin delegate -- the resolver that consumes this moved to
    `market_data.swing_evidence` in UNIT 2, and the helper must live beside it."""
    from market_data.swing_evidence import terminal_constituent_observed
    return terminal_constituent_observed(bucket, terminal)


def _newest_stamp(raw_series: list):
    """The timestamp of the latest bucket in the series.

    Only that bucket can be CURRENTLY forming; anything older is finished,
    whatever its membership count says.
    """
    stamps = [r.get("timestamp") for r in raw_series or [] if r.get("timestamp")]
    return max(stamps) if stamps else None


def _source_contract(raw_series: list, normalized: dict) -> dict:
    """The contract the bucket behind ONE normalized candle actually proves.

    STEP 4B.12 §6 UNIT 6 — IDENTITY SURVIVES NORMALISATION.

    `normalize_candle` rebuilds a whitelisted dict, so `contract` -- which
    `timeframe_builder` DOES attach to every bucket -- did not survive into
    `recent_candles`. The toolbox therefore could not mint a canonical FVG
    occurrence id, and every plain-FVG occurrence on the execution path came
    back `identity_evaluable = False`.

    Repaired at the SAME additive seam CONTINUITY-2G used for temporal status,
    rather than by widening the canonical `normalize_candle` schema for every
    consumer in the tree. Price fields are untouched; `all_normalized` and
    `all_settled` -- the detector inputs -- are deliberately not annotated, so
    detector behaviour stays bit-for-bit.

    PER CANDLE, FROM ITS OWN BUCKET. Not one value asserted over the series: a
    mixed-contract series must not be laundered into a single confident claim.
    `row_contract` refuses a row whose `contract` and `contractId` disagree, and
    that refusal is preserved as ABSENCE rather than swallowed -- an occurrence
    whose contract cannot be proven has no identity, and no identity is not
    permission to execute.

    There is no fallback. Not the configured symbol, not an environment
    variable, not the instrument alias. Those name a SETTING; identity must name
    the market object.
    """
    from market_data.object_identity import row_contract

    stamp = (normalized or {}).get("timestamp")
    for raw in raw_series or []:
        if raw.get("timestamp") != stamp:
            continue
        try:
            contract = row_contract(raw, where="snapshot candle contract")
        except Exception:            # noqa: BLE001 — contradictory row proves nothing
            return {}
        return {"contract": contract} if contract else {}
    return {}


def annotated_timeframe(raw_candles: list, tf: str, *, normalized: list = None) -> dict:
    """THE ONE definition of an annotated timeframe view. PURE.

    EVENT-WAKE-ACTIONABLE-STRUCTURE-1 extracted this from `build_snapshot` so
    that the wake registry and the production snapshot cannot end up with two
    different answers to "is this candle settled?".

    Rebuilding `normalize -> _temporal_status -> retain` independently would have
    worked tonight and drifted the first time this composition changed, leaving:

        WAKE PATH:        settled
        PRODUCTION PATH:  provisional

    on the same bar. `fvg_execution_instances` filters on exactly that field, so
    the two would silently disagree about which occurrences exist.

    PURE BY CONTRACT: it copies candle dicts and touches no `swing_tracker`,
    `po3_stability`, `expansion_stability`, flip registry, ledger, provider or
    Brain state. `normalized` is accepted so the snapshot path does not normalise
    twice; when omitted this normalises the raw series itself.
    """
    if not raw_candles:
        return {"last_candle": None, "recent_candles": []}
    if normalized is None:
        normalized = normalize_candles(raw_candles, get_session_label)
    if not normalized:
        return {"last_candle": None, "recent_candles": []}
    keep = CANONICAL_RETAINED_BARS.get(tf, 5)
    annotated = [{**c, **_temporal_status(raw_candles, c, tf),
                  **_source_contract(raw_candles, c)}
                 for c in normalized[-keep:]]
    return {"last_candle": annotated[-1], "recent_candles": annotated}


def _temporal_status(raw_series: list, normalized: dict, tf: str = None) -> dict:
    """The temporal truth about ONE bucket: settled / forming / unknown.

    `normalize_candle` whitelists its output, so the `complete` / `members`
    flags `timeframe_builder` attaches do not survive normalisation. The raw
    series is consulted by timestamp instead.

    THREE states, not two. A bar whose completeness was never recorded -- an
    older archive, a replay, a hand-built fixture -- is `unknown`, and says so.
    It is still TREATED as settled by `_bucket_is_settled` (the CONTINUITY-2D
    policy: inventing incompleteness would silently delete real structure), but
    the uncertainty is preserved in what is published rather than collapsed into
    a confident "settled". A consumer that cannot tell those apart cannot
    reason honestly about them, and the Brain is exactly such a consumer.
    """
    expected = _EXPECTED_MEMBERS.get(tf)
    stamp = (normalized or {}).get("timestamp")
    for raw in raw_series or []:
        if raw.get("timestamp") != stamp:
            continue
        if "complete" not in raw:
            break
        members = raw.get("members")
        if raw.get("complete"):
            status = SETTLED
        elif stamp == _newest_stamp(raw_series):
            status = FORMING                 # the live bucket; its close may move
        else:
            status = HISTORICAL_INCOMPLETE   # finished, but built on a hole
        return {"temporal_status": status,
                "members": members if isinstance(members, int) else None,
                "expected_members": raw.get("expected_members", expected)}
    return {"temporal_status": UNKNOWN, "members": None,
            "expected_members": expected}


def settled_source_provenance(raw_series: list, settled_series: list) -> dict:
    """WHICH BAR AUTHORED this timeframe's confirmed structure and liquidity.

    CAUSAL-OCCURRENCE-IDENTITY-1. `analyze_structure` and `analyze_liquidity`
    are handed `all_settled[tf]` and nothing else, so every confirmed claim they
    publish is a function of the newest SETTLED bucket -- not of the scan that
    happened to observe it. That bucket is the causal author, and until now its
    identity was never written down anywhere a consumer could read.

    The consequence was concrete: a 15m raid stayed true for fifteen 1m scans,
    and each scan minted a fresh occurrence identity from the SCAN clock, so one
    market event was recorded as fifteen. Publishing the authoring bucket is what
    lets identity be built from the event instead of from the observation.

    THREE CLOCKS, DELIBERATELY DISTINCT AND NEVER INTERCHANGEABLE:

        source_bar_time     the canonical bucket OPEN. Identity. Stable for the
                            whole life of the bucket and for every later scan.
        settled_edge_time   the terminal constituent that actually closed the
                            bucket, `source_member_times[-1]`. Diagnostic: it
                            says WHEN the bucket became knowable.
        observed_at         the scan. Belongs to the observer, never to the
                            event, and is therefore not published here at all.

    `settled_edge_time` is None on 1m, honestly: the aggregator publishes
    `source_member_times` only for buckets it actually aggregated, and a
    pass-through minute has no member list to name a terminal constituent from.
    Deriving one by arithmetic would manufacture provenance. `settled_edge_basis`
    says which of those two worlds produced the answer.

    PURE, and additive at the snapshot boundary: it reads the same series the
    detectors were given and computes nothing they consume.
    """
    out = {"source_bar_time": None, "settled_edge_time": None,
           "settled_edge_basis": None, "temporal_status": None,
           "settled_bars": len(settled_series or [])}
    if not settled_series:
        return out
    last = settled_series[-1] or {}
    stamp = last.get("timestamp")
    if not stamp:
        return out
    out["source_bar_time"] = canonical_instant(stamp, strict=False)
    out["temporal_status"] = _temporal_status(raw_series, last).get(
        "temporal_status")
    for raw in raw_series or []:
        if raw.get("timestamp") != stamp:
            continue
        members = raw.get("source_member_times")
        if isinstance(members, (list, tuple)) and members:
            out["settled_edge_time"] = str(members[-1])
            out["settled_edge_basis"] = "source_member_times[-1]"
        else:
            out["settled_edge_basis"] = "no_member_list_published"
        break
    else:
        out["settled_edge_basis"] = "bucket_absent_from_raw_series"
    return out


def _bucket_is_settled(raw_series: list, normalized: dict) -> bool:
    """Is this bar a FINISHED bucket? Only `forming` is not.

    Delegates so there is ONE owner of the settled/forming reading. `unknown`
    counts as settled here -- see `_temporal_status` for why that policy is
    deliberate, and why it no longer costs us the ability to say "unknown".
    """
    # PHASE 4B: DETECTOR POLICY IS UNCHANGED. Splitting FORMING into
    # forming/historical_incomplete refines what is PUBLISHED, not what counts as
    # settled evidence -- an incomplete historical bucket was excluded here
    # before and is excluded now. `unknown` still counts as settled, for the
    # CONTINUITY-2D reason documented above.
    return _temporal_status(raw_series, normalized).get(
        "temporal_status") not in (FORMING, HISTORICAL_INCOMPLETE)

_NO_MEMORY = {"available": False, "snapshot_count": 0, "global": None, "timeframes": None}


def compute_htf_conflict_flags(htf_context, narrative_direction) -> list:
    """FLAG-SPLIT (2026-07-30) — the single owner of conflict-flag semantics.

    A conflict flag means ONE thing: the multi-day HTF bias and the mechanical
    narrative direction are both directional and point opposite ways. Gap
    state is context (htf_context["gap_context"], always present), never a
    conflict — the pre-split gap flag latched entire sessions and was 84% of
    all flag volume (docs/audits/HTF_CONFLICT_FLAGS_AUDIT_20260730.md).
    Witness semantics only: no gate, qualification, or execution path reads
    these flags; the intended reader is the Brain via a future, separately
    measured prompt clause (HTF-PROMPT)."""
    if not isinstance(htf_context, dict):
        return []
    hb = htf_context.get("htf_bias")
    if hb not in ("bullish", "bearish"):
        return []
    if narrative_direction in ("bullish", "bearish") and narrative_direction != hb:
        return [f"htf_bias_{hb}_vs_narrative_{narrative_direction}"]
    return []


def build_snapshot(
    raw_data: dict,
    ref_timestamp: str = None,
    memory=None,
    experience_summary: dict = None,
    prior_memory_search: dict = None,
    prior_dashboard: dict = None,
    thesis_engine=None,
    symbol: str = None,
    swing_tracker=None,
    po3_stability=None,
    expansion_stability=None,
    session_po3=None,
    deep_1m=None,
    capital_report=None,
    htf_context=None,
    contract_id: str = None,
    execution_price: dict = None,
) -> dict:
    timeframes = {}
    all_normalized = {}

    for tf in TIMEFRAMES:
        candles = raw_data.get(tf, [])
        if not candles:
            timeframes[tf] = {"last_candle": None, "recent_candles": []}
            all_normalized[tf] = []
            continue

        normalized = normalize_candles(candles, get_session_label)
        all_normalized[tf] = normalized
        # CONTINUITY-2G (2026-08-11). The realtime channel now STATES each bar's
        # temporal status instead of leaving the reader to guess.
        #
        # The forming bucket was always delivered here -- deliberately, it is
        # realtime context -- but normalisation had stripped `complete`/`members`,
        # so `brain_input` handed the Brain a 15m bar that was 6 minutes old with
        # nothing to distinguish it from a finished one. "Realtime context may
        # not counterfeit confirmation" was unenforceable at that boundary
        # because the Brain was never given the fact.
        #
        # ADDITIVE ONLY: price fields are untouched, so every existing consumer
        # of `recent_candles` / `last_candle` reads exactly what it read before.
        # `all_normalized` / `all_settled` -- the DETECTOR inputs -- are
        # deliberately left un-annotated so detector behaviour stays bit-for-bit.
        # PHASE 4A (2026-08-12) — THE STORE IS NOT THE VIEW.
        #
        # This used to keep `normalized[-5:]`, which meant the CANONICAL market
        # state was amputated to the Brain's old presentation horizon. Measured
        # on PROD-20260812-PM: every scan, every timeframe, exactly 5 bars --
        # 5 minutes of 1m and 25 minutes of 5m. Terra was asked to find a
        # discretionary entry through a four-minute window, and any future
        # consumer of this snapshot inherited the same blindness before it got a
        # say.
        #
        # Retention is now sized to the widest consumer need per timeframe.
        # Presentation windows belong to consumers: `brain_input` applies the
        # Brain's, `price_levels` pins its own 5-bar zone horizon explicitly.
        timeframes[tf] = annotated_timeframe(candles, tf, normalized=normalized)

    # CONTINUITY-2D (2026-08-11). CONFIRMED structure and liquidity are derived
    # from SETTLED buckets only.
    #
    # `_aggregate` deliberately emits the forming higher-timeframe bar so live
    # scanning can see the market in progress -- but `find_swings` confirms a
    # pivot against its neighbours on BOTH sides, so an unfinished bucket was
    # supplying right-side confirmation for structure presented as confirmed.
    # Measured on the live tape: at 15:05Z a 15m swing high of 29,805.0 rested
    # on a 6-of-15 bucket, and vanished the moment that bucket closed higher.
    #
    # The forming bar is NOT discarded -- `timeframes[tf]` below still carries
    # it as realtime context. What it may no longer do is create a confirmed
    # structural claim.
    all_settled = {tf: [c for c in all_normalized.get(tf, [])
                        if _bucket_is_settled(raw_data.get(tf, []), c)]
                   for tf in TIMEFRAMES}

    # Structure analysis runs on the settled history per timeframe
    # STEP 4B.12 §4 UNIT 1: the pivot neighbourhood is a MARKET neighbourhood.
    # This layer owns the raw provenance and the cadence, so it resolves the
    # evidence and hands `analyze_structure` the answer.
    _swing_ev = {tf: _swing_evidence(all_settled.get(tf, []),
                                     raw_data.get(tf, []),
                                     _TF_MINUTES_4B5.get(tf))
                 for tf in TIMEFRAMES}
    # UNIT 2: a BREAK is an EVENT, so structure also needs the previous EXPECTED
    # market bucket's close. Same evidence owner, same resolver the raid family
    # uses -- structure decides doctrine, market-data establishes reality.
    from market_data.swing_evidence import build_transition_evidence
    _trans_ev = {tf: build_transition_evidence(all_settled.get(tf, []),
                                               raw_data.get(tf, []),
                                               _TF_MINUTES_4B5.get(tf))
                 for tf in TIMEFRAMES}
    structure = {tf: analyze_structure(all_settled.get(tf, []), _swing_ev.get(tf),
                                       transition=_trans_ev.get(tf))
                 for tf in TIMEFRAMES}
    structure["alignment"] = compute_alignment({tf: structure[tf] for tf in TIMEFRAMES})

    # Liquidity analysis runs on the settled history per timeframe.
    #
    # STEP 4B.12: this layer owns the cadence and the UNFILTERED series, so it
    # resolves the previous EXPECTED market slot and the authority of the one
    # field the raid predicate consumes -- that slot's CLOSE. The detector never
    # walks backward through the filtered array to find something convenient.
    liquidity = {tf: analyze_liquidity(
        all_settled.get(tf, []),
        _previous_slot_close(all_settled.get(tf, []), raw_data.get(tf, []),
                             _TF_MINUTES_4B5.get(tf)),
        # UNIT 1: the swing LEVELS this detector publishes need canonical
        # neighbourhood authority too -- the dependency the prior-close unit
        # deferred. Same series, same horizon, proven witnesses.
        swing_evidence=_swing_ev.get(tf))
        for tf in TIMEFRAMES}

    # Standing directional authority, derived from `structure` alone so it is
    # available to every layer below without inverting the dependency chain.
    _ctx_series = next((all_normalized[tf] for tf in ("1m", "3m", "5m", "15m")
                        if all_normalized.get(tf)), None)
    _last_price = _ctx_series[-1]["close"] if _ctx_series else None
    # DOCTRINE: Liquidity and PO3 author direction; structure confirms only.
    # Neither exists yet at this point in the build (po3 is computed below,
    # narrative_authority later still), so this early authority is deliberately
    # neutral — it feeds displacement's coherence note, which is reported and
    # never enforced. The authoritative read is recomputed after PO3.
    _authority = htf_authority(structure.get("15m"), _last_price, "15m")
    _relationship = classify_relationship(
        _authority, str((structure.get("5m") or {}).get("bias") or "neutral").lower())

    # Volatility and expansion: ATR computed first, feeds both classifiers
    volatility = {}            # CONTINUITY-2E.3 — the composed AUTHORITY view
    volatility_realtime = {}   # the live read, forming bucket included
    volatility_settled = {}    # the baseline, settled buckets only
    expansion = {}
    for tf in TIMEFRAMES:
        candles = all_normalized.get(tf, [])
        # CONTINUITY-2E (2026-08-11). The settled series computed above is the
        # SINGLE source for detectors that publish a confirmed/authoritative
        # claim. It is not re-filtered here -- one settled series owns the
        # contract, so a consumer cannot drift from it.
        settled = all_settled.get(tf, [])
        # CONTINUITY-2E.1A (2026-08-11). TWO ATRs, named for their temporal class.
        #
        # THE INVARIANT: the temporal class of the SCALE must match the temporal
        # class of the EVIDENCE it qualifies. v22 moved the candles to settled but
        # kept feeding the detectors a realtime ATR, so settled bodies were being
        # judged against a forming-derived threshold -- a hidden category
        # mismatch, not a rounding detail.
        #
        # PROVEN, not assumed (AUDIT_2E1A_verification_verdict.md): holding the
        # settled history FIXED and varying only the forming bucket flipped
        # `displacement_detected` on 3m/5m/15m and `state` early<->mature, in
        # some cases with the SAME number of forming minutes -- the forming
        # bucket's price action alone authored the field. The path is
        # `atr -> disp_threshold = max(atr*K_ATR, f_disp(tf))` compared against
        # settled bodies, plus `atr_trend -> _score() +5/-8`.
        realtime_atr_result = calculate_atr(candles)
        settled_atr_result = calculate_atr(settled)
        # CONTINUITY-2E.3 (2026-08-12). Volatility is computed TWICE and composed
        # asymmetrically. The realtime read still sees the forming bucket -- that
        # is a truthful "how fast is it moving right now" fact and the emergency
        # brake depends on it. What it may no longer do is GRANT.
        #
        # AUDIT_2E3 measured, settled history byte-identical, forming bucket the
        # only variable: 170 risk-multiplier RAISES, 68 veto REMOVALS, 22
        # extended-stop GRANTS. Realtime volatility was an accelerator as well as
        # a brake, and `state` was carrying two different propositions under one
        # name -- "range is elevated right now" and "we are in a dangerous
        # volatility REGIME".
        volatility_realtime[tf] = dict(
            classify_volatility(candles, realtime_atr_result),
            temporal_class="realtime")
        volatility_settled[tf] = dict(
            classify_volatility(settled, settled_atr_result),
            temporal_class="settled")
        # `volatility[tf]` stays the key every authority consumer already reads,
        # so the composition applies everywhere at once instead of being wired
        # into five call sites that could each drift. Witness consumers that want
        # the live read take `volatility_realtime` explicitly.
        volatility[tf] = compose_authority(volatility_settled[tf],
                                           volatility_realtime[tf])
        # VECTOR-3: tf enables magnitude gate. LEG-SCOPE: structure[tf] supplies
        # the pivot that bounds the conviction ratios to the current auction leg.
        #
        # CONTINUITY-2E.1 (2026-08-11): SETTLED. Every helper inside
        # detect_expansion is tail-sensitive, so the forming bucket reached all
        # of them at once -- `_directional_efficiency` reads `candles[-1]["close"]`
        # (the provisional close) directly, `_follow_through` anchors its streak
        # on the forming bar's CURRENT direction, `_displacement_detected` scans
        # `candles[-5:]`, and `_body_dominance` / `_range_acceleration` weight it
        # like a finished bar.
        #
        # This is what closes 2E's own residue: `directional_efficiency` is 15 of
        # the 100 points detect_displacement scores (W_EFFICIENCY, against
        # EFFICIENCY_AT=0.30) and additionally gates po3_engine's `clean_disp`
        # at `dir_eff >= 0.30`. With expansion settled, no expansion-derived
        # scalar can push displacement_possible -> displacement_confirmed.
        #
        # Terra does NOT lose its realtime view: CONTINUITY-2G gives it the
        # forming bar itself, explicitly labelled `forming` with members N/M, so
        # `expansion_state` no longer has to serve two masters.
        #
        # 2E.1A: SETTLED ATR. An earlier note here argued ATR should stay
        # realtime because a settled ATR "blinds 6 of 89 samples". That
        # measurement was an ARTIFACT OF THE 50-MINUTE GOLD FIXTURE -- every
        # blinded sample was the 15m, which has only 2 settled buckets there.
        #
        # FAIL-CLOSED, never borrowed: when the settled series cannot support an
        # ATR, detect_expansion returns its own truthful `state: "unknown"`
        # block. Measured against the real production range (the loop accepts
        # HISTORY_MINIMUM_BARS=60 up to HISTORY_HORIZON_MINUTES=300):
        #
        #     window   3m        5m        15m
        #      60min   20 ok     12 ok      4 NONE   <- 15m genuinely cannot
        #      75min   25 ok     15 ok      5 ok        support a 14-period ATR
        #     300min  100 ok     60 ok     20 ok
        #
        # So a 60-74 minute coherent window yields `expansion["15m"].state ==
        # "unknown"`. That is the honest answer with four closed 15m buckets, and
        # it is the answer, not a gap to paper over with the forming bar.
        expansion[tf] = detect_expansion(settled, settled_atr_result, tf,
                                         structure.get(tf))
        # MANIP-CONFLUENCE: manipulation is a phase, not a closing-bar event.
        # Attached to liquidity so po3_engine keeps scoring from processed
        # evidence rather than raw candles.
        #
        # CONTINUITY-2E: SETTLED. detect_manipulation runs find_swings over its
        # context window (the same two-sided pivot rule 2D protected) and reads
        # sweep/reclaim off the trailing window. A forming bucket's high only
        # ratchets up -- so a detected sweep sticks -- while its close flickers,
        # so the RECLAIM appears and vanishes inside one unfinished bar. That
        # made "manipulation complete" toggle intra-bucket, and po3_engine pays
        # +10 for exactly that claim. This result is attached onto liquidity[tf],
        # which 2D made settled; feeding it forming candles left one published
        # block half-settled and half-forming with no marker saying which.
        # 2E.1A: settled ATR. `_rapid_reversal` measures the reversal against
        # ATR and is already guarded (`not atr or atr <= 0` -> component absent),
        # so an unavailable settled ATR costs that ONE component rather than
        # borrowing a forming-derived scale for it.
        if isinstance(liquidity.get(tf), dict):
            liquidity[tf]["manipulation"] = detect_manipulation(
                settled, settled_atr_result.get("atr"),
                # Full-series evidence; the detector projects it onto its own
                # MANIP_CONTEXT horizon rather than being handed wider swings.
                swing_evidence=_swing_ev.get(tf))
        # DISPLACEMENT-CONFLUENCE: displacement_detected is a bare bool and
        # cannot separate a nudge from a drive that tears gaps in the tape.
        #
        # CONTINUITY-2E: SETTLED. The classification is literally named
        # `displacement_confirmed`, and three of its components read the bar
        # directly: follow-through anchors on window[-1]'s CURRENT direction,
        # imbalance lets the forming bar act as c3 of an FVG, and magnitude
        # scores a partial body against ATR. order_block_extractor already
        # documents this exact hazard ("bearish while forming and bullish once
        # closed ... a leg must be judged on closed candles only") and defends
        # itself -- the detector it calls did not.
        #
        # 2E.1A: the seam noted here in 2E is now CLOSED on both sides. All six
        # components rest on settled evidence: the five that read candles
        # directly, and `directional_efficiency`, which arrives from the settled
        # `expansion[tf]` above. `_magnitude` divides the body by ATR, so the
        # scale is settled too -- and its `not atr` guard keeps that component
        # absent rather than borrowed when the settled series cannot support one.
        if isinstance(expansion.get(tf), dict):
            # STEP 3D: the ATR is the DENOMINATOR of the magnitude ratio, so the
            # candles that authored it are evidence too. `detect_displacement`
            # only ever receives a float and cannot know where it came from --
            # this is the layer that does.
            from volatility.atr_engine import atr_source_window, DEFAULT_PERIOD
            expansion[tf]["displacement"] = detect_displacement(
                settled, structure.get(tf), settled_atr_result.get("atr"),
                expansion[tf], authority=_authority,
                atr_provenance={"period": DEFAULT_PERIOD,
                                "source_bars": atr_source_window(settled)},
                # STEP 4B.5: the detector must be able to prove canonical
                # timeframe adjacency; only this layer knows the timeframe.
                tf_minutes=_TF_MINUTES_4B5.get(tf))

    # PERCEPTION-1 — expansion state hysteresis (VECTOR-3 analogue). The live
    # loop passes its persistent instance; one-shot callers get no stabilizer
    # (bit-for-bit legacy). Debounces the flickering per-TF expansion `state`
    # so a one-scan threshold crossing no longer overrides a stable state.
    if expansion_stability is not None:
        expansion = expansion_stability.update(expansion)

    # Anchor snapshot to the most granular available last candle
    anchor = None
    for tf in ["1m", "3m", "5m", "15m"]:
        if timeframes.get(tf, {}).get("last_candle"):
            anchor = timeframes[tf]["last_candle"]
            break

    snap_time = ref_timestamp or (
        anchor["timestamp"] if anchor else datetime.now(timezone.utc).isoformat()
    )
    session = anchor["session_label"] if anchor else "unknown"

    # PO3 phase analysis — runs on already-computed mechanical evidence.
    # Reconciled against the authority established above: additive only, it
    # annotates how each phase sits inside the authority and never rewrites it.
    po3 = analyze_po3_snapshot(structure, liquidity, volatility, expansion)

    # Authoritative read: PO3 now exists and can author direction (authority #2).
    # Liquidity's active_liquidity_draw (authority #1) lives in
    # narrative_authority, which is built further down, so it reaches this only
    # on the paths where narrative already exists. Structure is passed for
    # CONFIRMATION reporting and can never author direction.
    # narrative_authority does not exist yet (it is built further down and its
    # own _build reads po3, so it cannot precede this). PO3 authors here.
    _authority = htf_authority(structure.get("15m"), _last_price, "15m",
                               po3=po3, liquidity=liquidity)
    _relationship = classify_relationship(
        _authority, str((structure.get("5m") or {}).get("bias") or "neutral").lower())
    for _tf in ("15m", "5m", "3m", "1m"):
        if isinstance(po3.get(_tf), dict):
            po3[_tf]["authority_reading"] = reconcile_phase(
                po3[_tf].get("phase", "no_phase"), _authority,
                _relationship["relationship"])
    po3["authority"] = {"bias": _authority.get("bias"),
                        "intact": _authority.get("intact"),
                        "source": _authority.get("source"),
                        "relationship": _relationship["relationship"],
                        "detail": _authority.get("detail")}

    # VECTOR-3 — stateful stability layer. The pure engine above re-derives phases
    # and alignment from scratch each scan; the manager (when the live loop passes
    # its persistent instance) applies the phase dead-band + alignment hysteresis
    # so a single sub-floor 1m flip can no longer rewrite global alignment. When no
    # instance is passed, po3 is unchanged (pure pass-through).
    if po3_stability is not None:
        po3 = po3_stability.update(po3)

    # SESSION-PO3 AUTHORITY (LUNA-SESSION-PO3-AUTHORITY-1). Everything above is
    # per-timeframe EVIDENCE; this is the one canonical session phase, and the
    # only place that answers whether a NEW entry may exist at all.
    #
    # It runs here because every input it needs is already resolved -- the
    # settled 1m series, the per-TF PO3 phases, the manipulation confluence
    # attached to liquidity, and `_authority`, the repo's standing answer to
    # "who owns direction". Placing it in the builder (rather than in one loop)
    # is what makes live, restart-rebuild and replay read the same phase: they
    # all come through here.
    #
    # The manager is OPTIONAL and additive: a one-shot caller that passes none
    # gets the identical phase, because the phase is a pure function of the tape
    # and the manager contributes provenance only.
    from structure.session_po3 import SessionPo3Authority, derive as _derive_session_po3
    _sp3_args = dict(settled_1m=all_settled.get("1m") or [], po3=po3,
                     liquidity=liquidity, structure=structure, authority=_authority)
    if isinstance(session_po3, SessionPo3Authority):
        session_po3_state = session_po3.update(observed_at=snap_time, **_sp3_args)
    else:
        session_po3_state = _derive_session_po3(**_sp3_args)

    # CROSS-SESSION CONTEXT (LUNA-CROSS-SESSION-PO3-CONTEXT-1). Beside the
    # session phase, never inside it: `session_po3.derive` above has no argument
    # through which any of this could reach it, which is what makes "prior
    # sessions never dictate New York" structural rather than a convention.
    #
    # It reads a DEDICATED DEEPER SERIES. The ordinary scan window is 300
    # minutes and reaches ~04:30 ET at the open -- enough for premarket, blind to
    # London and Asia. Widening that window would have changed every downstream
    # consumer, so the depth is supplied separately and only this producer sees
    # it. Absent, every context reports honestly rather than guessing.
    from market_data.session_context import derive as _derive_session_context
    session_context_state = _derive_session_context(settled_1m=deep_1m or [])

    # Memory modifiers from prior snapshots — read BEFORE building narrative/confidence
    memory_mods = memory.get_modifiers() if memory else {}

    # AI layer: narrative (informed by PO3 + memory) → confidence → full context
    narrative  = build_narrative(structure, volatility, expansion, liquidity, po3, session, memory_mods)
    confidence = score_confidence(structure, volatility, expansion, liquidity, session, narrative, po3, memory_mods)

    ai_context = {
        "market_narrative":  narrative["market_narrative"],
        "market_state":      narrative["market_state"],
        "directional_bias":  narrative["directional_bias"],
        "confidence_score":  confidence["confidence_score"],
        "confidence_tier":   confidence["confidence_tier"],
        "trade_personality": narrative["trade_personality"],
        "coherence":         narrative["coherence"],
        "warnings":          narrative["warnings"],
        # NARRATIVE-AUDIT — decision-reason transparency (observe-only telemetry)
        "narrative_reason":     narrative.get("narrative_reason"),
        "narrative_driver_tf":  narrative.get("narrative_driver_tf"),
        "summary":           "",  # filled after memory is attached
    }

    # AI_CONTEXT-AUTHORITY (2026-07-09) — TRUTH-IN-LABELLING. Despite the name,
    # EVERY ai_context field is MECHANICALLY authored: build_narrative() /
    # score_confidence() read only structure/volatility/expansion/liquidity/po3.
    # The true AI Brain lives in snapshot['ai_brain'] / ['brain_thesis'] /
    # ['thesis_state']. This metadata marks each field's real author so no
    # consumer can mistake a mechanical reading for AI authority. Decision
    # consumers demote these to witness when the Brain is sovereign (see
    # shared_context.mechanical_judges.mechanical_context_witness).
    ai_context["_authorship"] = {
        "market_narrative":  "mechanical_derived",
        "market_state":      "mechanical_derived",
        "directional_bias":  "mechanical_derived",
        "confidence_score":  "mechanical_derived",
        "confidence_tier":   "mechanical_derived",
        "trade_personality": "mechanical_derived",
        "coherence":         "mechanical_sensor",
        "warnings":          "mechanical_sensor",
        "narrative_reason":     "telemetry",
        "narrative_driver_tf":  "telemetry",
        "summary":              "telemetry",
    }
    ai_context["ai_context_is_mechanical_witness"] = True

    snapshot = {
        "timestamp":  snap_time,
        "session":    session,
        "symbol":     symbol,
        # PLAIN-FVG-EXECUTABLE-REPRESENTATION-1. `symbol` is "MNQ" -- an
        # instrument, not the EXACT contract identity requires. Canonical candle
        # rows record no contract, so without this every plain FVG was anonymous
        # on every timeframe. Threaded from the caller that knows it; None when
        # unknown, and identity then fails closed rather than being invented.
        "contract_id": contract_id,
        "timeframes": timeframes,
        "structure":  structure,
        "volatility": volatility,
        # CONTINUITY-2E.3 — published so the composition is auditable and so a
        # witness consumer can ask for the live read BY NAME rather than by
        # accident. `volatility` above is the authority view.
        "volatility_realtime": volatility_realtime,
        "volatility_settled":  volatility_settled,
        "liquidity":  liquidity,
        "expansion":  expansion,
        "po3":        po3,
        "session_po3": session_po3_state,
        "session_context": session_context_state,
        "ai_context": ai_context,
        # CAUSAL-OCCURRENCE-IDENTITY-1. WHICH BAR AUTHORED the confirmed
        # structure/liquidity above, per timeframe. Additive and inert: no
        # detector, gate, candidate or Brain projection reads it. It exists so
        # that a market EVENT can be identified by the bucket that caused it
        # rather than by the scan that happened to notice it.
        "settled_source": {tf: settled_source_provenance(raw_data.get(tf, []),
                                                         all_settled.get(tf, []))
                           for tf in TIMEFRAMES},
    }

    # Memory context: compares this snapshot to history, then stores it
    snapshot["memory"] = (
        memory.push_and_get_context(snapshot) if memory else _NO_MEMORY.copy()
    )

    # Regime Classifier (Phase 5A, moved up in 5F): labels the environment.
    # Confidence-side authority unchanged (observe_only, confidence_modifier=0).
    # Phase 5F.2 grants regime CONSTRAINT authority via the permission matrix below.
    # CONTINUITY-2E: `all_normalized` still supplies the REALTIME reads (last
    # price, range metrics, range state) -- those describe now and must see the
    # forming bar. `all_settled` supplies swing_sequence, which calls the very
    # find_swings 2D protected and was confirming 15m pivots against an
    # unfinished right-side neighbour. Both are passed; the regime layer chooses
    # per feature rather than being handed one series and guessing.
    snapshot["market_regime"] = classify_regime(
        snapshot, all_normalized, settled_data=all_settled)

    # ── MARKET-CONTEXT — stage 1 authority. Must follow classify_regime, which
    # it consumes rather than duplicates. Adds what nothing upstream provides:
    # retracement as an environment, the dealing range / premium-discount, and
    # the authority downstream asks before assigning direction to a local event.
    snapshot["market_context"] = analyze_market_context(
        structure, liquidity, expansion, po3, snapshot["market_regime"],
        last_price=_last_price)

    # ── Phase NEWS-1 — News Intelligence pre-pass (gated NEWS_LAYER_ENABLED) ───
    # Attaches non-directional market-awareness context (scheduled events,
    # breaking news, event-risk state) so the Brain can weigh it. Runs BEFORE the
    # ECU pre-pass so the Brain receives it. News never authors direction or
    # trades. When OFF, skipped entirely — pipeline bit-for-bit unchanged.
    from news.news_engine import news_enabled, build_news_context
    if news_enabled():
        snapshot["news_context"] = build_news_context(snapshot.get("timestamp"))

    # ── VOLUME-WITNESS — participation sense organ (gated VOLUME_WITNESS) ─────
    # Non-directional participation evidence attached BEFORE the ECU pre-pass:
    # per-TF relative volume + z-score + same-minute-of-day percentile (replay-
    # built baseline table) + sweep/displacement association (EXISTING sensors'
    # events only — no re-detection) + IEX venue provenance. WITNESS ONLY: no
    # gate/risk/qualification/decision path reads it (test-locked). When OFF,
    # skipped entirely — pipeline bit-for-bit unchanged.
    from market_data.volume_witness import volume_witness_enabled, build_volume_witness
    if volume_witness_enabled():
        snapshot["volume_witness"] = build_volume_witness(
            all_normalized, liquidity=liquidity, expansion=expansion,
            symbol=symbol or snapshot.get("symbol"))

    # ── HTF-MEM-1 — higher-timeframe memory (CONTEXT ONLY) ─────────────────────
    # Multi-day context (previous day/session, weekly direction, gap, untapped
    # liquidity) computed by the scan loop's HtfMemoryEngine and attached BEFORE
    # the ECU pre-pass so the Brain can weigh it. It informs thesis quality and
    # warns about conflict; it may NOT execute, veto, or force direction.
    if isinstance(htf_context, dict):
        snapshot["htf_memory"] = htf_context

    # ── Phase PIPE-1 — assemble the load-bearing evidence the Brain authors from
    # BEFORE the single canonical Brain call. Previously protected_swings,
    # narrative_authority and shared_context were built in scan_loop AFTER this
    # function returned, so the consumed ECU thesis saw delivery.state=None,
    # protected_swings=none and active_draw=None (the upstream ordering inversion).
    # The protected-swing tracker is stateful: the live loop passes its persistent
    # instance; one-shot callers get a transient tracker. This is the ONLY place
    # the tracker is advanced per scan.
    #
    # NOTE: shared_context here carries the qualification-INDEPENDENT delivery view
    # the Brain needs (delivery_state / exhaustion_present / po3). Its opportunity
    # view (qualification / playbook / setup_age) is necessarily still default at
    # this point and is rebuilt downstream once qualification + setup_lifecycle
    # exist; nothing reads that view before the rebuild.
    _swings = swing_tracker if swing_tracker is not None else ProtectedSwingTracker()
    snapshot["protected_swings"]    = _swings.update(snapshot)
    snapshot["narrative_authority"] = build_narrative_authority(
        snapshot, snapshot["protected_swings"])

    # ── AUTHORITY, RESOLVED. The earlier read (right after PO3) could only see
    # authority #2, because narrative_authority — which owns
    # active_liquidity_draw, authority #1 — is assembled here and its own _build
    # reads po3, so it cannot precede it. The draw therefore existed on 117 of
    # 133 replayed scans and never reached the authority model, which reported
    # neutral on every one of them.
    #
    # Recomputed here with the draw available, and republished so the snapshot
    # carries the resolved read rather than the provisional one.
    _authority = htf_authority(structure.get("15m"), _last_price, "15m",
                               narrative=snapshot["narrative_authority"],
                               po3=po3, liquidity=liquidity)
    _relationship = classify_relationship(
        _authority, str((structure.get("5m") or {}).get("bias") or "neutral").lower())
    snapshot["directional_authority"] = {
        **_authority, "relationship": _relationship["relationship"],
        "reasoning": _relationship["reason"]}
    for _tf in ("15m", "5m", "3m", "1m"):
        if isinstance(po3.get(_tf), dict):
            po3[_tf]["authority_reading"] = reconcile_phase(
                po3[_tf].get("phase", "no_phase"), _authority,
                _relationship["relationship"])
    po3["authority"] = {"bias": _authority.get("bias"),
                        "intact": _authority.get("intact"),
                        "source": _authority.get("source"),
                        "relationship": _relationship["relationship"],
                        "detail": _authority.get("detail")}

    # HTF-MEM-1: conflict WARNING flags (context, not veto) — HTF bias vs the
    # narrative direction, computed pre-Brain so the Brain sees the warning too.
    # FLAG-SPLIT (2026-07-30): a conflict flag is ONLY directional HTF-vs-
    # narrative disagreement. The unfilled-gap condition is a session-long
    # STATE, not a conflict — it latched 100% of scans on 7 sessions (84% of
    # all flag volume) and its information already rides gap_context
    # unconditionally (audit: docs/audits/HTF_CONFLICT_FLAGS_AUDIT_20260730.md).
    if isinstance(htf_context, dict):
        htf_context["htf_conflict_flags"] = compute_htf_conflict_flags(
            htf_context,
            (snapshot["narrative_authority"] or {}).get("narrative_direction"))
    snapshot["shared_context"]      = build_shared_market_context(
        snapshot, symbol or snapshot.get("symbol"))

    # ── Phase AB-5B — canonical ECU Brain call (gated BRAIN_ECU_MODE, default off)
    # Runs AFTER the evidence above and BEFORE the intelligence consumers, so the
    # consumed thesis is fully-fed. When OFF, skipped entirely and the
    # mechanical-owned pipeline is unchanged (bit-for-bit).
    from ai_brain.ecu import ecu_enabled, produce_thesis
    if ecu_enabled():
        candidate = produce_thesis(snapshot)
        snapshot["candidate_thesis"] = candidate
        snapshot["brain_thesis"] = candidate   # shadow default: pipeline bit-for-bit unchanged

        # ── Phase AB-7 — Persistent Thesis Lifecycle (gated THESIS_LIFECYCLE_MODE) ──
        # The Brain produces a CANDIDATE every scan; the lifecycle engine maintains a
        # persisted ACTIVE thesis (continue/strengthen/weaken/invalidate/replace). In
        # shadow it only observes; in enforce it stabilizes brain_thesis so the
        # consumers stop flickering on one-scan evidence noise.
        from ai_brain.thesis_lifecycle import (
            lifecycle_enabled, enforce_mode, extract_evidence, ThesisLifecycleEngine,
            thesis_state,
        )
        if lifecycle_enabled():
            # The symbol MUST be passed. ThesisLifecycleEngine falls back to
            # SCAN_SYMBOL/"QQQ", and its cross-instrument reload guard compares
            # the stored thesis's symbol against that same default — so an
            # unnamed engine on an MNQ session identifies as QQQ, matches a
            # stored QQQ thesis, and resurrects it. The guard passes precisely
            # because both sides are the same wrong default. scan_loop and
            # replay_session already pass it; this fallback did not.
            engine = thesis_engine or ThesisLifecycleEngine(
                symbol=symbol or snapshot.get("symbol"))
            snapshot["thesis_lifecycle"] = engine.update(
                candidate, extract_evidence(snapshot, candidate), snapshot.get("timestamp"),
            )
            # ── Phase AB-7.3a — read-only thesis state for downstream consumers ──
            # Exposes the stabilized thesis/playbook state (status, age, confidence
            # trend) so qualification/readiness/gate can consume it. Read-only; no
            # behavioral change on its own (consumers gate their own usage).
            snapshot["thesis_state"] = thesis_state(snapshot["thesis_lifecycle"])
            if enforce_mode():
                stabilized = engine.as_brain_thesis()
                if stabilized is not None:
                    snapshot["brain_thesis"] = stabilized

    # Qualification: validator. Opportunity SCORE is mechanical; direction is
    # owned by the Brain thesis under ECU mode (see _direction_with_source).
    snapshot["qualification"] = qualify_trade(snapshot)

    # Playbook: validator/ranker. Direction owned by Brain thesis under ECU mode.
    snapshot["playbook"] = classify_playbook(snapshot)

    # Regime Permission Matrix (Phase 5F.2): constraint authority.
    # Controls permissions (playbooks, risk cap, trigger strictness, setup age)
    # — NEVER confidence scores. Enforced in order_builder + execution_gate.
    snapshot["regime_permissions"] = evaluate_regime_permissions(snapshot)

    # Risk Governor: reads full snapshot including qualification + playbook
    snapshot["risk"] = evaluate_risk(snapshot)

    # TOOLBOX-EXECUTION-PRICE-ORDERING-1:
    # The governed executable price must precede toolbox evaluation --
    # `_reanchor_location` answers "where is price relative to this zone" from
    # it, and without it a zone whose invalidation was already breached reports
    # `invalidated: False`. The caller supplies ONE block per scan and the same
    # block is reused, so the price zones were measured against is the price the
    # Brain is shown. Attached only when supplied: the historical rebuild passes
    # nothing and keeps its price-free shape, key absent as before.
    if execution_price is not None:
        snapshot["execution_price"] = execution_price

    # Toolbox: reads playbook + risk + all evidence to select entry tools
    snapshot["toolbox"] = run_toolbox(snapshot)

    # ── ADAPTIVE-3 — Adaptive Policy Report (OBSERVE_ONLY / DEFENSIVE_ONLY) ────
    # Reads the symbol-native performance tables for the CURRENT candidate
    # (playbook/tool/session/regime/volatility) and reports expectancy grades +
    # recommendation flags. Recommendation-only: it authorizes/blocks/overrides
    # NOTHING (authority_level=observe_only). Built AFTER toolbox so all five
    # candidate dimensions exist. Never raises.
    from adaptive_learning.adaptive_policy_engine import generate_adaptive_policy_report
    _regime = snapshot.get("market_regime", {}) or {}
    # CAPITAL-1: the scan loop computes the capital report once per scan and
    # passes it here; capital rides the policy as a DEFENSIVE evidence source.
    snapshot["capital_intelligence"] = capital_report
    snapshot["adaptive_policy"] = generate_adaptive_policy_report({
        "symbol":     symbol or snapshot.get("symbol"),
        "playbook":   (snapshot.get("playbook", {}) or {}).get("selected_playbook"),
        "tool":       (snapshot.get("toolbox", {}) or {}).get("preferred_tool"),
        "session":    snapshot.get("session"),
        "regime":     _regime.get("regime_family"),
        "volatility": _regime.get("volatility_state"),
    }, capital=capital_report)

    # ── ADAPTIVE-4 — Bounded Mutation Engine (SHADOW MODE / DEFENSIVE_ONLY) ────
    # Computes the DEFENSIVE_ONLY mutations the policy WOULD apply to the live
    # candidate (confidence penalty / size halving / soft veto). SHADOW: computed,
    # visible, and persisted with the snapshot, but NOT enforced — execution reads
    # the original authority. Boosts are ignored. Never raises. qty is None here
    # (sizing happens at execution); the size rule therefore no-ops in-snapshot.
    from adaptive_learning.adaptive_mutation_engine import mutate_candidate
    _qual = snapshot.get("qualification", {}) or {}
    snapshot["adaptive_mutation"] = mutate_candidate(
        {
            "confidence":           (snapshot.get("ai_context", {}) or {}).get("confidence_score"),
            "qty":                  None,
            "playbook":             (snapshot.get("playbook", {}) or {}).get("selected_playbook"),
            "tool":                 (snapshot.get("toolbox", {}) or {}).get("preferred_tool"),
            "qualification_status": _qual.get("status"),
            "direction":            _qual.get("direction"),
        },
        snapshot["adaptive_policy"],
    )

    # ── ADAPTIVE-5 — Live Mutation Authority (LIVE / DEFENSIVE_ONLY) ───────────
    # Promotes the shadow mutation to a LIVE defensive OVERLAY: exposes
    # adaptive_live_authority / adaptive_confidence / adaptive_block / adaptive_size
    # WITHOUT overwriting ai_context, qualification, playbook, tool, direction, the
    # Brain confidence, or the risk governor. Downstream layers may READ these to
    # become STRICTER only (confidence never raised, size never invented, block can
    # only add a no-trade reason). Never raises.
    from adaptive_learning.adaptive_live_authority import apply_adaptive_live_authority
    apply_adaptive_live_authority(snapshot)

    # Experience Intelligence (Phase 3A): OBSERVE_ONLY context from previous scan.
    # confidence_modifier is always 0 and must never influence toolbox or decisions.
    if experience_summary:
        snapshot["experience_summary"] = experience_summary

    # Phase 5E.3 — inject prior-scan intelligence so AI input sees real data.
    # These are 1-scan stale but far better than empty dicts.
    # scan_loop.py overwrites them with fresh values after this function returns.
    if prior_memory_search:
        snapshot["memory_search"] = prior_memory_search
    if prior_dashboard:
        snapshot["performance_dashboard"] = prior_dashboard

    # TIER-2A (2026-07-10) — the legacy AI wrapper call
    # (ai_discretionary / confidence_fusion / ai_debate) is RETIRED. Downstream
    # readers tolerate absence: Commander council testimony reports an explicit
    # missing_reason; the ADAPTIVE-6 confidence overlay finds no target (its
    # guard makes it a recorded no-op); decision.confidence reports 0.

    # Summary generated last so it sees everything
    ai_context["summary"] = format_for_ai(snapshot)

    # ── MARKET COMMANDER (Phase B1) — OBSERVE-ONLY telemetry ──────────────────
    # Built LAST, after every evidence layer + Brain/thesis/qualification/risk/
    # playbook/toolbox exist, so the matrix reflects the full picture. It
    # authorizes/blocks/overrides NOTHING (authority_level=observe_only); it only
    # unifies the scan into one state matrix and flags contradictions.
    snapshot["market_commander"] = build_market_commander_matrix(snapshot)

    return snapshot
