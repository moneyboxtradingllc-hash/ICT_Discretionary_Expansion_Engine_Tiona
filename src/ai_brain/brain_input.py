"""
Phase AB-1 — Narrative Brain input builder (replaces the starved wrapper input).

AI-0 autopsy proved the old input withheld price (on no-setup scans), candles,
position state, the brain's own history, protected swings, the liquidity draw,
and the bearish half of the toolbox — while feeding the machine's finished
conclusions. This builder gives the brain evidence on BOTH sides and flags
what it could not see (degraded[]), so starvation is visible instead of silent.

Pure assembly from the already-built snapshot + the NA-1 protected-swing state
+ stance memory. No model call here. Never raises.
"""
from toolbox.tool_library import eligible_tools

_TFS = ("15m", "5m", "3m", "1m")

#: BRAIN PRESENTATION WINDOWS — role-based, deterministic, uncurated.
#: Each timeframe gets the span its job needs rather than one uniform number.
_BRAIN_PATH_BARS = {"1m": 90, "3m": 60, "5m": 80, "15m": 32}

_PATH_SCHEMA = ["ts", "o", "h", "l", "c", "v", "t"]
#: `ts` carries MM-DD as well as the clock. A first cut emitted HH:MM only, and
#: measured against the real canonical store the 15m window reaches back across
#: a session boundary -- at the 15:43 ET scan it spanned 2026-08-11 AND
#: 2026-08-12. Yesterday's 14:15 bar would have been indistinguishable from
#: today's. Six bytes a bar is the cheapest honesty in this payload.
_PATH_LEGEND = ("ts=MM-DD HH:MM UTC, o/h/l/c=price, v=volume, "
                "t=S settled | F forming now (close may still move) | "
                "I historical bucket finished but INCOMPLETE (missing minutes, "
                "treat its OHLC as partial evidence) | U completeness unrecorded")

#: `I` is not a shade of `F`. A currently-forming bucket is realtime context
#: whose close will still move; a historical_incomplete bucket is FINISHED and
#: will never change, but was assembled from a hole in the canonical series.
#: Terra must not read damaged history as live price action.
_TEMPORAL_CODE = {"settled": "S", "forming": "F",
                  "historical_incomplete": "I", "unknown": "U"}


#: STEP 4B.12 §5 — THE EPISTEMIC BORDER CHECKPOINT.
#:
#: `liquidity["events"]` is a POSITIVE-ONLY inventory: a comprehension guarded by
#: `if sweep_detected`. Everything upstream had already been repaired to
#: distinguish "the detector ran and found nothing" from "the detector could not
#: answer" -- and this builder threw that passport away. Traced on the real tape:
#: liquidity_engine published capability, the snapshot preserved it, the archive
#: formatter preserved it, and the Terra payload contained no trace of it.
#:
#: Two ORTHOGONAL channels are published now:
#:
#:     events[]      positive facts, unchanged, still positive-only
#:     evaluation[]  detector evaluability, stated for EVERY timeframe
#:
#: Stated for every timeframe DELIBERATELY. A first design emitted evaluation
#: rows only for the exceptional timeframes, which would have required Terra to
#: infer "EVALUATED" from a MISSING row -- reintroducing absence-as-semantics one
#: layer later. Silence is evidence only where the detector had an opportunity to
#: speak, so the opportunity is enumerated rather than implied.
#:
#: Terra can now separate four states that were previously one:
#:
#:     event + DETECTOR_EVALUATED        positively found
#:     no event + DETECTOR_EVALUATED     detector ran, no positive
#:     no event + UNEVALUABLE_EVIDENCE   detector could not answer
#:     UNAVAILABLE_SENSOR                detector cannot answer, ever
#:
#: DETECTOR_EVALUATED is deliberately NOT called FALSE_PROVEN. `find_swings` and
#: other dependencies of these propositions are still inside the unfinished
#: adjacency audit, so the honest meaning is "the current detector executed under
#: the prerequisites presently modeled", nothing stronger.
_RAID_PROPOSITIONS = ("sweep_detected", "reclaim_detected")

_BRAIN_CAPABILITY = {
    "EVALUATED": "DETECTOR_EVALUATED",
    "UNEVALUABLE_EVIDENCE": "UNEVALUABLE_EVIDENCE",
    "UNAVAILABLE_SENSOR": "UNAVAILABLE_SENSOR",
}

_CAPABILITY_LEGEND = {
    "DETECTOR_EVALUATED": ("the current detector ran under the prerequisites "
                           "presently modeled and published its result — this "
                           "is NOT proof the pattern is absent"),
    "UNEVALUABLE_EVIDENCE": ("the detector could not answer: required evidence "
                             "was unavailable. Unknown, not absent."),
    "UNAVAILABLE_SENSOR": ("the detector cannot answer regardless of evidence. "
                           "Better candles would not change this."),
    "UNKNOWN": ("the producer stated no capability for this timeframe — treat "
                "as unknown, never as a negative"),
}


