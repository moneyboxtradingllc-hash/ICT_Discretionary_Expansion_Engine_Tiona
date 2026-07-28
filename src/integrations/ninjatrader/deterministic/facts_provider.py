"""Mechanical facts provider — WIRED to the organism's real authorities on MNQ.

Builds the canonical snapshot from MNQ bars via the SAME deterministic mechanical
pipeline the organism uses (build_snapshot; the AI Brain is gated OFF by default,
so NO OpenAI is called), then extracts the 20 mechanical facts the deterministic
author needs from the REAL subsystems:

  * qualification / playbook / decision  -> direction + setup family
  * structure / liquidity / expansion    -> structural / liquidity / displacement evidence
  * narrative_authority                  -> protected-zone permit + invalidation level
  * market_commander (via execution_gate)-> environmental permit / STAND_DOWN
  * execution_gate                       -> trigger, regime, council, promoted-rule,
                                            narrative, commander permits
  * structural swing / protected swing   -> structural invalidation price fallback

The gate's BRAIN_AUTHORSHIP check is deliberately EXCLUDED: this lane is authored
by deterministic_sim_author (explicit predicates), never the AI Brain. FC-0B's
chase-cap intent is enforced by this lane's 20-pt structural stop cap.
"""
from __future__ import annotations

import sys
from typing import Optional

# Bullish/bearish -> long/short. Anything else (neutral/conflicted) -> unknown.
_BULL_BEAR = {"bullish": "long", "bearish": "short"}
_TFS = ("1m", "3m", "5m", "15m")


def _dir(x) -> Optional[str]:
    return _BULL_BEAR.get(str(x).lower())


def _any_tf(d: dict, key: str) -> bool:
    return any(bool((d.get(tf) or {}).get(key)) for tf in _TFS)


_SWING_TRACKER = None


def _swing_tracker():
    """Module-level persistent tracker for this lane.

    Held here rather than in loop.py so every entry point into
    build_mnq_snapshot — live loop, backtest, replay harness — shares one
    tracker, the same way scan_loop holds one for its lane.
    """
    global _SWING_TRACKER
    if _SWING_TRACKER is None:
        from narrative_authority.protected_swings import ProtectedSwingTracker
        _SWING_TRACKER = ProtectedSwingTracker()
    return _SWING_TRACKER


_SETUP_TRACKER = None
_PREV_SNAPSHOT = None
_PREV_QUAL = None
_BARS_IN_STATE = 0


def _setup_tracker():
    """Persistent setup lifecycle for this lane — same rationale as the swings.

    The execution gate enforces a minimum setup age, read from
    snapshot["setup_lifecycle"]["age_scans"] and only when that block is active.
    This lane never produced the block, so age was 0 on every scan and the age
    requirement could not be satisfied: 129 of 133 scans on 2026-07-24 blocked on
    "setup age requirement not met (required=2, actual=0)".
    """
    global _SETUP_TRACKER
    if _SETUP_TRACKER is None:
        from setup_lifecycle.setup_tracker import SetupTracker
        _SETUP_TRACKER = SetupTracker()
    return _SETUP_TRACKER


def reset_swing_tracker():
    """Drop all per-session lane state — for tests and a clean session start."""
    global _SWING_TRACKER, _SETUP_TRACKER, _PREV_SNAPSHOT, _PREV_QUAL, _BARS_IN_STATE
    _SWING_TRACKER = None
    _SETUP_TRACKER = None
    _PREV_SNAPSHOT = None
    _PREV_QUAL = None
    _BARS_IN_STATE = 0


