"""
VECTOR-3 — PO3 Stability Manager (stateful hysteresis wrapper).

`po3_engine` is intentionally PURE: deterministic in its inputs, no memory. But
the proven failure (alignment flicker) is temporal — a single 1m phase flip moving
d_count 2<->3 rewrites global alignment every scan. Temporal stability therefore
lives here, in a stateful wrapper around the pure engine, leaving the engine (and
its tests) untouched.

Two layers:
  1. Phase dead-band (per timeframe): a new winning phase replaces the held phase
     only if it clears PHASE_THRESHOLD and beats the runner-up by a margin; an
     ambiguous winner holds the previous phase; a decisive-but-unconfirmed winner
     must persist N scans. A material event grants immediate replacement.
  2. Alignment hysteresis (global): the global alignment changes immediately only
     on a material HTF (5m/15m) trigger; otherwise the new candidate must persist
     N scans. full_distribution_alignment additionally requires HTF confirmation.

Usage (live): construct once per session, call update(results) every scan with the
dict returned by analyze_po3_snapshot. One-shot callers that never persist the
instance get single-scan (pass-through-on-init) behaviour, which is safe.
"""
from structure import po3_config as cfg
from structure.po3_engine import _po3_alignment, PHASE_THRESHOLD, TIMEFRAMES


class Po3StabilityManager:
    def __init__(self):
        self._prev_result = {}        # tf -> last EMITTED (stabilized) per-tf dict
        self._phase_candidate = {}    # tf -> {"phase": str, "streak": int}
        self._live_alignment = None
        self._align_candidate = None  # {"alignment": str, "streak": int}

    # ── Phase dead-band ───────────────────────────────────────────────────────

    def _decisive(self, raw: dict) -> bool:
        winner = raw.get("winner_score", 0)
        gap = winner - raw.get("runner_up_score", 0)
        if winner < PHASE_THRESHOLD:
            return False
        return gap >= max(cfg.PHASE_MARGIN_ABS, cfg.PHASE_MARGIN_REL * winner)

    def _stabilize_phase(self, tf: str, raw: dict):
        """Return (emitted_result_dict, changed_bool) for one timeframe."""
        held_result = self._prev_result.get(tf)
        held_phase = held_result.get("phase") if held_result else None
        raw_phase = raw.get("phase", "no_phase")

        # Initialization — nothing to protect, adopt the engine read.
        if held_result is None:
            self._phase_candidate.pop(tf, None)
            return self._emit(tf, raw, held=False), True

        if raw_phase == held_phase:
            self._phase_candidate.pop(tf, None)
            return self._emit(tf, raw, held=False), False

        decisive = self._decisive(raw)
        material = raw.get("material_event", False)

        # Material + decisive → real structural change, adopt immediately.
        if decisive and material:
            self._phase_candidate.pop(tf, None)
            return self._emit(tf, raw, held=False), True

        # Decisive but no material event → require N consecutive confirmations.
        if decisive:
            cand = self._phase_candidate.get(tf)
            if cand and cand["phase"] == raw_phase:
                cand["streak"] += 1
            else:
                cand = {"phase": raw_phase, "streak": 1}
            self._phase_candidate[tf] = cand
            if cand["streak"] >= cfg.PHASE_PERSIST_N:
                self._phase_candidate.pop(tf, None)
                return self._emit(tf, raw, held=False), True
            return self._hold(tf, raw), False

        # Ambiguous winner (too close to runner-up) → hold previous, reset streak.
        self._phase_candidate.pop(tf, None)
        return self._hold(tf, raw), False

    def _emit(self, tf: str, raw: dict, held: bool) -> dict:
        out = dict(raw)
        out["stabilized_held"] = held
        out["raw_phase"] = raw.get("phase", "no_phase")
        self._prev_result[tf] = out
        return out

    def _hold(self, tf: str, raw: dict) -> dict:
        """Re-emit the last trusted read, annotated with what was rejected."""
        out = dict(self._prev_result[tf])
        out["stabilized_held"] = True
        out["raw_phase"] = raw.get("phase", "no_phase")
        # keep self._prev_result[tf] as the held (trusted) result
        self._prev_result[tf] = out
        return out

    # ── Alignment hysteresis ──────────────────────────────────────────────────

    def _candidate_alignment(self, stabilized: dict) -> str:
        cand = _po3_alignment(stabilized)
        if cand == "full_distribution_alignment":
            htf_distrib = any(
                stabilized.get(tf, {}).get("phase") == "distribution"
                for tf in cfg.HTF_TRIGGER_TFS
            )
            if not htf_distrib:
                cand = "mixed"
        return cand

    # ── Entry point ───────────────────────────────────────────────────────────

    def update(self, results: dict) -> dict:
        stabilized = {}
        changed = {}
        for tf in TIMEFRAMES:
            if tf in results and isinstance(results[tf], dict):
                stabilized[tf], changed[tf] = self._stabilize_phase(tf, results[tf])

        cand_align = self._candidate_alignment(stabilized)

        if self._live_alignment is None:
            self._live_alignment = cand_align
            self._align_candidate = None
        elif cand_align == self._live_alignment:
            self._align_candidate = None
        else:
            htf_material = any(
                changed.get(tf) and stabilized.get(tf, {}).get("material_event", False)
                for tf in cfg.HTF_TRIGGER_TFS
            )
            if htf_material:
                self._live_alignment = cand_align
                self._align_candidate = None
            else:
                c = self._align_candidate
                if c and c["alignment"] == cand_align:
                    c["streak"] += 1
                else:
                    c = {"alignment": cand_align, "streak": 1}
                self._align_candidate = c
                if c["streak"] >= cfg.ALIGN_PERSIST_N:
                    self._live_alignment = cand_align
                    self._align_candidate = None
                # else: hold live alignment

        out = dict(results)
        out.update(stabilized)
        out["alignment"] = self._live_alignment
        out["alignment_candidate"] = cand_align
        out["alignment_held"] = (cand_align != self._live_alignment)
        return out