def _liquidity_evaluation(liq: dict) -> tuple:
    """(evaluation rows for every timeframe, declared sensor capabilities).

    The sensors block is an inventory of what producers ACTUALLY declared. It is
    not a completeness claim: a producer predating the capability contract
    declares nothing, and nothing is invented on its behalf.
    """
    rows, sensors = [], {}
    for tf in _TFS:
        block = liq.get(tf) or {}
        caps = block.get("proposition_capability") or {}
        reasons = block.get("capability_reason") or {}
        row = {"tf": tf}
        for name in _RAID_PROPOSITIONS:
            short = name.replace("_detected", "")
            if not block:
                row[short] = {"capability": "UNKNOWN",
                              "reason": "NO_DETECTOR_OUTPUT_FOR_TIMEFRAME"}
            elif name not in caps:
                row[short] = {"capability": "UNKNOWN",
                              "reason": "PRODUCER_DID_NOT_STATE_CAPABILITY"}
            else:
                entry = {"capability": _BRAIN_CAPABILITY.get(caps[name], "UNKNOWN")}
                if reasons.get(name):
                    entry["reason"] = reasons[name]
                row[short] = entry
        rows.append(row)

        # Sensor-scoped, never concept-scoped. `liquidity_engine.failed_breakout`
        # is unreachable by construction; that says nothing about whether failed
        # breakouts occur, and a sibling producer under a different sensor is
        # deliberately NOT folded in here -- handing Terra new market evidence is
        # a doctrine decision, not an epistemics repair.
        if caps.get("failed_breakout") == "UNAVAILABLE_SENSOR":
            rec = sensors.setdefault("liquidity_engine.failed_breakout", {
                "capability": "UNAVAILABLE_SENSOR",
                "reason": reasons.get("failed_breakout",
                                      "PREDICATE_UNREACHABLE_DOCTRINE_UNRESOLVED"),
                "timeframes": [],
                "scope_note": ("this is the capability of ONE sensor. It is not a "
                               "claim that failed breakouts did or did not occur, "
                               "and it does not speak for any other sensor."),
            })
            rec["timeframes"].append(tf)
    return rows, sensors


# STEP 4B.12 §4 UNIT 3 — THE SINGLE STRUCTURE-EPISTEMICS NORMALIZATION OWNER.
#
# Unit 2 taught the engine to distinguish an evaluated no-event from a
# transition it could not evaluate, and published the cause as
# `bos_evaluability` / `mss_evaluability`. Measured over the same 1000
# scan x timeframe opportunities, NOTHING consumed them: the two names appear in
# exactly one file, `structure_engine.py`. Terra saw `bool(struct["bos"])`, and
# `bool(False)`, `bool(None)` and "could not establish" are the same token.
#
# Four internal BOS states collapsed into `bos_event=False`:
#
#     EVALUATED_NO_EVENT                   630
#     EVALUATED_NO_EVENT_ALREADY_BEYOND    278
#     UNEVALUABLE_PREVIOUS_CLOSE             3
#     UNEVALUABLE_PREVIOUS_SLOT              1
#
# and two into `mss_event=False` (960 / 4). The collision is real, not
# theoretical: at 18:02 and 18:14 on 3m the witness rows are BYTE-IDENTICAL
# while one opportunity was evaluated and the other was
# UNEVALUABLE_PREVIOUS_CLOSE.
#
# ONE OWNER, deliberately. Both Terra-visible structure lanes (STRUCTURE_WITNESS
# and MTF_MARKET_STATE) and the derived `quiet` authority in embedding_v2 call
# THIS function. Two mappings would be two authorities for one epistemic fact,
# which is the defect class this unit exists to remove.
#
# NO `UNAVAILABLE_SENSOR` FOR STRUCTURE. The structure engine is present and
# runs; every measured failure is evidence-shaped (a previous slot, a close, a
# cadence). Calling it a missing sensor would claim better candles could not
# help, which is false here.
_STRUCTURE_UNKNOWN_REASON = "PRODUCER_DID_NOT_STATE_EVALUABILITY"

#: Block names owned by `market_state.mtf_market_state`. Mirrored as literals
#: rather than imported: `ai_brain` importing `market_state` would create the
#: dependency this decoration exists to avoid, and these are contract constants.
_MTF_CONFIRMED = "confirmed"
_MTF_REALTIME = "realtime"

#: The three capabilities structure can actually hold. UNAVAILABLE_SENSOR is
#: deliberately absent: the structure engine is present and runs.
#:
#: NOT published as a legend inside STRUCTURE_WITNESS. The payload already
#: carries `liquidity.capability_legend` with these same definitions, so a
#: second copy would be a second authority for the vocabulary -- and every
#: non-`_disclaimer` key in the witness is a TIMEFRAME by convention, so a
#: sibling metadata key reads as a timeframe row to anything iterating it.
STRUCTURE_CAPABILITIES = ("DETECTOR_EVALUATED", "UNEVALUABLE_EVIDENCE",
                          "UNKNOWN")


def structure_evaluation(evaluability) -> dict:
    """Producer evaluability token -> {capability, reason}.

    `EVALUATED` is the ONLY token that earns DETECTOR_EVALUATED. Anything else
    that the producer actually stated is UNEVALUABLE_EVIDENCE carrying the exact
    producer token as its reason -- the cause is never generalised away, because
    "could not read the previous close" and "cadence unknown" are different
    facts about the world.

    A producer that stated nothing (absent block, legacy contract, None) is
    UNKNOWN. It is NEVER promoted to DETECTOR_EVALUATED: inferring "evaluated"
    from silence is exactly the false-absence this repair exists to delete.
    """
    if not isinstance(evaluability, str) or not evaluability:
        return {"capability": "UNKNOWN", "reason": _STRUCTURE_UNKNOWN_REASON}
    if evaluability == "EVALUATED":
        return {"capability": "DETECTOR_EVALUATED", "reason": None}
    return {"capability": "UNEVALUABLE_EVIDENCE", "reason": evaluability}


def structure_evaluations(block) -> dict:
    """Both proposition evaluations for one timeframe's structure block.

    Named `bos_evaluation` / `mss_evaluation` rather than `bos` / `mss`:
    `bos_event` already owns the event proposition, and a sibling key with the
    bare name would read as a second, competing answer to the same question.
    """
    b = block if isinstance(block, dict) else {}
    return {"bos_evaluation": structure_evaluation(b.get("bos_evaluability")),
            "mss_evaluation": structure_evaluation(b.get("mss_evaluability"))}