def build_mnq_snapshot(bars: list):
    """Run the real mechanical pipeline on MNQ 1m bars. Returns
    (snapshot, decision, gate). No OpenAI (Brain gated off by default)."""
    from data_feed.timeframe_builder import build_timeframes
    from market_data.snapshot_builder import build_snapshot
    from trade_intent.intent_builder import build_intent
    from decision_authority.decision_engine import make_decision
    from execution_gate.execution_gate import evaluate_gate

    tfs = build_timeframes(bars or [])
    # The protected-swing tracker is STATEFUL BY DESIGN: "a protected level
    # persists until violated, not until the next scan forgets the sweep."
    # scan_loop and replay_session both hold a persistent instance; this lane
    # passed none, so build_snapshot constructed a fresh tracker every scan and
    # threw it away — the persistence layer had no persistence here.
    #
    # Measured on 2026-07-24 RTH, 133 scans:
    #   transient   protected_swings  14   active_liquidity_draw  66
    #   persistent  protected_swings 105   active_liquidity_draw 117
    snapshot = build_snapshot(tfs, symbol="MNQ SEP26",
                              swing_tracker=_swing_tracker())
    # Order and publication both matter, and this lane got both wrong.
    #
    # evaluate_gate and build_intent do not receive the decision as an argument —
    # they read snapshot["decision_authority"]["decision"]. This lane called
    # make_decision into a LOCAL variable and never published it, and it built
    # the intent before deciding at all. So the key the gate reads never existed,
    # normalize_decision(None) returned "stand_down", and the gate was told to
    # stand down on every scan no matter what the market did.
    #
    # Measured on 2026-07-24 RTH: decision_authority returned
    # ready_for_execution on 7 scans while the gate's blocking_factors read
    # "decision_authority decision=stand_down" on all 133 — the lane could not
    # authorize a trade under any conditions.
    #
    # scan_loop is the reference: transition, setup lifecycle, decide, publish,
    # gate, then build intent. state_transition must precede the setup tracker
    # (SetupTracker.update documents that dependency) and both must precede the
    # gate, which reads setup_lifecycle.age_scans.
    global _PREV_SNAPSHOT, _PREV_QUAL, _BARS_IN_STATE
    from state_transitions.transition_engine import analyze_transition

    _cur_qual = str((snapshot.get("qualification") or {}).get("status")
                    or "no_trade").lower()
    _BARS_IN_STATE = _BARS_IN_STATE + 1 if _cur_qual == _PREV_QUAL else 1
    snapshot["state_transition"] = analyze_transition(
        snapshot, _PREV_SNAPSHOT, _BARS_IN_STATE)
    _PREV_SNAPSHOT, _PREV_QUAL = snapshot, _cur_qual

    snapshot["setup_lifecycle"] = _setup_tracker().update(snapshot, "MNQ SEP26")

    snapshot["decision_authority"] = make_decision(snapshot)
    snapshot["execution_gate"] = evaluate_gate(snapshot)
    snapshot["trade_intent"] = build_intent(snapshot, "MNQ SEP26")
    decision = snapshot["decision_authority"]
    gate = snapshot["execution_gate"]
    # Hard invariant for this lane: the Brain must never have been invoked.
    if "openai" in sys.modules:
        raise RuntimeError("openai imported during deterministic MNQ scan — aborting")
    return snapshot, decision, gate


def _structural_invalidation(na: dict, structure: dict, direction: str,
                             entry: float) -> Optional[float]:
    """Structural invalidation price: narrative invalidation_level if present,
    else nearest protected swing / structure swing on the correct side."""
    lvl = na.get("invalidation_level")
    if isinstance(lvl, (int, float)) and lvl > 0:
        return float(lvl)
    if direction == "long":
        cands = [na.get("protected_low")] + \
                [(structure.get(tf) or {}).get("last_swing_low") for tf in _TFS]
        cands = [c for c in cands if isinstance(c, (int, float)) and c < entry]
        return max(cands) if cands else None      # nearest below entry
    if direction == "short":
        cands = [na.get("protected_high")] + \
                [(structure.get(tf) or {}).get("last_swing_high") for tf in _TFS]
        cands = [c for c in cands if isinstance(c, (int, float)) and c > entry]
        return min(cands) if cands else None      # nearest above entry
    return None


def _zone_displacement_confirmed(snapshot: dict, direction: Optional[str],
                                 price_level: dict) -> bool:
    """Deterministic entry trigger for THIS lane (operator rule, 2026-07-22):
    a candle that closes beyond the zone midpoint IN the trade direction is the
    entry EVEN IF that close carries price past the zone's far edge — the ICT
    displacement-out-of-zone entry. The candle must have overlapped the zone (so
    it is the displacement candle, not a distant bar). Missing data -> False.

    This SUPPLEMENTS, never weakens, the execution gate's own trigger: the gate's
    in-zone confirmation still counts; this additionally rescues the confirmation
    candles the gate was discarding because the confirming bar exited the zone
    (measured: ~70% of valid confirmations were being thrown away this way).
    """
    if direction not in ("long", "short") or not isinstance(price_level, dict):
        return False
    if price_level.get("level_type") in (None, "no_zone") or price_level.get("invalidated"):
        return False
    try:
        zlow, zhigh, mid = (price_level.get("zone_low"), price_level.get("zone_high"),
                            price_level.get("midpoint"))
        if zlow is None or zhigh is None or mid is None:
            return False
        zlow, zhigh, mid = float(zlow), float(zhigh), float(mid)
        tfs = snapshot.get("timeframes", {}) or {}
        last = None
        for tf in ("1m", "3m"):
            lc = (tfs.get(tf) or {}).get("last_candle")
            if lc and all(lc.get(k) is not None for k in ("open", "high", "low", "close")):
                last = lc
                break
        if last is None:
            return False
        o, h, l, c = (float(last["open"]), float(last["high"]),
                      float(last["low"]), float(last["close"]))
        overlaps_zone = (l <= zhigh) and (h >= zlow)   # candle interacted with the zone
        if not overlaps_zone:
            return False
        if direction == "long":
            return c > o and c > mid        # bullish close beyond midpoint
        return c < o and c < mid            # bearish close beyond midpoint
    except (TypeError, ValueError):
        return False


