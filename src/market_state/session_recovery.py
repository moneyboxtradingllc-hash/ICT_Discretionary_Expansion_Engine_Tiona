"""STARTUP-STATE-RECOVERY-KERNEL-1 — the market did not start when we did.

Deterministic hydration of current-session causal state from the canonical 1m
tape. Its single purpose is to remove PROCESS START TIME as a variable: given
the same tape, the same contract and the same canonical origin, the
reconstructed state must not depend on when the process happened to launch.

NON-AUTHORITATIVE BY CONSTRUCTION. Nothing here persists. It writes no
occurrence to the durable ledger, holds no ledger handle, and reconstructs into
state the caller owns and can throw away. That restraint is deliberate:
`CAUSAL-OCCURRENCE-IDENTITY-1` is unfinished, HTF occurrence identity is known
defective, and writing reconstructed history under a defective identity would
put exactly the wrong thing beyond reach. Observations are returned for
certification, never as evidence.

NO SECOND MARKET ENGINE. Every mechanic below is the canonical one, in the
canonical order, following the precedent already set by
`ProductionScanCycle._rebuild_from_canonical_history`:

    bars[:end] -> build_timeframes -> build_snapshot -> extract_occurrences

with the stateful trackers carried across steps exactly as live processing
carries them. A private reconstruction would be a second definition of what a
swing is.

WARMUP IS NOT THE SESSION. Bars before the session boundary are legitimately
required to know what already existed at the bell -- the 15m swing a 09:31 raid
attacks was formed long before 09:00. Those bars establish STATE; they do not
make their events current-session events. Each observation is tagged, and the
distinction is kept rather than resolved by truncation, which would destroy the
very structure the opening raid was aimed at.

ZERO AUTHORITY. No provider, no router, no candidate, no risk, no mission, no
broker. A historical opportunity is not an opportunity; it is a fact about a
market that has already moved on.
"""
from __future__ import annotations

from data_feed.timeframe_builder import build_timeframes
from market_data.snapshot_builder import build_snapshot
from market_state.active_path import ActivePath, extract_occurrences

SCHEMA = "session_recovery.v1"

#: Matches `ProductionScanCycle.REBUILD_MIN_BARS`. The canonical rebuild refuses
#: to derive from less, and recovery may not claim a lower evidence bar.
MIN_BARS = 20


def _ts(bar) -> str:
    return str((bar or {}).get("timestamp") or "")