def _mtf_with_structure_evaluations(state, struct) -> dict:
    """MTF_MARKET_STATE carrying the SAME epistemics as STRUCTURE_WITNESS.

    MTF_MARKET_STATE is the SECOND Terra-visible structure lane, and it reads
    the same producer: `bos_event` is None and `mss_event` is False both when
    the engine evaluated and found nothing AND when it could not evaluate at
    all. Repairing only the witness would have left Terra receiving the same
    false absence through another factual channel.

    Decorated HERE rather than inside `market_state.mtf_market_state` for a
    layering reason, not a stylistic one: nothing under `market_state/` imports
    `ai_brain/`, and making it do so to reach the normalizer would invert the
    dependency to place a Brain-boundary concern inside a producer. This is the
    same boundary at which `_liquidity_evaluation` already decorates liquidity,
    and it keeps ONE owner for the mapping.

    The producer object is never mutated -- the snapshot has other consumers,
    and none of them asked for this.
    """
    src = state if isinstance(state, dict) else {}
    out = dict(src)
    tfs = src.get("timeframes")
    if not isinstance(tfs, dict):
        return out
    rebuilt = {}
    for tf, facts in tfs.items():
        if not isinstance(facts, dict):
            rebuilt[tf] = facts
            continue
        ev = structure_evaluations((struct or {}).get(tf))
        row = dict(facts)
        # Each evaluation sits beside the proposition it qualifies: the BOS
        # event is realtime, the MSS flag is pivot-confirmed. Putting both in
        # one block would misfile one of them.
        if isinstance(row.get(_MTF_REALTIME), dict):
            row[_MTF_REALTIME] = {**row[_MTF_REALTIME],
                                  "bos_evaluation": ev["bos_evaluation"]}
        if isinstance(row.get(_MTF_CONFIRMED), dict):
            row[_MTF_CONFIRMED] = {**row[_MTF_CONFIRMED],
                                   "mss_evaluation": ev["mss_evaluation"]}
        rebuilt[tf] = row
    out["timeframes"] = rebuilt
    return out


def _compact_path(recent: list, limit: int) -> list:
    """The last `limit` canonical bars as compact rows.

    Temporal status is NON-NEGOTIABLE per bar. A forming 15m bucket and a
    settled one may not look identical to the reader -- that is the whole of
    CONTINUITY-2G, and it survives compaction rather than being a casualty of it.
    A forming bar is INCLUDED and LABELLED, never dropped: realtime context may
    be forming, confirmed structure must rest on settled evidence.
    """
    out = []
    for c in (recent or [])[-int(limit):]:
        ts = str(c.get("timestamp") or "")
        stamp = f"{ts[5:10]} {ts[11:16]}" if len(ts) >= 16 else ts
        out.append([stamp,
                    c.get("open"), c.get("high"), c.get("low"), c.get("close"),
                    int(c.get("volume") or 0),
                    _TEMPORAL_CODE.get(str(c.get("temporal_status") or "unknown"), "U")])
    return out


def _candles(snapshot: dict) -> dict:
    """Recent candle context per TF (bodies/wicks/close). Live snapshots carry
    timeframes; trimmed archives do not — absence is reported in degraded[].

    The producer key is `recent_candles`. This read `candles`, which no producer
    emits, so every live scan silently fell through to the single-bar fallback:
    the brain was handed one candle per timeframe instead of a five-bar window,
    and `available` stayed True because last_candle existed — so degraded[] never
    reported it. Verified on 2026-07-24 RTH: recent_candles held 5 bars on all
    four timeframes on every scan while the payload carried 1.

    `candles` is kept as a secondary read so archives written under the old key
    still resolve.
    """
    tfs = snapshot.get("timeframes", {}) or {}
    out, have_any, thin, unknown = {}, False, [], []
    for tf in _TFS:
        t = tfs.get(tf, {}) or {}
        recent = (t.get("recent_candles") or t.get("candles")
                  or ([t["last_candle"]] if t.get("last_candle") else []))
        if recent:
            have_any = True
            if len(recent) < 2:
                thin.append(tf)
            c = recent[-1]
            # CONTINUITY-2G — the NEWEST bar is the one that may still be
            # forming, so its temporal status is lifted out of `recent[]` and
            # stated at the top of the timeframe block. Buried metadata is
            # metadata the reader can miss; every bar in `recent` carries its
            # own status too.
            status = c.get("temporal_status") or "unknown"
            if status == "unknown":
                unknown.append(tf)
            out[tf] = {
                # PHASE 4A — THE WINDSHIELD.
                #
                # `recent` carried 5 bars per timeframe: 5 minutes of 1m, 25 of
                # 5m. A discretionary entry depends on retracement structure on
                # exactly those timeframes, so the read was being made through a
                # four-minute window while the tape ran an hour.
                #
                # `path` is a neutral temporal window -- the last N canonical
                # bars, nothing selected, ranked or curated by mechanics. Event
                # chronology may point at the interesting parts; it may not
                # decide which part of the chart Terra is allowed to look at.
                #
                # Compact rows because a bar costs 325 bytes in the rich shape
                # and 53 as an array. `range`, `body_size`, `upper_wick`,
                # `lower_wick` and `direction` are all reconstructible from OHLC
                # and are not repeated 262 times; the tokens buy span instead.
                "path": _compact_path(recent, _BRAIN_PATH_BARS.get(tf, 5)),
                # Compatibility / near-term detail view, NOT the long-term
                # sensory contract. Phase 4M decides whether these fifteen
                # fields still carry unique information.
                "recent": recent[-5:],
                "last_candle_temporal_status": status,
                "last_candle_members": c.get("members"),
                "last_candle_expected_members": c.get("expected_members"),
                "last_close": c.get("close"),
                "last_high":  c.get("high"),
                "last_low":   c.get("low"),
                "body":  (round(abs(c["close"] - c["open"]), 4)
                          if c.get("close") is not None and c.get("open") is not None else None),
            }
    # Stated ONCE. Repeating the schema and legend inside each timeframe block
    # is four copies of the same sentence for no added truth.
    return {"by_tf": out, "available": have_any, "single_bar_only": thin,
            "temporal_status_unknown": unknown,
            "path_schema": _PATH_SCHEMA, "path_legend": _PATH_LEGEND}


