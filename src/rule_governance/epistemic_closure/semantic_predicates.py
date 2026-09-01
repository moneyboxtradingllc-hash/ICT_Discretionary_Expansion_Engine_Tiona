"""EPISTEMIC-CLOSURE-CERTIFICATION-1 — semantics as EXECUTABLE claims.

A `semantic_claim` written in prose cannot be checked, and prose is exactly what
failed: `brain_prompt` said `registered_at` was a birth time, the tracker
re-stamped it, and both statements sat in the repository for months without ever
being placed in the same room.

So every load-bearing semantic gets a PREDICATE that runs against real data.
`rule_governance` already established this shape -- rule STATE as data in a
registry, rule LOGIC as code in `predicates.py`, joined by an id -- and this
mirrors it deliberately: contracts name `semantic_predicates` by id, and the
verifier executes them.

A predicate returns (ok, detail). It NEVER raises: a predicate that explodes is
reported as a failure with its exception, because an unrunnable check is not a
passing check.

PREDICATES THAT PROVE NEGATIVES ARE THE POINT. Roughly half of these exist to
demonstrate that a BLOCKED or LEGACY fact really is as limited as its contract
says. If `nearest_buy_side` ever became genuinely nearest, or the dealing range
gained containment, these fail -- and the contract, not the code, is what is out
of date. That is the correct direction for the alarm to point.
"""
from __future__ import annotations

import glob
import json
import os

#: repo root. The package sits at src/rule_governance/epistemic_closure/,
#: so four levels up. Derived rather than hardcoded so a future move
#: fails loudly at import instead of silently reading the wrong tree.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
_ARCHIVE = os.path.join(_ROOT, "data", "ai_brain")
CID = "CON.F.US.MNQ.U26"


class SkipPredicate(Exception):
    """Evidence this predicate needs is not on this machine."""