def recover(*, bars_1m, contract_id, symbol=None, session_start=None,
            handoff=None, min_bars=MIN_BARS, swing_tracker=None):
    """Rebuild causal session state from the canonical tape. Never raises.

    `session_start` marks where CURRENT-SESSION event ownership begins; bars
    before it are warmup and their observations are tagged `in_session=False`.
    `handoff` stops the replay at the last bar at or before it, which is where
    live processing would take over.

    Returns the reconstructed state plus the observations that produced it. The
    caller owns everything: nothing is written anywhere.
    """
    bars = [b for b in (bars_1m or []) if _ts(b)]
    bars.sort(key=_ts)
    if handoff:
        bars = [b for b in bars if _ts(b) <= str(handoff)]

    out = {"schema": SCHEMA, "contract_id": contract_id,
           "session_start": session_start, "handoff": handoff,
           "bars_available": len(bars), "snapshots": 0, "observations": [],
           "active_path": None, "protected_swings": None,
           "last_snapshot_time": None, "sufficient": False, "error": None}
    if len(bars) < min_bars:
        out["error"] = (f"only {len(bars)} bars; {min_bars} required before "
                        "causal state may be derived")
        return out

    # THE SAME STATEFUL TRACKERS LIVE PROCESSING CARRIES, carried ACROSS steps.
    #
    # Leaving these to default per call was a real defect caught by the kernel's
    # own equivalence test: protected-swing state then restarts every snapshot,
    # so registrations never persist to be replaced or violated and the
    # reconstructed path diverges from a continuous run on the identical tape.
    # Carrying them is the entire point -- the canonical rebuild does exactly
    # this, and a recovery that dropped them would be a different mechanic
    # wearing the same name.
    from narrative_authority.protected_swings import ProtectedSwingTracker
    from structure.po3_alignment_manager import Po3StabilityManager
    from structure.session_po3 import SessionPo3Authority
    from volatility.expansion_stability import ExpansionStabilityManager

    if swing_tracker is None:
        swing_tracker = ProtectedSwingTracker()
    try:
        po3_stability = Po3StabilityManager()
        session_po3 = SessionPo3Authority()
        expansion_stability = ExpansionStabilityManager()
    except Exception:  # noqa: BLE001 — stability managers are optional context
        po3_stability = expansion_stability = session_po3 = None
    path, prior = ActivePath(), {}
    snapshot = None
    try:
        for end in range(min_bars, len(bars) + 1):
            window = bars[:end]
            at = _ts(window[-1])
            snapshot = build_snapshot(
                build_timeframes(window), ref_timestamp=at, symbol=symbol,
                swing_tracker=swing_tracker, po3_stability=po3_stability,
                session_po3=session_po3, deep_1m=window,
                expansion_stability=expansion_stability, contract_id=contract_id,
                # NO EXECUTABLE PRICE EXISTS HISTORICALLY. A candle close is not
                # a quote, and substituting one is the defect EXEC-PRICE-
                # FRESHNESS-1 removed. Anything needing a live quote has no
                # authority during recovery.
                execution_price=None)
            out["snapshots"] += 1

            occurrences = extract_occurrences(snapshot, prior, contract_id)
            prior = ((snapshot.get("protected_swings") or {})
                     .get("by_timeframe") or prior)

            in_session = (not session_start) or at >= str(session_start)
            for occ in occurrences:
                out["observations"].append({
                    "observed_at": at, "in_session": in_session,
                    "event_type": occ.get("event_type"),
                    "source_tf": occ.get("source_tf"),
                    "direction": occ.get("sweep_direction") or occ.get("direction"),
                    "level": occ.get("swept_level") or occ.get("level"),
                    "swing_id": occ.get("swing_id"),
                    "registered_at": occ.get("registered_at"),
                    "old_level": occ.get("old_level"),
                    # Carried so a reader can see WHICH identity produced it.
                    # It is not certified: HTF identity binds observation time.
                    "occurrence_id": occ.get("occurrence_id")})

            # Lifecycle is enforced exactly as live: a session or contract
            # boundary releases derived ownership rather than letting a leg
            # from warmup own the session it preceded.
            path.enforce_lifecycle(snapshot.get("timestamp"), contract_id)
            path.ingest(occurrences)
            path.mark_scan_end()

        out["active_path"] = path.state()
        out["protected_swings"] = ((snapshot or {}).get("protected_swings") or {}
                                   ).get("by_timeframe") or {}
        out["last_snapshot_time"] = (snapshot or {}).get("timestamp")
        out["sufficient"] = True
    except Exception as exc:  # noqa: BLE001 — recovery reports, never explodes
        out["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    return out


def transition_provenance(result) -> dict:
    """Protected-swing transitions keyed by their formation provenance.

    `swing_id` is `tf:side:price` and is NOT unique across a session -- a level
    can be taken and re-form at the same price. Pairing it with the record's own
    `registered_at` is what separates two lives of one price, and whether THAT
    pairing is deterministic across start times is precisely what this kernel
    exists to measure.
    """
    out = {}
    for obs in (result or {}).get("observations") or []:
        if not str(obs.get("event_type") or "").startswith("PROTECTED_SWING"):
            continue
        key = (obs.get("event_type"), obs.get("source_tf"), obs.get("swing_id"),
               obs.get("registered_at"))
        out.setdefault(key, obs)
    return out