def _authority_temporal_class(snapshot: dict) -> str:
    """What `market.volatility_state` ACTUALLY is.

    CONTINUITY-2E.3A. `market_regime.volatility_state` is sourced from the 15m
    composed block, so the label is read from that same block rather than
    asserted alongside it. Never raises.

      authority_settled_baseline    settled baseline, realtime may only tighten
      unknown_no_settled_baseline   fail-closed: no settled view existed
      unavailable                   the 15m block itself is absent
    """
    block = (snapshot.get("volatility") or {}).get("15m")
    if not isinstance(block, dict) or not block:
        return "unavailable"
    cls = block.get("temporal_class")
    return "authority_settled_baseline" if cls == "authority" else str(cls or "unknown")


def _realtime_volatility(snapshot: dict) -> dict:
    """The LIVE volatility read per timeframe, explicitly marked as realtime.

    CONTINUITY-2E.3. The authority view is a settled baseline the live read may
    only tighten, so on its own it cannot answer "is it violent right now" --
    which is a legitimate and useful question for a discretionary read. This
    block answers it, and says what it is. `realtime_tightened` names the one
    case where the two disagree and the live read won.

    Absent on trimmed archives written before 2E.3; the key is simply omitted
    rather than faked. Never raises.
    """
    live = snapshot.get("volatility_realtime")
    if not isinstance(live, dict) or not live:
        return {}
    authority = snapshot.get("volatility") or {}
    tfs = snapshot.get("timeframes") or {}
    out = {}
    for tf in _TFS:
        block = live.get(tf) or {}
        if not block:
            continue
        # CONTINUITY-2E.3A — DERIVED, never asserted. This published a hardcoded
        # `includes_forming_bucket: True`, which is false for 1m in production
        # (the TopstepX aggregator never emits a developing minute) and false for
        # any higher timeframe evaluated exactly on a bucket boundary. Terra was
        # being told the evidence contained a forming candle when it did not.
        #
        # The answer comes from the 2G metadata already on the candles -- there is
        # no second completeness detector, and there must not be one.
        status = ((tfs.get(tf) or {}).get("last_candle") or {}).get(
            "temporal_status", "unknown")
        out[tf] = {
            "state": block.get("state"),
            "volatility_score": block.get("volatility_score"),
            "range_acceleration": block.get("range_acceleration"),
            "temporal_class": "realtime",
            "newest_bucket_temporal_status": status,
            # True / False only when the status is known. `None` where 2G itself
            # reports `unknown` -- claiming False there would assert settlement
            # that was never recorded.
            "includes_forming_bucket": (True if status == "forming"
                                        else False if status == "settled"
                                        else None),
            "settled_state": (authority.get(tf) or {}).get("settled_state"),
            "realtime_tightened": bool(
                (authority.get(tf) or {}).get("realtime_tightened")),
        }
    return out


def _continuity_markers(snapshot: dict) -> list:
    """`candle_gap:...` entries from the scan's own continuity report.

    Imported lazily and defended: a payload that cannot describe its own gaps
    must still be delivered, because refusing to build the input would blind the
    Brain completely rather than partially.
    """
    report = snapshot.get("candle_continuity")
    if not isinstance(report, dict):
        return []
    try:
        from data_feed.candle_continuity import degraded_markers
        return degraded_markers(report)
    except Exception:  # noqa: BLE001
        return ["candle_continuity_unreadable"]


def _settled_price(snapshot: dict, candles: dict) -> tuple:
    """The newest SETTLED close, and WHICH source supplied it.

    EXEC-PRICE-FRESHNESS-1 (2026-08-20): the basis was never published, so the
    1m -> 3m -> 5m -> 15m fallback below was invisible. A gapped 1m stream
    silently promoted a FIFTEEN MINUTE old close into `current_price`, and
    nothing in the payload said so. The price is unchanged; what it is has to
    travel with it.

    This is market truth, not an executable price. See
    `broker/topstepx_execution_price.py` for the number a trade is priced from.
    """
    for tf in ("1m", "3m", "5m", "15m"):
        c = candles["by_tf"].get(tf, {})
        if c.get("last_close") is not None:
            return float(c["last_close"]), f"settled_close:{tf}"
    ez = (snapshot.get("trade_intent", {}) or {}).get("entry_zone") or {}
    for k in ("current_price",):
        if ez.get(k) is not None:
            return float(ez[k]), "trade_intent.entry_zone"
    pm = snapshot.get("position_monitor", {}) or {}
    if pm.get("current_price") is not None:
        return float(pm["current_price"]), "position_monitor"
    return None, None


def _current_price(snapshot: dict, candles: dict) -> "float | None":
    return _settled_price(snapshot, candles)[0]