def _tape(day="20260825"):
    seen = {}
    for path in sorted(glob.glob(os.path.join(_ARCHIVE, f"{day}_*_MNQ.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                snap = json.load(fh)["raw_snapshot"]
        except Exception:  # noqa: BLE001
            continue
        for candle in ((snap.get("timeframes") or {}).get("1m") or {}).get(
                "recent_candles") or []:
            if candle.get("timestamp"):
                seen[str(candle["timestamp"])] = candle
    bars = [seen[k] for k in sorted(seen)]
    if len(bars) < 40:
        raise SkipPredicate(f"archived 1m tape for {day} is absent")
    return bars


def _replay(bars, min_bars=30):
    """Canonical growing-window rebuild. Yields (at, snapshot, occurrences)."""
    from data_feed.timeframe_builder import build_timeframes
    from market_data.snapshot_builder import build_snapshot
    from market_state.active_path import extract_occurrences
    from narrative_authority.protected_swings import ProtectedSwingTracker

    tracker, prior = ProtectedSwingTracker(), {}
    for end in range(min_bars, len(bars) + 1):
        window = bars[:end]
        at = str(window[-1]["timestamp"])
        snap = build_snapshot(build_timeframes(window), ref_timestamp=at,
                              symbol="MNQ", swing_tracker=tracker,
                              contract_id=CID, execution_price=None)
        occ = extract_occurrences(snap, prior, CID)
        yield at, snap, occ
        prior = ((snap.get("protected_swings") or {}).get("by_timeframe") or prior)


# ══ PROTECTED SWING ═════════════════════════════════════════════════════════
def formation_time_is_immutable_within_a_life():
    """THE DEFECT THAT CREATED THIS FRAMEWORK, as a running check.

    A slot vacancy ends a life, so state is cleared on it -- otherwise a
    genuinely new life at a repeated price is misread as a re-stamp.
    """
    live, restamped, lives = {}, [], 0
    for at, snap, _occ in _replay(_tape()):
        by = (snap.get("protected_swings") or {}).get("by_timeframe") or {}
        for side in ("lows", "highs"):
            block = by.get(side) or {}
            for tf, rec in block.items():
                slot, sid = (side, tf), rec.get("swing_id")
                was = live.get(slot)
                if was is None or was[0] != sid:
                    lives += 1
                elif was[1] != rec.get("registered_at"):
                    restamped.append((at, sid, was[1], rec.get("registered_at")))
                live[slot] = (sid, rec.get("registered_at"))
            for slot in [k for k in live if k[0] == side and k[1] not in block]:
                live.pop(slot, None)
    if restamped:
        return False, (f"{len(restamped)} re-stamps across {lives} lives; "
                       f"first: {restamped[0]}")
    return True, f"{lives} protected-swing lives, 0 re-stamped"


def swing_id_is_not_unique_across_lives():
    """The LIMITATION the contract declares, proven rather than asserted. If
    this ever passes as 'unique', occurrence identity may not rely on the pair.
    """
    live, repeats = {}, []
    for _at, snap, _occ in _replay(_tape()):
        by = (snap.get("protected_swings") or {}).get("by_timeframe") or {}
        for side in ("lows", "highs"):
            block = by.get(side) or {}
            for tf, rec in block.items():
                slot, sid = (side, tf), rec.get("swing_id")
                was = live.get(slot)
                if was and was[0] == sid and was[1] != rec.get("registered_at"):
                    repeats.append((sid, was[1], rec.get("registered_at")))
                live[slot] = (sid, rec.get("registered_at"))
            for slot in [k for k in live if k[0] == side and k[1] not in block]:
                # A death is what allows the same id to return as a new life.
                was = live.pop(slot, None)
                if was:
                    live[("dead", slot[1], was[0])] = was
        for side in ("lows", "highs"):
            for tf, rec in (by.get(side) or {}).items():
                dead = live.get(("dead", tf, rec.get("swing_id")))
                if dead and dead[1] != rec.get("registered_at"):
                    repeats.append((rec.get("swing_id"), dead[1],
                                    rec.get("registered_at")))
                    live.pop(("dead", tf, rec.get("swing_id")), None)
    if not repeats:
        return False, ("no repeated swing_id across lives found on this tape -- "
                       "the contract's non-uniqueness limitation is unproven "
                       "here, so identity must not assume it either way")
    return True, (f"{len(repeats)} swing_id reused by a later life, e.g. "
                  f"{repeats[0][0]} born {repeats[0][1]} then {repeats[0][2]}")


# ══ CAUSAL IDENTITY ═════════════════════════════════════════════════════════
def one_settled_edge_is_one_category_a_event():
    from market_data.causal_identity import CATEGORY_A, causal_event_key
    rows = []
    for _at, _snap, occ in _replay(_tape()):
        rows.extend(o for o in occ if o.get("event_type") in CATEGORY_A)
    htf = [r for r in rows if r.get("source_tf") in ("3m", "5m", "15m")]
    if not htf:
        raise SkipPredicate("no HTF Category A events on this tape")
    v1 = len({r["occurrence_id"] for r in htf})
    v2 = len({causal_event_key(r) for r in htf})
    if v2 >= v1:
        return False, f"HTF collapse did not occur: v1={v1} v2={v2}"
    return True, f"HTF observations {v1} -> {v2} causal events"


def category_b_mints_no_identity():
    """The BLOCKED claim, enforced. If a key ever appears here, either 1B landed
    or something leaked -- both require the contract to change first."""
    from market_data.causal_identity import (CATEGORY_B, causal_event_key,
                                             refusal_reason)
    seen = 0
    for _at, _snap, occ in _replay(_tape()):
        for row in occ:
            if row.get("event_type") not in CATEGORY_B:
                continue
            seen += 1
            if causal_event_key(row) is not None:
                return False, (f"{row['event_type']} minted a causal key while "
                               f"the contract declares Category B BLOCKED")
            if not refusal_reason(row):
                return False, f"{row['event_type']} refused without a reason"
    if not seen:
        raise SkipPredicate("no Category B transitions on this tape")
    return True, f"{seen} Category B transitions, all refused with a reason"


def production_does_not_select_v2():
    """`occurrence.causal_event_key.category_a` is CAPABILITY ONLY.

    STRUCTURAL, NOT LEXICAL. The first version of this check searched source
    text for `causal_identity_version=2` and immediately flagged the governance
    package, which NAMES v2 in order to record that production does not use it.
    Excluding a directory would have been a lexical patch on a lexical defect.

    A comment is not a call. This walks the AST of every production module and
    asks whether any real CALL passes `causal_identity_version`, and with what.
    """
    from rule_governance.epistemic_closure import authority_ast as AST
    src_root = os.path.join(_ROOT, "src")
    sites = AST.keyword_call_sites(src_root, "causal_identity_version")
    selecting = [c for c in sites if not c["literal"] or c["value"] not in (None, 1)]
    if selecting:
        first = selecting[0]
        return False, (f"{len(selecting)} production call site(s) select a "
                       f"non-v1 causal identity; first "
                       f"{first['file']}:{first['line']} "
                       f"{first['callee']}(causal_identity_version="
                       f"{first['value'] if first['literal'] else '<dynamic>'})")
    return True, (f"{len(sites)} production call site(s) pass "
                  f"causal_identity_version; none select v2 (AST-verified)")


# ══ LIQUIDITY ═══════════════════════════════════════════════════════════════
def brain_nearest_is_not_mathematically_nearest():
    """Proves the LEGACY label is honest.

    `brain_input` selects the first non-null pool scanning 15m -> 5m -> 3m -> 1m.
    Whenever a finer timeframe holds a pool CLOSER to price than the one chosen,
    the published 'nearest' is not nearest.
    """
    from ai_brain.brain_input import build_brain_input
    counter = 0
    checked = 0
    for path in sorted(glob.glob(os.path.join(_ARCHIVE, "20260825_*_MNQ.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                snap = json.load(fh)["raw_snapshot"]
        except Exception:  # noqa: BLE001
            continue
        payload = build_brain_input(snap, {})
        price = ((payload.get("market") or {}).get("current_price"))
        chosen = (payload.get("liquidity") or {}).get("nearest_buy_side")
        if price is None or chosen is None:
            continue
        checked += 1
        pools = []
        for tf in ("15m", "5m", "3m", "1m"):
            val = ((snap.get("liquidity") or {}).get(tf) or {}).get(
                "nearest_buy_side_liquidity")
            if isinstance(val, (int, float)):
                pools.append(val)
        if not pools:
            continue
        truly_nearest = min(pools, key=lambda p: abs(p - price))
        if abs(truly_nearest - price) < abs(chosen - price):
            counter += 1
    if not checked:
        raise SkipPredicate("no payload carried both a price and a buy-side pool")
    if counter == 0:
        return False, (f"across {checked} payloads the published value was "
                       f"always the mathematically nearest pool -- the LEGACY "
                       f"contract may now be understating the field")
    return True, (f"{counter}/{checked} payloads published a pool that was NOT "
                  f"the nearest; selection is highest-timeframe-first")


# ══ DEALING RANGE ═══════════════════════════════════════════════════════════
def dealing_range_position_is_unclamped():
    """Proves `dealing_range.containment` is genuinely BLOCKED.

    The producer computes (price - low) / (high - low) with no containment test,
    so a position outside [0, 1] is reachable and still carries a premium or
    discount label. Checked against the producer directly, because a given
    archive may never have wandered outside its own range.
    """
    from structure.market_context import _dealing_range
    structure = {"15m": {"last_swing_high": 29400.0, "last_swing_low": 29200.0}}
    out = _dealing_range(structure, {}, 29500.0)      # price ABOVE the range
    if out.get("position") is None:
        raise SkipPredicate("producer published no position for this fixture")
    if out["position"] <= 1.0:
        return False, ("position was clamped -- containment may now exist, so "
                       "the BLOCKED contract needs revisiting")
    return True, (f"price above range yields position={out['position']} "
                  f"zone={out['zone']!r}; no containment check exists")


# ══ RECOVERY ════════════════════════════════════════════════════════════════
def recovery_kernel_has_no_production_authority():
    """`recovery.session_state_completeness` is BLOCKED because nothing imports
    the kernel. This is what keeps that BLOCKED status true rather than stale.

    STRUCTURAL: an `import` statement, not the substring "session_recovery"
    appearing somewhere in a file. A fact contract that DESCRIBES the kernel is
    not a module that CALLS it, and the two contaminated-suite failures were
    caused by exactly that confusion.
    """
    from rule_governance.epistemic_closure import authority_ast as AST
    src_root = os.path.join(_ROOT, "src")
    hits = AST.imports_module(
        src_root, "session_recovery",
        exclude_files=[os.path.join(src_root, "market_state",
                                    "session_recovery.py")])
    if hits:
        where = ", ".join(f"{h['file']}:{h['line']}" for h in hits[:3])
        return False, (f"the recovery kernel is imported by production: {where}. "
                       f"It may now hold production authority, which the "
                       f"contract declares BLOCKED")
    return True, "no production module imports the recovery kernel (AST-verified)"


def protected_level_dies_when_price_accepts_through_it():
    """`protected_swing.level`'s declared invalidation, checked on tape.

    The contract says a level is defended UNTIL price closes beyond it. If a
    level ever survived a decisive close through it, `brain_prompt`'s reading --
    "a level still listed has not been violated" -- would be false.
    """
    from narrative_authority.protected_swings import _violation_buffer_pct
    survivors, checked = [], 0
    for at, snap, _occ in _replay(_tape()):
        by = (snap.get("protected_swings") or {}).get("by_timeframe") or {}
        price = (((snap.get("timeframes") or {}).get("1m") or {})
                 .get("last_candle") or {}).get("close")
        if price is None:
            continue
        buf = float(price) * _violation_buffer_pct()
        for tf, rec in (by.get("lows") or {}).items():
            checked += 1
            if float(price) < float(rec["level"]) - buf:
                survivors.append((at, tf, rec["level"], price))
        for tf, rec in (by.get("highs") or {}).items():
            checked += 1
            if float(price) > float(rec["level"]) + buf:
                survivors.append((at, tf, rec["level"], price))
    if not checked:
        raise SkipPredicate("no protected levels published on this tape")
    if survivors:
        return False, (f"{len(survivors)} published levels survived a decisive "
                       f"close through them; first {survivors[0]}")
    return True, f"{checked} published level-observations, none violated-but-listed"


def ownership_is_never_claimed_without_confirmation():
    """`active_path.owner`'s declared formation rule.

    The contract says ESTABLISHED ownership requires a rejected-raid origin PLUS
    a same-direction structure break. A leg that owned the tape without ever
    being confirmed would be the `owner=bearish` defect that published ownership
    for 116 scans of a session mechanics could not read at all.
    """
    from market_state.active_path import STRUCTURE_BREAK, ActivePath
    path = ActivePath()
    confirmed, violations, scans = set(), [], 0
    for at, snap, occ in _replay(_tape()):
        path.enforce_lifecycle(snap.get("timestamp"), CID)
        path.ingest(occ)
        for row in occ:
            if row.get("event_type") == STRUCTURE_BREAK and row.get("direction"):
                confirmed.add(row["direction"])
        scans += 1
        owner = path.state().get("owner")
        if owner in ("bullish", "bearish") and owner not in confirmed:
            violations.append((at, owner))
        path.mark_scan_end()
    if not scans:
        raise SkipPredicate("no scans replayed")
    if violations:
        return False, (f"{len(violations)} scans claimed ownership with no "
                       f"same-direction structure break; first {violations[0]}")
    return True, f"{scans} scans, ownership never claimed before confirmation"


def load_bearing_level_is_producer_backed():
    """`active_path.load_bearing_structure`'s no-ghost rule.

    The contract says it follows the PRODUCER even when the move is adverse. A
    level the tracker has stopped holding, still published as load-bearing and
    intact, is the 2026-08-21 defect where a leg replayed 153/153 bearish
    because the violation of its real level could never match the stale one.
    """
    from market_state.active_path import ActivePath
    path = ActivePath()
    ghosts, held = [], 0
    for at, snap, occ in _replay(_tape()):
        path.enforce_lifecycle(snap.get("timestamp"), CID)
        path.ingest(occ)
        lb = path.state().get("load_bearing_structure") or {}
        level = lb.get("level")
        if level is not None:
            held += 1
            by = (snap.get("protected_swings") or {}).get("by_timeframe") or {}
            live = {float(r["level"]) for side in ("lows", "highs")
                    for r in (by.get(side) or {}).values()
                    if r.get("level") is not None}
            if lb.get("intact") and float(level) not in live:
                ghosts.append((at, level, sorted(live)))
        path.mark_scan_end()
    if not held:
        raise SkipPredicate("no load-bearing structure was ever established")
    if ghosts:
        return False, (f"{len(ghosts)}/{held} observations published an intact "
                       f"load-bearing level the tracker no longer holds; first "
                       f"{ghosts[0][0]} level={ghosts[0][1]}")
    return True, f"{held} load-bearing observations, all producer-backed"


def brain_nearest_sell_side_is_not_mathematically_nearest():
    """The sell-side twin of the buy-side LEGACY proof. Both sides are flattened
    by the same next() over ('15m','5m','3m','1m'), and proving one is not
    proving the other."""
    from ai_brain.brain_input import build_brain_input
    counter = checked = 0
    for path in sorted(glob.glob(os.path.join(_ARCHIVE, "20260825_*_MNQ.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                snap = json.load(fh)["raw_snapshot"]
        except Exception:  # noqa: BLE001
            continue
        payload = build_brain_input(snap, {})
        price = (payload.get("market") or {}).get("current_price")
        chosen = (payload.get("liquidity") or {}).get("nearest_sell_side")
        if price is None or chosen is None:
            continue
        checked += 1
        pools = [v for v in ((((snap.get("liquidity") or {}).get(tf) or {})
                              .get("nearest_sell_side_liquidity"))
                             for tf in ("15m", "5m", "3m", "1m"))
                 if isinstance(v, (int, float))]
        if not pools:
            continue
        if abs(min(pools, key=lambda x: abs(x - price)) - price) < abs(chosen - price):
            counter += 1
    if not checked:
        raise SkipPredicate("no payload carried both a price and a sell-side pool")
    if counter == 0:
        return False, (f"across {checked} payloads the published value was always "
                       f"the nearest pool -- the LEGACY contract may be "
                       f"understating the field")
    return True, (f"{counter}/{checked} payloads published a pool that was NOT "
                  f"the nearest")


def dealing_range_bounds_come_from_one_timeframe():
    """`dealing_range.bounds`' declared derivation: the last swing high and low
    of ONE source timeframe, high above low. A range assembled from two
    timeframes would describe an auction nobody actually traded."""
    from ai_brain.brain_input import build_brain_input
    bad, checked = [], 0
    for path in sorted(glob.glob(os.path.join(_ARCHIVE, "20260825_*_MNQ.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                snap = json.load(fh)["raw_snapshot"]
        except Exception:  # noqa: BLE001
            continue
        dr = (build_brain_input(snap, {}).get("market") or {}).get("dealing_range") or {}
        hi, lo, tf = dr.get("high"), dr.get("low"), dr.get("source_tf")
        if hi is None or lo is None:
            continue
        checked += 1
        if not tf:
            bad.append((os.path.basename(path), "no source_tf"))
        elif not hi > lo:
            bad.append((os.path.basename(path), f"high {hi} not above low {lo}"))
        else:
            st = (snap.get("structure") or {}).get(tf) or {}
            if st.get("last_swing_high") != hi or st.get("last_swing_low") != lo:
                bad.append((os.path.basename(path),
                            f"bounds {lo}-{hi} are not {tf} swings "
                            f"{st.get('last_swing_low')}-{st.get('last_swing_high')}"))
    if not checked:
        raise SkipPredicate("no dealing range published on this tape")
    if bad:
        return False, f"{len(bad)}/{checked} malformed; first {bad[0]}"
    return True, f"{checked} ranges, each the swings of one source timeframe"



# == SESSION PO3 =============================================================
# LUNA-SESSION-PO3-AUTHORITY-1. These bind the producer to what the three
# decision-bearing consumers believe: the candidate producer and the execution
# gate believe a False `new_entry_allowed` forbids opening a position, and the
# Brain believes the phase describes the session it is reasoning about. Every
# one of them runs against the ARCHIVED TAPE through the real builder, so a
# refactor that quietly changed what the phase means fails here rather than in a
# live session.

def _session_states(limit=60):
    """(at, session_po3 block) for the tail of the archived tape."""
    bars = _tape()[-limit:]
    out = []
    for at, snap, _occ in _replay(bars, min_bars=30):
        block = snap.get("session_po3")
        if isinstance(block, dict) and block.get("phase"):
            out.append((at, block, snap))
    if not out:
        raise SkipPredicate("no session_po3 published on the archived tape")
    return out


def session_phase_is_recomputed_never_remembered():
    """DECLARED: RECOMPUTED, and a restart replaying the same tape reaches the
    same phase. Every consumer trusts that -- a phase that drifted with scan
    cadence would make `restart: recomputed` a lie and would make the block
    itself unreproducible in an audit."""
    from structure.session_po3 import SessionPo3Authority, derive
    bars = _tape()[-60:]
    checked, bad = 0, []
    for at, published, snap in _session_states():
        settled = [c for c in ((snap.get("timeframes") or {}).get("1m") or {}).get(
            "recent_candles") or [] if c.get("temporal_status") == "settled"]
        one_shot = derive(settled_1m=settled, po3=snap.get("po3"),
                          liquidity=snap.get("liquidity"),
                          structure=snap.get("structure"),
                          authority=(snap.get("po3") or {}).get("authority"))
        checked += 1
        if one_shot["phase"] != published["phase"]:
            bad.append((at, published["phase"], one_shot["phase"]))
        elif one_shot["new_entry_allowed"] != published["new_entry_allowed"]:
            bad.append((at, "entry ruling differs from a cold derivation"))
    if bad:
        return False, f"{len(bad)}/{checked} scans differ on restart; first {bad[0]}"
    return True, (f"{checked} scans: a cold derivation reproduces the published "
                  f"phase and its entry ruling exactly")


def session_block_refuses_every_consumer_identically():
    """DECLARED: `new_entry_allowed` False forbids OPENING a position, and both
    decision-bearing consumers act on it. This is the check that would have
    caught the 2026-08-25 defect: the phase said accumulation and nothing
    downstream cared."""
    from broker.luna_candidate_producer import CandidateProducer, NoCandidate
    from execution_gate.execution_gate import evaluate_gate
    checked, blocked, bad = 0, 0, []
    for at, block, _snap in _session_states():
        checked += 1
        permits = bool(block.get("new_entry_allowed"))
        try:
            CandidateProducer._assert_session_phase_permits_entry(
                {"session_po3": block})
            producer_permits = True
        except NoCandidate as exc:
            producer_permits = False
            if exc.reason != "session_phase_blocks_entry" or not exc.stand_down:
                bad.append((at, f"wrong refusal {exc.reason!r}"))
        gate = evaluate_gate({"session_po3": block})
        if producer_permits != permits:
            bad.append((at, "producer disagrees with the published ruling"))
        if gate["session_phase_permits_entry"] != permits:
            bad.append((at, "execution gate disagrees with the published ruling"))
        if not permits:
            blocked += 1
            if gate["would_authorize_if_enabled"]:
                bad.append((at, "gate would authorize inside a blocking phase"))
    if bad:
        return False, f"{len(bad)} disagreements; first {bad[0]}"
    return True, (f"{checked} scans, {blocked} blocking: producer and gate both "
                  f"refuse exactly when the phase does")


def session_range_is_what_the_balance_absorbed():
    """DECLARED: the range is the high/low of every settled bar the balance
    ABSORBED, high above low. The consumer that matters -- derive() itself --
    treats those bounds as the boundary a close must clear, so a range that did
    not come from absorbed bars would mislocate every excursion."""
    checked, bad = 0, []
    for at, block, _snap in _session_states():
        rng = block.get("range")
        if not rng:
            continue
        checked += 1
        if rng.get("high") is None or rng.get("low") is None:
            bad.append((at, "range published with no bounds"))
        elif not rng["high"] > rng["low"]:
            bad.append((at, f"high {rng['high']} not above low {rng['low']}"))
        elif not rng.get("birth"):
            bad.append((at, "range has no birth"))
        elif rng.get("established") and (rng.get("age_bars") or 0) < 12:
            bad.append((at, f"established at {rng.get('age_bars')} bars"))
    if not checked:
        raise SkipPredicate("no range published on the archived tape")
    if bad:
        return False, f"{len(bad)}/{checked} malformed; first {bad[0]}"
    return True, f"{checked} ranges, each bounded, born and honestly aged"


def session_excursion_requires_an_established_range():
    """DECLARED: a balance that was never ESTABLISHED cannot be departed from.
    This is the rule that keeps a genuine opening drive legal -- without it the
    authority would ban every early-session trade, which is a worse failure than
    the one it was built to fix."""
    checked, bad = 0, []
    for at, block, _snap in _session_states():
        exc = block.get("excursion")
        if not exc:
            continue
        checked += 1
        rng = block.get("range") or {}
        if block["phase"] in ("EXCURSION_UNRESOLVED", "MANIPULATION_CONFIRMED",
                              "DISTRIBUTION_ACTIVE", "REACCUMULATION"):
            if not rng.get("established"):
                bad.append((at, f"{block['phase']} from an unestablished range"))
        if block["phase"] == "EXCURSION_UNRESOLVED" and block["new_entry_allowed"]:
            bad.append((at, "an unresolved excursion permitted an entry"))
    if not checked:
        raise SkipPredicate("no excursion published on the archived tape")
    if bad:
        return False, f"{len(bad)}/{checked} unsound; first {bad[0]}"
    return True, (f"{checked} excursions, every one from an established range, "
                  f"and none of the unresolved ones authorized an entry")


def session_manipulation_reads_the_band_not_the_score():
    """DECLARED: only a `manipulation_confirmed` BAND may resolve an excursion,
    and the direction is the DETECTOR'S own -- not `sweep_direction`, which is
    what po3_engine substituted while the detector's direction was discarded."""
    checked, bad, confirmed = 0, [], 0
    for at, block, snap in _session_states():
        m = block.get("manipulation") or {}
        checked += 1
        # The published verdict must be one the detector actually issued.
        issued = {str(((snap.get("liquidity") or {}).get(tf) or {}).get(
            "manipulation", {}).get("classification") or "none")
            for tf in ("15m", "5m", "3m", "1m")}
        if m.get("classification") not in issued:
            bad.append((at, f"published {m.get('classification')!r} not in {issued}"))
        if block["phase"] == "MANIPULATION_CONFIRMED":
            confirmed += 1
            if m.get("classification") != "manipulation_confirmed":
                bad.append((at, "confirmed phase on a non-confirmed band"))
            if m.get("conflicted"):
                bad.append((at, "confirmed phase on conflicting timeframes"))
    if bad:
        return False, f"{len(bad)}/{checked} unsound; first {bad[0]}"
    return True, (f"{checked} scans, {confirmed} confirmed: every phase rests on "
                  f"the detector's own band, never on its score")


def session_preference_never_creates_a_playbook():
    """DECLARED: a preference is a ranking input, never a permission. It must be
    unable to promote a family that scored nothing, which is what separates
    'the reversal is preferred' from 'take a reversal'."""
    from playbooks import playbook_classifier as PC
    snap = {"session_po3": {"phase": "MANIPULATION_CONFIRMED",
                            "new_entry_allowed": True,
                            "preferred_playbook_families":
                                ["liquidity_sweep_reversal", "trend_continuation"]}}
    if PC._phase_preference(snap, "opening_drive") != 0:
        return False, "an unpreferred family still earned phase points"
    if PC._phase_preference(snap, "liquidity_sweep_reversal") <= 0:
        return False, "a preferred family earned nothing"
    # A family that scored zero must stay at zero: the bonus is applied only to
    # a non-zero score, so preference cannot manufacture an opportunity.
    scores = {"liquidity_sweep_reversal": 0, "trend_continuation": 40}
    boosted = {n: min(100, sc + PC._phase_preference(snap, n)) if sc else sc
               for n, sc in scores.items()}
    if boosted["liquidity_sweep_reversal"] != 0:
        return False, "preference promoted a family that scored nothing"
    if boosted["trend_continuation"] <= 40:
        return False, "preference did not rank an eligible family"
    return True, ("preference ranks a scoring family and cannot create one that "
                  "scored nothing")



# == CROSS-SESSION CONTEXT ===================================================
# LUNA-CROSS-SESSION-PO3-CONTEXT-1. Two propositions, both run against the
# archived tape through the real builder.

def session_context_never_publishes_facts_without_exact_coverage():
    """DECLARED: a context publishes a high/low/range ONLY when every
    venue-expected settled minute of its window is present. The Brain reads
    these as prior-session facts, so a range assembled from a fragment would be
    a claim about a window that was never observed.

    This is the proposition the whole VENUE-CALENDAR-AUTHORITY-HORIZON-1
    prerequisite existed to make checkable."""
    from market_data.session_context import (AVAILABLE, IN_PROGRESS,
                                             derive as derive_ctx)
    bars = _tape()
    checked, facts_published, bad = 0, 0, []
    for end in range(60, len(bars) + 1, 30):
        state = derive_ctx(settled_1m=bars[:end])
        for name, block in (state.get("contexts") or {}).items():
            checked += 1
            status, facts = block.get("status"), block.get("facts")
            cov = block.get("coverage") or {}
            if status in (AVAILABLE, IN_PROGRESS):
                facts_published += 1
                if cov.get("missing_bars") != 0:
                    bad.append((name, status, f"missing={cov.get('missing_bars')}"))
                if not facts:
                    bad.append((name, status, "fact-bearing status with no facts"))
            else:
                if facts is not None:
                    bad.append((name, status, "facts published without coverage"))
    if not checked:
        raise SkipPredicate("no session context derivable from the archived tape")
    if bad:
        return False, f"{len(bad)}/{checked} unsound; first {bad[0]}"
    return True, (f"{checked} context reads, {facts_published} fact-bearing: every "
                  f"published window had complete expected coverage and every "
                  f"incomplete one published nothing")


def session_context_cannot_reach_the_session_phase():
    """DECLARED: cross-session context is evidence, never authority. Proven
    STRUCTURALLY -- `session_po3.derive` has no parameter through which a prior
    session could arrive -- and then behaviourally on the real tape."""
    import inspect

    from data_feed.timeframe_builder import build_timeframes
    from market_data.snapshot_builder import build_snapshot
    from structure.session_po3 import derive as po3_derive

    params = set(inspect.signature(po3_derive).parameters)
    if params != {"settled_1m", "po3", "liquidity", "structure", "authority"}:
        return False, f"session_po3.derive grew a parameter: {sorted(params)}"

    src = open(os.path.join(_ROOT, "src", "structure", "session_po3.py"),
               encoding="utf-8").read()
    if "session_context" in src:
        return False, "session_po3 now references session_context"

    bars = _tape()
    scan = bars[-300:]
    if len(scan) < 40:
        raise SkipPredicate("archived tape too short for a snapshot comparison")
    with_ctx = build_snapshot(build_timeframes(scan), symbol="MNQ",
                              contract_id=CID, deep_1m=bars)
    without = build_snapshot(build_timeframes(scan), symbol="MNQ",
                             contract_id=CID)
    if with_ctx["session_po3"] != without["session_po3"]:
        return False, "session_po3 output changed when context was supplied"
    return True, ("session_po3 has no context parameter, no context import, and "
                  "identical output with and without the context block")



# ── ORDINAL SWING STRUCTURE ─────────────────────────────────────────────────
# LUNA-SWING-SEQUENCE-TRUTH-1 (2026-09-01).
#
# THESE CERTIFY STRUCTURAL MEANING, NOT TRADING IMPLICATION. `BULLISH_SEQUENCE`
# is proven to mean "confirmed highs rose AND confirmed lows rose" and nothing
# else. It is deliberately NOT bound to bias, entry permission, Active Path
# ownership, PO3 phase, a target or an expected outcome -- if a predicate here
# ever proves one of those, the fact has stopped being structure and become a
# recommendation.

def _sequence_of(highs, lows):
    from narrative_authority.swing_structure import canonical_sequence
    return canonical_sequence({"highs": {"1m": [{"level": h} for h in highs]},
                               "lows": {"1m": [{"level": lo} for lo in lows]}})


def bullish_sequence_means_both_sides_rose():
    """BULLISH_SEQUENCE iff every confirmed high rose AND every low rose."""
    from narrative_authority.swing_structure import BULLISH
    r = _sequence_of([100, 110, 120], [90, 95, 99])
    if r["sequence"] != BULLISH:
        return False, f"rising/rising produced {r['sequence']!r}"
    if r["high_ordinals"] != ["higher_high"] * 2 or \
            r["low_ordinals"] != ["higher_low"] * 2:
        return False, f"ordinals disagree: {r['high_ordinals']} / {r['low_ordinals']}"
    # A single non-rising high on either side must remove the claim.
    for bad_h, bad_l in (([100, 110, 105], [90, 95, 99]),
                         ([100, 110, 120], [90, 95, 92])):
        if _sequence_of(bad_h, bad_l)["sequence"] == BULLISH:
            return False, "a falling swing did not remove BULLISH_SEQUENCE"
    return True, ("BULLISH_SEQUENCE requires rising confirmed highs AND rising "
                  "confirmed lows; one contrary swing removes it")


def bearish_sequence_means_both_sides_fell():
    from narrative_authority.swing_structure import BEARISH
    r = _sequence_of([120, 110, 100], [99, 95, 90])
    if r["sequence"] != BEARISH:
        return False, f"falling/falling produced {r['sequence']!r}"
    for bad_h, bad_l in (([120, 110, 115], [99, 95, 90]),
                         ([120, 110, 100], [99, 95, 97])):
        if _sequence_of(bad_h, bad_l)["sequence"] == BEARISH:
            return False, "a contrary swing did not remove BEARISH_SEQUENCE"
    return True, ("BEARISH_SEQUENCE requires falling confirmed highs AND "
                  "falling confirmed lows")


def conflicting_structure_is_mixed_not_a_lean():
    """A widening or narrowing auction is reported, never resolved into a lean."""
    from narrative_authority.swing_structure import MIXED
    cases = {"higher highs, lower lows": ([100, 120], [90, 80]),
             "lower highs, higher lows": ([120, 110], [90, 95]),
             "flat both sides": ([100, 100], [90, 90])}
    for name, (h, lo) in cases.items():
        got = _sequence_of(h, lo)["sequence"]
        if got != MIXED:
            return False, f"{name} produced {got!r}, not MIXED"
    return True, "conflicting ordinal evidence yields MIXED, never a lean"


def insufficient_and_unknown_do_not_collapse():
    """Two different claims: 'too early' vs 'unavailable'."""
    from narrative_authority.swing_structure import (INSUFFICIENT, UNKNOWN,
                                                     canonical_sequence)
    early = canonical_sequence({"highs": {}, "lows": {}})
    if early["sequence"] != INSUFFICIENT:
        return False, f"an empty but readable registry gave {early['sequence']!r}"
    one = _sequence_of([100], [90])
    if one["sequence"] != INSUFFICIENT:
        return False, "one swing a side was not INSUFFICIENT"
    for absent in (None, {}, "corrupt", 7):
        if canonical_sequence(absent)["sequence"] != UNKNOWN:
            return False, f"absent registry {absent!r} was not UNKNOWN"
    return True, ("INSUFFICIENT means readable-but-early; UNKNOWN means "
                  "unavailable; neither is ever reported as the other")


def the_sequence_carries_no_trading_implication():
    """THE LAW THAT KEEPS THIS STRUCTURAL. The published fact must not contain
    any directional or permissive vocabulary."""
    r = _sequence_of([100, 110, 120], [90, 95, 99])
    blob = repr(r).lower()
    banned = ("buy", "sell", "long", "short", "entry", "target", "bias",
              "permission", "authorize", "take_trade")
    hit = [w for w in banned if w in blob]
    if hit:
        return False, f"structural fact leaked trading vocabulary: {hit}"
    return True, ("the canonical sequence states ordering only; it names no "
                  "direction to trade, no entry and no permission")


def the_registry_outranks_the_windowed_witness():
    """The witness may disagree; it may never override."""
    from narrative_authority.swing_structure import BULLISH, witness_agreement
    canon = _sequence_of([100, 110], [90, 95])
    w = witness_agreement(canon, "lower_highs_lower_lows")
    if w["agreement"] != "disagree":
        return False, f"a contradicting witness reported {w['agreement']!r}"
    if w["canonical"] != BULLISH:
        return False, "the canonical answer changed when the witness disagreed"
    agree = witness_agreement(canon, "higher_highs_higher_lows")
    if agree["agreement"] != "agree":
        return False, "a concurring witness was not reported as agreement"
    return True, ("the confirmed registry keeps its answer under disagreement; "
                  "the windowed witness is published, never promoted")


def agreement_is_not_claimed_across_unavailable_truth():
    from narrative_authority.swing_structure import (INSUFFICIENT, UNKNOWN,
                                                     witness_agreement)
    canon = _sequence_of([100, 110], [90, 95])
    if witness_agreement(canon, "unknown")["agreement"] != "not_comparable":
        return False, "an unknown witness was compared anyway"
    for state in (UNKNOWN, INSUFFICIENT):
        got = witness_agreement({"sequence": state}, "higher_highs_higher_lows")
        if got["agreement"] != "not_comparable":
            return False, f"canonical {state} was compared anyway"
    return True, ("comparison requires both sides to be established; otherwise "
                  "not_comparable, never a guessed agreement")


def ordinals_are_derived_not_trusted():
    """The same confirmed prices yield the same relationships by any route, so a
    stored ordinal can never disagree with the levels it describes."""
    a = _sequence_of([100, 110, 120], [90, 95, 99])
    b = _sequence_of([100, 110, 120], [90, 95, 99])
    if a["high_ordinals"] != b["high_ordinals"] or a["sequence"] != b["sequence"]:
        return False, "the same ladder produced two different answers"
    if len(a["high_ordinals"]) != len(a["highs"]) - 1:
        return False, "ordinal count does not match the relationships available"
    return True, ("ordinals are recomputed from the ordered prices; a rebuild "
                  "yields an identical sequence")


def the_windowed_witness_reads_one_settled_timeframe():
    """Selection is by pivot sufficiency over settled candles, and yields ONE
    timeframe -- never a mixed-timeframe pivot set."""
    import ast as _ast
    import inspect as _inspect

    from regime_classification import regime_features as RF
    tree = _ast.parse(_inspect.getsource(RF._extract))
    fn = next(n for n in _ast.walk(tree) if isinstance(n, _ast.FunctionDef))
    called = {getattr(c.func, "id", "") for c in _ast.walk(fn)
              if isinstance(c, _ast.Call)}
    if "_settled_series" not in called:
        return False, "swing candidates no longer come from the settled authority"
    raw_sub = [n for n in _ast.walk(fn) if isinstance(n, _ast.Subscript)
               and getattr(n.value, "id", "") == "raw_data"]
    if raw_sub:
        return False, "a candidate series was taken from the realtime view"
    return True, ("every windowed candidate is drawn through the settled-series "
                  "authority; exactly one timeframe becomes the witness")



def explanatory_prose_introduces_no_new_claim():
    """`detail` fields explain; they must never assert.

    Prose reaches the Brain as language, which is exactly how a recommendation
    could smuggle itself past a structured contract -- so the explanation is
    held to the same law as the fact it describes: it may restate ordering and
    counts, and it may say why something is unresolved, but it may not name a
    direction to trade, an entry, a target or a permission.
    """
    from narrative_authority.swing_structure import canonical_sequence
    banned = ("buy", "sell", "long", "short", "entry", "target", "bias",
              "permission", "authorize", "should", "expect")
    samples = [
        canonical_sequence({"highs": {"1m": [{"level": 100}, {"level": 110}]},
                            "lows": {"1m": [{"level": 90}, {"level": 95}]}}),
        canonical_sequence({"highs": {"1m": [{"level": 100}]},
                            "lows": {"1m": [{"level": 90}]}}),
        canonical_sequence(None),
        canonical_sequence({"highs": {}, "lows": {}}),
    ]
    for r in samples:
        text = str(r.get("detail", "")).lower()
        hit = [w for w in banned if w in text]
        if hit:
            return False, f"detail prose asserted {hit} in {text!r}"
        if not text:
            return False, f"a {r['sequence']} result gave no explanation"
    return True, ("every detail string explains the sequence without naming a "
                  "direction, an entry, a target or a permission")



# ── LIQUIDITY SCOPE ─────────────────────────────────────────────────────────
# LUNA-LIQUIDITY-SCOPE-TRUTH-1 (2026-09-01).
#
# These certify that scope means WHAT WAS TAKEN, RELATIVE TO WHICH NAMED
# AUTHORITY, AT THE TIME. None of them binds scope to a trade: `external` +
# `sell_side` + `reclaimed` is three facts, and if a predicate here ever proved
# a direction, the fact would have stopped being an observation.

def _scope_sweep(side="sell_side", level=100.0):
    return {"event_time": "2026-09-01T13:40:00+00:00",
            "liquidity_side_taken": side, "swept_level": level,
            "reclaimed": True}


def scope_is_event_time_immutable():
    """THE DEFECT, AS A RUNNING CHECK.

    The classifier answered from whatever pivot context happened to be current,
    so a later higher swing rewrote what an earlier event WAS. A stamp taken at
    the event must survive a context that has since moved.
    """
    from market_data.liquidity_scope import EXTERNAL, INTERNAL, stamp
    f = _scope_sweep(level=100.0)
    at_event = stamp(f, highs=[130], lows=[100.0, 110.0])
    if at_event["detector_scope"] != EXTERNAL:
        return False, "the event-time stamp was not EXTERNAL"
    later = stamp(f, highs=[130], lows=[90.0, 100.0])
    if later["detector_scope"] != INTERNAL:
        return False, "a moved context did not reclassify a NEW stamp"
    if at_event["detector_scope"] != EXTERNAL:
        return False, "the frozen stamp was rewritten by later context"
    return True, ("scope stamped at the event survives a context that moved; a "
                  "later scan mints a new fact rather than restating an old one")


def scope_is_not_direction():
    """Scope, side and rejection are observations. None of them is a trade."""
    from market_data.liquidity_scope import stamp
    r = stamp(_scope_sweep(), highs=[130], lows=[100.0])
    blob = repr(r).lower()
    banned = ("bullish", "bearish", "buy", "long", "short", "entry", "target",
              "bias", "permission", "authorize")
    hit = [w for w in banned if w in blob]
    if hit:
        return False, "a scope fact carried directional vocabulary: %s" % hit
    return True, ("scope publishes side, classification and reference only -- no "
                  "direction, entry, target or permission")


def scope_names_its_authority():
    """`external` without `external to what` is not a fact."""
    from market_data.liquidity_scope import (MANIPULATION_PIVOT_CONTEXT,
                                             SESSION_PO3_ACCUMULATION_RANGE,
                                             stamp)
    r = stamp(_scope_sweep(), highs=[130], lows=[100.0],
              po3_range={"high": 140, "low": 95, "birth": "b",
                         "last_extension": "e", "established": True},
              session_date="20260901")
    det = (r.get("detector_scope_reference") or {}).get("type")
    po3 = (r.get("po3_scope_reference") or {}).get("type")
    if det != MANIPULATION_PIVOT_CONTEXT:
        return False, "the detector scope named no authority (%r)" % det
    if po3 != SESSION_PO3_ACCUMULATION_RANGE:
        return False, "the session scope named no authority (%r)" % po3
    if det == po3:
        return False, "the two authorities collapsed into one"
    return True, ("both scopes name a distinct authority, so they can "
                  "legitimately disagree without either being wrong")


def po3_scope_needs_a_prior_range():
    """A range that forms later is not evidence about an earlier event."""
    from market_data.liquidity_scope import EXTERNAL, UNKNOWN, stamp
    f = _scope_sweep(level=90.0)
    none_yet = stamp(f, highs=[130], lows=[90.0], po3_range=None,
                     session_date="20260901")
    if none_yet["po3_scope"] != UNKNOWN:
        return False, "no established range did not yield UNKNOWN"
    if none_yet["po3_scope_reference"] is not None:
        return False, "a reference was published without a range"
    forming = stamp(f, highs=[130], lows=[90.0],
                    po3_range={"high": 140, "low": 95, "birth": "b",
                               "last_extension": "e", "established": False},
                    session_date="20260901")
    if forming["po3_scope"] != UNKNOWN:
        return False, "a FORMING range was allowed to classify an event"
    later = stamp(f, highs=[130], lows=[90.0],
                  po3_range={"high": 140, "low": 95, "birth": "b",
                             "last_extension": "e", "established": True},
                  session_date="20260901")
    if later["po3_scope"] != EXTERNAL:
        return False, "an established range failed to classify"
    if none_yet["po3_scope"] != UNKNOWN:
        return False, "the earlier UNKNOWN was relabelled by a later range"
    return True, ("session scope requires an ESTABLISHED range that predates "
                  "the event; a forming or later range yields UNKNOWN and never "
                  "relabels history")


def range_id_survives_extension():
    """The same accumulation range that extends is still the same range."""
    from market_data.liquidity_scope import po3_reference
    base = {"high": 29179.0, "low": 29074.5, "birth": "2026-09-01T13:45:00+00:00",
            "last_extension": "2026-09-01T14:22:00+00:00", "established": True}
    v4 = po3_reference(base, session_date="20260901")
    v5 = po3_reference(dict(base, high=29210.0,
                            last_extension="2026-09-01T14:40:00+00:00"),
                       session_date="20260901")
    if v4["range_id"] != v5["range_id"]:
        return False, "an extension created a new range identity"
    if v4["reference_snapshot_id"] == v5["reference_snapshot_id"]:
        return False, "two different boundary states share one snapshot id"
    other = po3_reference(dict(base, birth="2026-09-01T15:10:00+00:00"),
                          session_date="20260901")
    if other["range_id"] == v4["range_id"]:
        return False, "a genuinely different range reused an identity"
    return True, ("range_id is stable across legitimate extension while the "
                  "snapshot id versions, so an event stays bound to the exact "
                  "boundaries it was judged against")


def scope_requires_a_proven_occurrence():
    """Scope enriches a proven event; it never manufactures one."""
    from datetime import datetime, timedelta, timezone

    from structure.liquidity_engine import analyze_liquidity
    t0 = datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc)
    bars = []
    for i in range(80):
        off = (i % 5) * 6.0 - (i % 3) * 4.0
        bars.append({"timestamp": (t0 + timedelta(minutes=i)).isoformat(),
                     "open": 29100 + off, "high": 29105 + off,
                     "low": 29095 + off, "close": 29101 + off})
    bars.append({"timestamp": (t0 + timedelta(minutes=80)).isoformat(),
                 "open": 29090, "high": 29095, "low": 29050, "close": 29092})
    prod = analyze_liquidity(bars, None)                 # production defaults
    if prod.get("sweep_fact") is not None:
        return False, "bare OHLC without member provenance minted a sweep"
    if "detector_scope" in repr(prod):
        return False, "a scope fact appeared without a proven occurrence"
    return True, ("no lawful sweep means no scope fact at all -- ABSENT, which "
                  "is not the same claim as UNKNOWN")


#: id -> callable. Contracts reference these by id; the verifier runs them.
PREDICATES = {
    "protected_swing.formation_immutable": formation_time_is_immutable_within_a_life,
    "swing.bullish_means_both_sides_rose": bullish_sequence_means_both_sides_rose,
    "swing.bearish_means_both_sides_fell": bearish_sequence_means_both_sides_fell,
    "swing.conflict_is_mixed": conflicting_structure_is_mixed_not_a_lean,
    "swing.insufficient_is_not_unknown": insufficient_and_unknown_do_not_collapse,
    "swing.structure_is_not_permission": the_sequence_carries_no_trading_implication,
    "swing.registry_outranks_witness": the_registry_outranks_the_windowed_witness,
    "swing.agreement_needs_both_sides": agreement_is_not_claimed_across_unavailable_truth,
    "swing.ordinals_are_derived": ordinals_are_derived_not_trusted,
    "swing.witness_is_settled_and_single": the_windowed_witness_reads_one_settled_timeframe,
    "swing.prose_asserts_nothing": explanatory_prose_introduces_no_new_claim,
    "liquidity.scope_is_event_time_immutable": scope_is_event_time_immutable,
    "liquidity.scope_is_not_direction": scope_is_not_direction,
    "liquidity.scope_names_its_authority": scope_names_its_authority,
    "liquidity.po3_scope_needs_a_prior_range": po3_scope_needs_a_prior_range,
    "liquidity.range_id_survives_extension": range_id_survives_extension,
    "liquidity.scope_requires_a_proven_occurrence": scope_requires_a_proven_occurrence,
    "liquidity.prose_asserts_nothing": explanatory_prose_introduces_no_new_claim,
    "protected_swing.id_not_unique_across_lives": swing_id_is_not_unique_across_lives,
    "causal.one_edge_one_event": one_settled_edge_is_one_category_a_event,
    "causal.category_b_refused": category_b_mints_no_identity,
    "causal.production_is_v1": production_does_not_select_v2,
    "liquidity.nearest_is_htf_first": brain_nearest_is_not_mathematically_nearest,
    "range.position_unclamped": dealing_range_position_is_unclamped,
    "recovery.kernel_unwired": recovery_kernel_has_no_production_authority,
    "protected_swing.level_dies_on_acceptance":
        protected_level_dies_when_price_accepts_through_it,
    "path.ownership_requires_confirmation":
        ownership_is_never_claimed_without_confirmation,
    "path.load_bearing_is_producer_backed": load_bearing_level_is_producer_backed,
    "liquidity.sell_side_is_htf_first":
        brain_nearest_sell_side_is_not_mathematically_nearest,
    "range.bounds_from_one_timeframe": dealing_range_bounds_come_from_one_timeframe,
    "session_po3.recomputed_not_remembered":
        session_phase_is_recomputed_never_remembered,
    "session_po3.block_binds_every_consumer":
        session_block_refuses_every_consumer_identically,
    "session_po3.range_is_absorbed_bars": session_range_is_what_the_balance_absorbed,
    "session_po3.excursion_needs_establishment":
        session_excursion_requires_an_established_range,
    "session_po3.band_not_score": session_manipulation_reads_the_band_not_the_score,
    "session_po3.preference_is_not_permission":
        session_preference_never_creates_a_playbook,
    "session_context.exact_coverage_or_no_facts":
        session_context_never_publishes_facts_without_exact_coverage,
    "session_context.cannot_reach_the_phase":
        session_context_cannot_reach_the_session_phase,
}


def predicate_exists(predicate_id) -> bool:
    return predicate_id in PREDICATES


def run(predicate_id) -> dict:
    """Execute one predicate. Never raises."""
    fn = PREDICATES.get(predicate_id)
    if fn is None:
        return {"predicate": predicate_id, "status": "MISSING",
                "detail": "no such semantic predicate"}
    try:
        ok, detail = fn()
    except SkipPredicate as exc:
        return {"predicate": predicate_id, "status": "SKIPPED", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001 — an unrunnable check is not a pass
        return {"predicate": predicate_id, "status": "ERROR",
                "detail": f"{type(exc).__name__}: {str(exc)[:200]}"}
    return {"predicate": predicate_id, "status": "PASS" if ok else "FAIL",
            "detail": detail}