def build_facts_from_snapshot(snapshot: dict, decision: dict, gate: dict,
                              last_price: Optional[float]) -> dict:
    qual = snapshot.get("qualification", {}) or {}
    pb = snapshot.get("playbook", {}) or {}
    na = snapshot.get("narrative_authority", {}) or {}
    structure = snapshot.get("structure", {}) or {}
    liq = snapshot.get("liquidity", {}) or {}
    exp = snapshot.get("expansion", {}) or {}

    from paper_execution.order_builder import evaluate_fc0b, _preferred_candidate

    direction = _dir(decision.get("direction"))
    entry = last_price if isinstance(last_price, (int, float)) else None

    # Structural invalidation: the setup's REAL invalidation_level (price_level),
    # then narrative, then a protected/structure swing on the correct side.
    ti = snapshot.get("trade_intent", {}) or {}
    ez = ti.get("entry_zone") or {}
    pref_c = _preferred_candidate(snapshot)
    pl = (pref_c.get("price_level") or {}) if isinstance(pref_c, dict) else {}
    invalidation = pl.get("invalidation_level")
    if not isinstance(invalidation, (int, float)):
        invalidation = (_structural_invalidation(na, structure, direction, entry)
                        if (direction and entry) else None)

    commander_permits = bool(gate.get("commander_permits_trade", False))
    # Effective entry trigger: the gate's own in-zone confirmation OR the lane's
    # zone-displacement confirmation (operator rule — a candle closing beyond the
    # zone midpoint in-direction is the entry even if it exits the zone edge).
    disp_confirmed = _zone_displacement_confirmed(snapshot, direction, pl)
    eff_trigger = bool(gate.get("trigger_requirement_met", False) or disp_confirmed)
    # The mechanical (non-Brain) gate: every sub-authority the execution gate
    # checks EXCEPT brain_authorship, which this deterministic lane replaces.
    _GATE_KEYS = ("narrative_permits_trade", "commander_permits_trade",
                  "council_permits_trade", "regime_permission_allowed",
                  "no_promoted_rule_block")
    mech_gate = eff_trigger and all(bool(gate.get(k)) for k in _GATE_KEYS)

    # ATTRIBUTION. mech_gate collapses six independent authorities into one
    # boolean, and the author records only that boolean — so a NO_TRADE said
    # `final_gate_authorizes: False` without naming which authority refused. The
    # regime permission matrix vetoed live for weeks behind exactly this.
    # Every authority is now recorded individually, and the ones that refused are
    # named, so a hidden veto announces itself on the scan it happens rather than
    # in a replay months later.
    _permissions = {k: bool(gate.get(k)) for k in _GATE_KEYS}
    _permissions["trigger_requirement_met"] = bool(eff_trigger)
    _gate_blockers = sorted(k for k, v in _permissions.items() if not v)

    setup_family = pb.get("selected_playbook")
    if setup_family in (None, "", "no_playbook"):
        setup_family = None

    # ── ACTUAL FC-0B verdict — the sanctioned order_builder.evaluate_fc0b seam.
    # Entry-location / chase authority, SEPARATE from the 20-pt structural stop
    # cap (which stays its own check in the risk engine). Indeterminable FC-0B
    # inputs -> None -> author fails closed (NO_TRADE).
    # Entry-location inputs: prefer trade_intent.entry_zone, but FALL BACK to the
    # preferred candidate's price_level (same fallback fc_stop/fc_mid already use).
    # entry_zone is frequently empty even when price is at the zone, which would
    # otherwise leave FC-0B indeterminable (None) and block every authorization.
    fc_relation = ez.get("price_relation") or pl.get("price_relation")
    fc_entry = ez.get("current_price")
    if fc_entry is None:
        fc_entry = pl.get("current_price")
    if fc_entry is None:
        fc_entry = entry
    fc_stop = pl.get("invalidation_level")
    if fc_stop is None:
        fc_stop = ez.get("zone_low") if direction == "long" else ez.get("zone_high")
    fc_mid = pl.get("midpoint") if pl.get("midpoint") is not None else ez.get("midpoint")
    # Operator rule: a confirmed zone-displacement entry DID touch the zone (the
    # candle overlapped it), so treat it as touching_zone for FC-0B — this lifts the
    # in-zone veto while the CHASE CAP still applies (a displacement that ran too far
    # from the stop is still denied).
    if disp_confirmed and str(fc_relation or "").lower() not in ("inside_zone", "touching_zone"):
        fc_relation = "touching_zone"
    if fc_relation is None or fc_entry is None or fc_stop is None:
        fc0b = None   # FC-0B indeterminable -> NO_TRADE upstream
        fc0b_reason = ("FC-0B indeterminable — "
                       f"relation={fc_relation!r} entry={fc_entry!r} stop={fc_stop!r}")
    else:
        _fc_ok, _fc_reason = evaluate_fc0b("market", fc_relation, fc_entry, fc_stop, fc_mid)
        fc0b = bool(_fc_ok)
        fc0b_reason = _fc_reason

    return {
        "setup_family": setup_family,
        "direction": direction,
        "qualification_direction": _dir(qual.get("direction")),
        "playbook_direction": _dir(pb.get("direction")),
        "decision_direction": direction,
        "liquidity_evidence": bool(_any_tf(liq, "sweep_detected")),
        "structural_evidence": bool(_any_tf(structure, "bos") or _any_tf(structure, "mss")),
        "displacement_evidence": bool(_any_tf(exp, "displacement_detected")),
        "trigger_confirmed": eff_trigger,
        "protected_zone_permits": bool(gate.get("narrative_permits_trade", False)),
        # Commander verdict consumed ONLY through the sanctioned gate adapter
        # (commander_permits_trade), never the raw matrix.
        "commander_state": ("STAND_DOWN" if not commander_permits else "PROCEED"),
        # None when FC-0B is indeterminable -> author treats as unknown -> NO_TRADE.
        "fc0b_permits": (None if fc0b is None else bool(fc0b)),
        "entry_invalidation": invalidation,
        "opposing_direction": None,
        "final_gate_authorizes": bool(mech_gate),
        "expected_entry": entry,
        # Provenance.
        "_provenance": "WIRED: build_snapshot -> make_decision -> evaluate_gate "
                       "(brain_authorship excluded; deterministic authorship)",
        "_decision_state": decision.get("decision"),
        "_qual_status": qual.get("status"),
        # ── Diagnostics. Underscore keys are NOT mechanical facts — they are not
        # in _REQUIRED_FACT_KEYS and the author never reads them. Recorded so a
        # NO_TRADE can be explained after the fact (which FC-0B guard fired, where
        # the zone actually was, which swing anchored the invalidation) without
        # re-deriving zone/swing state from raw bars.
        "_gate_permissions": _permissions,
        "_gate_blockers": _gate_blockers,
        "_fc0b_reason": fc0b_reason,
        "_fc0b_inputs": {"relation": fc_relation, "entry": fc_entry, "stop": fc_stop,
                         "midpoint": fc_mid, "displacement_confirmed": disp_confirmed},
        "_zone": {"tool": (pref_c.get("tool") if isinstance(pref_c, dict) else None),
                  "level_type": pl.get("level_type"),
                  "zone_low": pl.get("zone_low"), "zone_high": pl.get("zone_high"),
                  "midpoint": pl.get("midpoint"),
                  "price_relation": pl.get("price_relation"),
                  "distance_to_zone": pl.get("distance_to_zone"),
                  "invalidation_level": pl.get("invalidation_level"),
                  "source_tf": pl.get("source_tf"),
                  "entry_zone_low": ez.get("zone_low"),
                  "entry_zone_high": ez.get("zone_high"),
                  "entry_zone_relation": ez.get("price_relation")},
        "_swings": {tf: {"hi": (structure.get(tf) or {}).get("last_swing_high"),
                         "lo": (structure.get(tf) or {}).get("last_swing_low")}
                    for tf in _TFS},
    }


def build_facts(bars: list, quote: dict) -> dict:
    """Convenience: build the snapshot and extract facts in one call."""
    snapshot, decision, gate = build_mnq_snapshot(bars)
    return build_facts_from_snapshot(snapshot, decision, gate,
                                     (quote or {}).get("last"))