def _tool_catalog(snapshot: dict) -> list:
    """The Step 7 authorized tool catalog, imported lazily.

    `luna_candidate_producer` owns the catalog because it owns the gate that
    enforces it -- one definition, so what Terra is shown and what mechanics
    accept cannot drift apart. Imported here rather than at module scope to
    avoid a broker/ai_brain import cycle. Never raises: a payload that cannot
    describe the toolbox must still be delivered, and an empty catalog already
    means "nothing detected", which is the safe reading.
    """
    try:
        from broker.luna_candidate_producer import authorized_tool_catalog
        return authorized_tool_catalog(snapshot)
    except Exception:  # noqa: BLE001
        return []


def _two_sided_inventory(snapshot: dict) -> dict:
    """Both directions' PHYSICALLY WITNESSED tool inventory.

    PHASE 3 (2026-08-12). This used to read:

        tools = eligible_tools(pb, d) if pb != "no_playbook" else []

    which meant the mechanical playbook decided what Terra was allowed to SEE,
    even after Phase 2 made the toolbox generate both sides. Terra was told "no
    inventory" when the truth was "mechanics has no recommendation" -- and she
    said so, honestly, 81 times: *"no executable playbook/tool inventory is
    available"*.

    The list is now the truthful instance inventory. `mechanical_*_recommendation`
    is carried alongside it as an opinion Terra may weigh and may ignore.
    """
    pb = (snapshot.get("playbook", {}) or {}).get("selected_playbook") or "no_playbook"
    pdir = (snapshot.get("playbook", {}) or {}).get("direction")
    tb = snapshot.get("toolbox", {}) or {}
    inv = {"bullish": [], "bearish": []}
    for i in tb.get("tool_instances") or []:
        side = i.get("direction")
        if side in inv:
            inv[side].append({
                "tool": i.get("tool"), "tool_id": i.get("tool_id"),
                "source_tf": i.get("source_tf"),
                "directional_witness": i.get("directional_witness"),
                "local_evidence_score": i.get("local_evidence_score"),
                "global_context_score": i.get("global_context_score"),
                "score": i.get("score"), "live_scored": True})
    return {"active_playbook": pb, "active_direction": pdir,
            "mechanical_playbook_recommendation": pb,
            "mechanical_direction_recommendation": pdir,
            "bullish": inv["bullish"], "bearish": inv["bearish"],
            "note": "Both sides are physically witnessed, directionally anchored "
                    "inventory. mechanical_playbook_recommendation and "
                    "mechanical_direction_recommendation are OPINIONS: they do "
                    "not authorise, restrict or gate this list. 'no_playbook' "
                    "means mechanics has no preferred playbook, never that no "
                    "tool exists. An empty side means nothing was witnessed on "
                    "that side."}


def _position(snapshot: dict) -> dict:
    pm = snapshot.get("position_monitor", {}) or {}
    if not pm.get("has_open_position"):
        return {"position_open": False}
    return {
        "position_open":   True,
        "direction":       pm.get("side"),
        "qty":             pm.get("qty"),
        "entry_price":     pm.get("avg_entry_price"),
        "current_price":   pm.get("current_price"),
        "unrealized_pnl":  pm.get("unrealized_pnl"),
        "stop_reference":  pm.get("stop_reference"),
        "stop_distance":   pm.get("stop_distance"),
        "thesis_health":   (snapshot.get("thesis_monitor", {}) or {}).get("status"),
    }


def _protected(snapshot: dict, price) -> dict:
    ps = snapshot.get("protected_swings", {}) or {}
    ph, pl = ps.get("protected_high"), ps.get("protected_low")
    def rel(level, side):
        if level is None or price is None:
            return "none"
        lv = level["level"]
        if side == "high":
            if price > lv: return "violating"
            return "approaching" if (lv - price) / lv < 0.003 else "below"
        else:
            if price < lv: return "violating"
            return "approaching" if (price - lv) / lv < 0.003 else "above"
    return {
        "protected_high": ph, "protected_high_status": rel(ph, "high"),
        "protected_low":  pl, "protected_low_status":  rel(pl, "low"),
        # MTF-DELIVERY (2026-08-11). This function REBUILT the block and
        # silently dropped `by_timeframe`, so `authorized_invalidation_catalog`
        # found no per-timeframe registry and fell back to the legacy summary
        # branch -- emitting a single INV_PH_1 / INV_PL_1 pair.
        #
        # Live at 10:32:07: the tracker had registered protected highs on 1m
        # (29773.75, 27.75pt), 3m and 5m (29793.00, 47.00pt). Terra was handed
        # ONE side-valid bearish stop, the 47-point one, and the candidate died
        # on the 40-point ceiling while a 27.75-point execution-timeframe
        # structure existed in the same snapshot and was never offered.
        #
        # v10 built the per-timeframe registry and v11 pinned the catalog's
        # behaviour, but nothing asserted this hop DELIVERED it. Pass it
        # through; the summary fields above are untouched for their consumers.
        "by_timeframe": ps.get("by_timeframe") or {},
        "roles": ps.get("roles") or {},
    }


def _session_context_block(snapshot: dict) -> dict:
    """Prior-session context, compact. Interpretation only -- it authorises
    nothing, and the note inside the block says so to the reader as well."""
    try:
        from market_data.session_context import brain_block
        return brain_block(snapshot.get("session_context") or {})
    except Exception:  # noqa: BLE001 -- context must never break the payload
        return {"available": False, "trading_day": None, "contexts": {}}


def _session_po3_block(snapshot: dict) -> dict:
    """The canonical session phase, in the smallest form that can be reasoned on.

    Absence is stated, never faked: a snapshot without the block reports
    `available: False` so the Brain can tell "no phase authority ran" from "the
    phase authorizes entry".
    """
    b = (snapshot or {}).get("session_po3")
    if not isinstance(b, dict) or not b.get("phase"):
        return {"available": False, "phase": None, "new_entry_allowed": None}
    rng = b.get("range") or {}
    exc = b.get("excursion") or {}
    manip = b.get("manipulation") or {}
    return {
        "available": True,
        "phase": b.get("phase"),
        "new_entry_allowed": b.get("new_entry_allowed"),
        "block_reason": b.get("block_reason"),
        "range": ({"high": rng.get("high"), "low": rng.get("low"),
                   "age_bars": rng.get("age_bars"),
                   "established": rng.get("established")} if rng else None),
        "excursion": ({"side": exc.get("side"), "peak": exc.get("peak"),
                       "reentered": exc.get("reentered"),
                       "closes_outside": exc.get("consecutive_outside")}
                      if exc else None),
        "manipulation": {"classification": manip.get("classification"),
                         "direction": manip.get("direction"),
                         "conflicted": manip.get("conflicted")},
        "distribution_direction": b.get("distribution_direction"),
        "preferred_playbook_families": b.get("preferred_playbook_families") or [],
        "transition_reason": b.get("reason"),
    }


def build_brain_input(snapshot: dict, stance_history: dict) -> dict:
    """Full two-sided evidence payload for the narrative brain. Never raises."""
    try:
        degraded = []
        candles = _candles(snapshot)
        if not candles["available"]:
            degraded.append("candles_unavailable")
        elif candles["single_bar_only"]:
            # One bar is not a window; the brain cannot read sequence from it.
            degraded.append("single_bar_only:" + ",".join(candles["single_bar_only"]))
        # CONTINUITY-2G — a timeframe whose newest bar cannot state whether it is
        # settled or forming is a DEGRADED input, not a normal one. Older
        # archives and hand-built fixtures land here; live scans never should.
        # Absence stays absence.
        if candles.get("temporal_status_unknown"):
            degraded.append("candle_temporal_status_unknown:"
                            + ",".join(candles["temporal_status_unknown"]))
        price, price_basis = _settled_price(snapshot, candles)
        if price is None:
            degraded.append("current_price_unavailable")
        # EXEC-PRICE-FRESHNESS-1. A settled close from anything but the finest
        # timeframe is minutes old. It stays usable as market truth and is
        # stated as degraded, because absence of freshness is absence.
        elif price_basis != "settled_close:1m":
            degraded.append("settled_price_basis:" + str(price_basis))
        # DEALING-RANGE-PAYLOAD-1 (2026-08-21). `market_context.dealing_range`
        # was computed on EVERY scan, written into memory records for later
        # retrieval, and never shown to the Brain at decision time.
        #
        # On 2026-08-20 at 11:03:34 it held high 29470.25, low 29240.25,
        # midpoint 29355.25, position 0.823, zone "premium" -- a range whose
        # HIGH was the protected level Luna was reasoning about and whose LOW
        # was her own sell-side objective. She was deciding where to sell from
        # the top of an auction while the engine already knew she was 82.3%
        # through it, and said nothing.
        #
        # PASS-THROUGH ONLY. Nothing is recomputed here; `_dealing_range` in
        # `structure/market_context.py` remains the sole author, and an absent
        # range stays absent rather than being reconstructed downstream.
        dealing_range = ((snapshot.get("market_context") or {})
                         .get("dealing_range") or {})
        if not dealing_range.get("high"):
            degraded.append("dealing_range_unavailable")
        # The executable picture, captured by the scan from the live quote
        # stream. Absent in lanes that have no stream (replay, fixtures), where
        # the block says so positively rather than going missing.
        execution_price = snapshot.get("execution_price") or {}
        if not execution_price.get("available"):
            degraded.append("execution_price_unavailable:"
                            + str(execution_price.get("unavailable_reason")
                                  or "NO_QUOTE_PROVIDER"))
        elif not execution_price.get("fresh"):
            degraded.append("execution_price_stale")

        sc = snapshot.get("shared_context", {}) or {}
        po3 = snapshot.get("po3", {}) or {}
        liq = snapshot.get("liquidity", {}) or {}
        na = snapshot.get("narrative_authority", {}) or {}
        struct = snapshot.get("structure", {}) or {}
        mr = snapshot.get("market_regime", {}) or {}

        # PRIOR-SESSION-DEGRADATION-TRUTHFULNESS-1 (2026-08-23). This was
        # UNCONDITIONAL, written when the data plane genuinely had no yesterday
        # (MAP-0). HTF-MEM-1 shipped 2026-07-04 and has published prior-day
        # OHLC, swept/untapped draw levels and gap context ever since, so the
        # payload was telling the Brain "prior-session levels are absent" on the
        # same scan that handed it 29759.00 as an untapped buy-side draw.
        #
        # A degradation marker is a statement about what the Brain CANNOT see.
        # Emitting it falsely is worse than omitting it: the Brain reads
        # `degraded[]` and hedges against context it actually has.
        #
        # Absence is now read from the engine's own representation of it --
        # `_empty()` returns `previous_session_context: None` -- rather than a
        # second definition of "present" invented here. On day one, or whenever
        # HTF memory cannot serve a prior session, the marker still fires.
        #
        # SCOPE: prior ET-calendar-day context, which is what HTF memory builds.
        # A separately published RTH-only (09:30-16:00) prior high/low, split
        # from globex, is NOT part of this and is deliberately not claimed here.
        if not (snapshot.get("htf_memory") or {}).get("previous_session_context"):
            degraded.append("prior_session_levels_absent")

        # CANDLE-CONTINUITY (2026-08-11). The Brain must be told what it cannot
        # see. On 2026-08-11 it received five 1m bars spanning a twenty-minute
        # hole -- 14:41Z then 15:01Z -- with `degraded[]` carrying only
        # `prior_session_levels_absent`, so a payload missing the entire buy-side
        # manipulation through 29,800 read as an ordinary contiguous window.
        # Absence stays absence: it is stated, never inferred and never silent.
        degraded.extend(_continuity_markers(snapshot))

        _liq_evaluation, _liq_sensors = _liquidity_evaluation(liq)

        return {
            "timestamp": snapshot.get("timestamp"),
            "session":   snapshot.get("session"),
            "degraded":  degraded,
            "market": {
                # SETTLED market truth. Unchanged semantics and unchanged name:
                # every structural consumer still reads exactly what it read
                # before. `settled_price_basis` states which timeframe's close
                # this is, which was previously unknowable.
                "current_price": price,
                "settled_price_basis": price_basis,
                # WHERE PRICE SITS IN THE BROADER AUCTION. Location context —
                # never direction. See the prompt addendum.
                "dealing_range": dealing_range,
                # EXEC-PRICE-FRESHNESS-1 — the EXECUTABLE picture. Bid, ask,
                # age and freshness from the live stream. Candidate economics
                # price from here; a stale or absent block refuses the trade
                # rather than falling back to the settled close above.
                "execution_price": execution_price,
                # Stated once for every timeframe below.
                "price_path_schema": candles.get("path_schema"),
                "price_path_legend": candles.get("path_legend"),
                "candles": candles["by_tf"],
                # CONTINUITY-2E.3 — `volatility_state` is the COMPOSED AUTHORITY
                # view (settled baseline; the live read may tighten it, never
                # loosen it). Named so it cannot be mistaken for either input.
                #
                # 2E.3A: the CLASS IS READ OFF THE OBJECT, not asserted. It was a
                # hardcoded "authority_settled_baseline", which would have kept
                # claiming a settled baseline even if compose_authority had
                # returned its no-baseline block. A label must describe the thing
                # actually delivered.
                "volatility_state": mr.get("volatility_state"),
                "volatility_state_temporal_class":
                    _authority_temporal_class(snapshot),
                # The live read, offered separately and labelled. 2G told the
                # Brain which CANDLES are forming; that does not tell it which
                # VOLATILITY CALCULATION used which evidence. Realtime volatility
                # may inform cognition AS realtime volatility -- it may not
                # masquerade as a settled regime conclusion.
                "realtime_volatility": _realtime_volatility(snapshot),
                "expansion_state":  mr.get("expansion_state"),
            },
            # AI-BRAIN-H2 — structure is WITNESS ONLY and NON-DIRECTIONAL here.
            # The directional fields (bias, directional state) are removed from
            # the LLM payload — they were the AB-5A-S leak that let structure
            # override clean delivery. Only mechanical, non-directional facts
            # (swing levels + break/shift event booleans) remain.
            "STRUCTURE_WITNESS": {
                "_disclaimer": ("STRUCTURE WITNESS ONLY — NOT DIRECTIONAL "
                                "AUTHORITY. Do not use to choose direction; only "
                                "to note possible lag/conflict."),
                # UNIT 3 — the event booleans keep their contract, and each is
                # now accompanied by the EVALUABILITY of the proposition it
                # answers. `bos_event: false` alone was four different states.
                # Together the pair says which one:
                #
                #     event true  + DETECTOR_EVALUATED    evaluated positive
                #     event false + DETECTOR_EVALUATED    evaluated negative
                #     event false + UNEVALUABLE_EVIDENCE  could not establish
                #     event false + UNKNOWN               producer said nothing
                #
                # A row is emitted for EVERY timeframe, present or not, so Terra
                # never has to infer "evaluated" from a missing row -- the same
                # rule the liquidity contract already follows.
                **{tf: {"last_swing_high": (struct.get(tf, {}) or {}).get("last_swing_high"),
                        "last_swing_low":  (struct.get(tf, {}) or {}).get("last_swing_low"),
                        "bos_event": bool((struct.get(tf, {}) or {}).get("bos")),
                        "mss_event": bool((struct.get(tf, {}) or {}).get("mss")),
                        **structure_evaluations(struct.get(tf))}
                   for tf in _TFS},
            },
            "delivery": {
                "state":      sc.get("delivery_state"),
                "confidence": sc.get("delivery_confidence"),
                "continuation_intact": sc.get("continuation_intact"),
                "exhaustion_present":  sc.get("exhaustion_present"),
                "po3_15m": {"phase": (po3.get("15m", {}) or {}).get("phase"),
                            "manipulation_direction": (po3.get("15m", {}) or {}).get("manipulation_direction"),
                            "distribution_direction": (po3.get("15m", {}) or {}).get("distribution_direction")},
                "po3_alignment": po3.get("alignment"),
                # LUNA-SESSION-PO3-AUTHORITY-1. The per-TF PO3 above is texture;
                # THIS is the session's phase and the reason a new entry may or
                # may not exist. Deliberately compact -- the phase, the range it
                # is about, what left it, what the confluence detector actually
                # said (classification AND direction, both of which used to be
                # computed and discarded), and one line of why. Luna does not
                # need the scoring internals to reason about the phase, and
                # flooding the payload would cost the fields that matter.
                "session_po3": _session_po3_block(snapshot),
            },
            # CROSS-SESSION CONTEXT, published BESIDE delivery rather than
            # inside it. What Asia, London and premarket already did, with each
            # context's availability stated: an unavailable context shows its
            # REASON, never a high/low that reads as known.
            "session_context": _session_context_block(snapshot),
            "liquidity": {
                "events": [{"tf": tf, "sweep": (liq.get(tf, {}) or {}).get("sweep_direction"),
                            "reclaim": (liq.get(tf, {}) or {}).get("reclaim_detected")}
                           for tf in _TFS if (liq.get(tf, {}) or {}).get("sweep_detected")],
                "nearest_buy_side":  next(((liq.get(tf, {}) or {}).get("nearest_buy_side_liquidity")
                                           for tf in _TFS if (liq.get(tf, {}) or {}).get("nearest_buy_side_liquidity")), None),
                "nearest_sell_side": next(((liq.get(tf, {}) or {}).get("nearest_sell_side_liquidity")
                                           for tf in _TFS if (liq.get(tf, {}) or {}).get("nearest_sell_side_liquidity")), None),
                "active_draw": na.get("active_liquidity_draw"),
                # STEP 4B.12 §5 — evaluability, orthogonal to `events`.
                # `events` says what was FOUND; `evaluation` says what could be
                # ASKED. An empty `events` no longer means "no sweep": read the
                # matching evaluation row.
                "evaluation": _liq_evaluation,
                "capability_legend": _CAPABILITY_LEGEND,
                # Declared sensor capabilities. Present only where a producer
                # actually declared one; nothing is invented for producers that
                # predate the contract.
                **({"sensors": _liq_sensors} if _liq_sensors else {}),
            },
            "protected_swings": _protected(snapshot, price),
            # ACTIVE-PATH-STATE-1 (2026-08-24) — WHICH SIDE OWNS THE TAPE.
            #
            # Everything else in this payload is instantaneous: a boolean that
            # is true this scan and gone the next, or the single current
            # protected level with its predecessors already popped. On
            # 2026-08-24 at 10:52 three models on identical payloads answered
            # the ownership question BEARISH, 0 of 19 identifying the bullish
            # leg behind 29 structural breaks and three successively higher
            # defended lows -- because ownership could only be read off the
            # bearish gap sitting at price. This is the accumulated answer.
            #
            # EVIDENCE, NOT AUTHORISATION. It forbids no direction; a lawful
            # counter-path reaction stays executable. Absent when the scan
            # cycle could not derive it, which is a different fact from
            # "no path is established" and is published as such.
            "active_path_state": (snapshot or {}).get("active_path_state"),
            # STRUCTURE-FLIP (2026-08-11) — the SECOND invalidation family,
            # kept beside protected swings rather than merged into them. A
            # broken swing low is not a protected high; conflating them would
            # destroy the ability to tell the two facts apart downstream.
            # The registry that owns lifecycle lives on the scan cycle; this
            # only carries whatever it published for this snapshot.
            "structure_flips": list(snapshot.get("structure_flips") or []),
            # MTF_MARKET_STATE (2026-08-11) — its OWN key, deliberately not
            # folded into STRUCTURE_WITNESS. That contract stays exactly as it
            # is: witness-only, non-directional, no execution/invalidation/
            # objective authority. This carries per-timeframe ROLES, the
            # confirmed/realtime split, and the CONFLICTS between timeframes.
            # It states no direction of its own -- Terra still owns that.
            "MTF_MARKET_STATE": _mtf_with_structure_evaluations(
                snapshot.get("mtf_market_state"), struct),
            # ROADMAP STEP 7 (2026-08-12) — the execution expressions the
            # DETERMINISTIC toolbox actually detected this snapshot, published
            # beside the invalidation and objective catalogs Terra already
            # selects from. Terra may only be executed through an expression
            # that appears here, is on its side, and is execution_eligible.
            # Entries with execution_eligible False are shown deliberately
            # (CONTINUITY-2F witness/authority split) so the Brain still sees a
            # forming opportunity it may describe but may not trade. An EMPTY
            # catalog is a legitimate market result and is never manufactured.
            "authorized_tool_catalog": _tool_catalog(snapshot),
            "playbook_toolbox": _two_sided_inventory(snapshot),
            "position": _position(snapshot),
            "stance_history": stance_history,
            # AI-BRAIN-H2 — environmental only. The directional NA/council
            # "suggested side" fields are isolated OUT of the LLM payload so the
            # Brain derives direction independently from clean evidence.
            "governance_context": {
                "regime": mr.get("regime_label"),
            },
            "conflicts": na.get("conflict_flags", []),
            "warnings":  na.get("warnings", []),
            # NEWS-1 — non-directional market-awareness context (present only
            # when NEWS_LAYER_ENABLED attached it upstream). Context only: it
            # carries event-risk/awareness, never a direction or a trade.
            **({"news_context": snapshot["news_context"]}
               if isinstance(snapshot.get("news_context"), dict) else {}),
            # HTF-MEM-1 — multi-day context for thesis quality (context only;
            # the Brain may weigh it, it can never be forced by it).
            **({"htf_memory": snapshot["htf_memory"]}
               if isinstance(snapshot.get("htf_memory"), dict) else {}),
            # VOLUME-WITNESS — non-directional participation evidence (present
            # only when VOLUME_WITNESS attached it upstream). Conviction/quality
            # context only; it never carries or implies a direction.
            **({"volume_witness": snapshot["volume_witness"]}
               if isinstance(snapshot.get("volume_witness"), dict) else {}),
        }
    except Exception as exc:  # noqa: BLE001
        return {"timestamp": snapshot.get("timestamp"), "degraded": [f"input_error:{exc}"]}
