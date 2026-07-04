"""
META-1 — Meta-Awareness Engine (organ self-observation).

The organism watches the market. Now it watches itself.

A rolling-window observer that inspects every scan's organ outputs plus the
persistent adaptive stores, detects drift, scores instability, and emits a
per-scan health report. Six monitored organ groups:

    brain        — ECU Brain (fallbacks, degraded input, thesis flips,
                   confidence instability)
    authority    — cross-organ agreement (AB-4 divergence, MC contradictions,
                   narrative conflict flags)
    adaptive     — mutation frequency, probation failures / repeated re-locks
    suppression  — false-suppression clusters, over-blocking by one owner
    execution    — denial clusters (real opportunities dying pre-broker),
                   broker call errors
    memory       — data-integrity drift (tables vs ledger, scar-state
                   staleness, suppression-metrics consistency)

DOCTRINE (PHASE 6 — observe-only governance):
  * META-1 has NO live authority. It blocks nothing, changes no confidence,
    no size, no playbook. authority_level is hard-locked "observe_only".
  * Read-only against all stores (performance root: tables, ledger,
    scar_state, suppression_metrics). It writes nothing anywhere.
  * Never raises into the scan loop — on internal failure it reports itself
    (organ "meta") as degraded rather than guessing organism health.

Health states: healthy -> watchlist -> degraded -> critical.
Signal levels: watch (+8), degraded (+20), critical (+40); score capped 100.
State = critical when ANY critical signal exists; else by score
(0 healthy, <25 watchlist, <50 degraded, else critical).
"""
from __future__ import annotations

import json
import os
from collections import deque

from adaptive_learning.performance_tables import (
    performance_root, _norm_symbol, TABLE_FILES, LEDGER_FILE,
)
from adaptive_learning.memory_decay_engine import SCAR_STATE_FILE
from adaptive_learning.suppression_cost_engine import METRICS_FILE

AUTHORITY_LEVEL = "observe_only"   # HARD-LOCK

WINDOW_DEFAULT = 30
MIN_WINDOW     = 6      # rolling signals need at least this many scans

LEVEL_WATCH, LEVEL_DEGRADED, LEVEL_CRITICAL = "watch", "degraded", "critical"
_LEVEL_POINTS = {LEVEL_WATCH: 8, LEVEL_DEGRADED: 20, LEVEL_CRITICAL: 40}
_LEVEL_RANK   = {LEVEL_WATCH: 1, LEVEL_DEGRADED: 2, LEVEL_CRITICAL: 3}

STATE_HEALTHY, STATE_WATCHLIST, STATE_DEGRADED, STATE_CRITICAL = (
    "healthy", "watchlist", "degraded", "critical")

ORGANS = ("brain", "authority", "adaptive", "suppression", "execution", "memory")

# thresholds (documented drift model — PHASE 2)
BRAIN_FALLBACK_RATE     = 0.30
BRAIN_FLIP_RATE         = 0.40
BRAIN_CONF_SWING        = 35
AUTHORITY_CONFLICT_RATE = 0.50
MUTATION_RATE_EXCESS    = 0.80
RELOCK_INSTABILITY      = 3      # lock_count >= 3 on any scar record
FALSE_SUPPRESS_CLUSTER  = 3      # false suppressions in one bucket
SUPPRESS_ACCURACY_FLOOR = 0.40
OVERBLOCK_OWNER_RATE    = 0.90   # one owner on >=90% of blocked-opportunity scans
DENIAL_CLUSTER_RATE     = 0.95   # opportunities dying pre-broker
DENIAL_MIN_OPPS         = 6


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _num(v, default=None):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else default


class MetaAwarenessEngine:
    """Per-instance rolling observer. The live scan loop owns one instance and
    calls observe(snapshot) once per scan."""

    def __init__(self, symbol: str = None, window: int = WINDOW_DEFAULT,
                 base_dir: "str | None" = None):
        self.symbol = symbol
        self.window = max(int(window), MIN_WINDOW)
        self.base_dir = base_dir
        self._obs = deque(maxlen=self.window)

    # ── PHASE 3.1 — inspect_organs ────────────────────────────────────────────

    def inspect_organs(self, snapshot: dict) -> dict:
        """Extract one scan's raw organ observations (pure; no I/O)."""
        s = snapshot or {}
        brain = s.get("ai_brain") or {}
        out = brain.get("output") if isinstance(brain.get("output"), dict) else {}
        degraded = brain.get("input_degraded")
        degraded = bool(degraded) if not isinstance(degraded, list) else bool(degraded)
        source = str(brain.get("source") or "")

        div = s.get("ai_divergence") or {}
        mc = s.get("market_commander") or {}
        contradictions = list((mc.get("consistency") or {}).get("contradictions") or [])
        na_conflicts = list((s.get("narrative_authority") or {}).get("conflict_flags") or [])

        decision = ((s.get("decision_authority") or {}).get("decision") or "").lower()
        pe = s.get("paper_execution") or {}
        bt = pe.get("broker_trace") or {}
        opportunity = (decision in ("ready_for_execution", "prepare_long",
                                    "prepare_short")
                       or bool((s.get("trade_intent") or {}).get("intent_created")))

        try:
            from live_scan.snapshot_store import build_block_trace
            owners = sorted({b.get("layer") for b in build_block_trace(s)
                             if b.get("layer")})
        except Exception:  # noqa: BLE001
            owners = []

        return {
            "brain_enabled":     bool(brain.get("enabled")),
            "brain_fallback":    bool(brain.get("enabled")) and (
                degraded or source in ("deterministic", "fallback_none")),
            "brain_direction":   (out.get("narrative_direction") or "neutral").lower(),
            "brain_confidence":  _num(out.get("phase_confidence")),
            "diverged":          bool(div.get("diverged")),
            "contradictions":    bool(contradictions or na_conflicts),
            "mutated":           bool((s.get("adaptive_mutation") or {}).get("mutated")),
            "opportunity":       opportunity,
            "submitted":         (pe.get("status") or "").lower() == "submitted",
            "broker_error":      bool(bt.get("error")),
            "block_owners":      owners,
        }

    # ── PHASE 3.2 — detect_drift ──────────────────────────────────────────────

    def detect_drift(self, symbol: str = None) -> list:
        """Rolling-window + store-integrity drift signals."""
        signals = []
        obs = list(self._obs)
        n = len(obs)

        def _sig(organ, name, level, detail):
            signals.append({"organ": organ, "signal": name,
                            "level": level, "detail": detail})

        # ── A. brain drift (rolling) ──
        if n >= MIN_WINDOW:
            enabled = [o for o in obs if o["brain_enabled"]]
            if enabled:
                fb = sum(1 for o in enabled if o["brain_fallback"]) / len(enabled)
                if fb > BRAIN_FALLBACK_RATE:
                    _sig("brain", "fallback_frequency", LEVEL_DEGRADED,
                         f"{fb:.0%} of scans on fallback/degraded input")
                dirs = [o["brain_direction"] for o in enabled
                        if o["brain_direction"] in ("bullish", "bearish")]
                flips = sum(1 for a, b in zip(dirs, dirs[1:]) if a != b)
                if len(dirs) >= MIN_WINDOW and flips / max(len(dirs) - 1, 1) > BRAIN_FLIP_RATE:
                    _sig("brain", "thesis_flip_frequency", LEVEL_WATCH,
                         f"{flips} flips over {len(dirs)} directional scans")
                confs = [o["brain_confidence"] for o in enabled
                         if o["brain_confidence"] is not None]
                if len(confs) >= MIN_WINDOW and (max(confs) - min(confs)) > BRAIN_CONF_SWING:
                    _sig("brain", "confidence_instability", LEVEL_WATCH,
                         f"confidence swing {min(confs)}..{max(confs)} in window")

            # ── B. authority conflict (rolling) ──
            conflict = sum(1 for o in obs if o["diverged"] or o["contradictions"]) / n
            if conflict > AUTHORITY_CONFLICT_RATE:
                _sig("authority", "contradiction_spike", LEVEL_DEGRADED,
                     f"{conflict:.0%} of scans carry divergence/contradictions")

            # ── C. adaptive instability (rolling part) ──
            mut = sum(1 for o in obs if o["mutated"]) / n
            if mut > MUTATION_RATE_EXCESS:
                _sig("adaptive", "excessive_mutation_frequency", LEVEL_WATCH,
                     f"mutation active on {mut:.0%} of scans")

            # ── D. suppression over-blocking by owner (rolling) ──
            opp_blocked = [o for o in obs
                           if o["opportunity"] and not o["submitted"]
                           and o["block_owners"]]
            if len(opp_blocked) >= DENIAL_MIN_OPPS:
                counts = {}
                for o in opp_blocked:
                    for owner in o["block_owners"]:
                        counts[owner] = counts.get(owner, 0) + 1
                for owner, c in counts.items():
                    if c / len(opp_blocked) >= OVERBLOCK_OWNER_RATE:
                        _sig("suppression", "overblocking_owner", LEVEL_WATCH,
                             f"{owner} present on {c}/{len(opp_blocked)} blocked opportunities")

            # ── E. execution instability (rolling) ──
            opps = [o for o in obs if o["opportunity"]]
            if len(opps) >= DENIAL_MIN_OPPS:
                denied = sum(1 for o in opps if not o["submitted"]) / len(opps)
                if denied >= DENIAL_CLUSTER_RATE:
                    _sig("execution", "denial_cluster", LEVEL_WATCH,
                         f"{denied:.0%} of {len(opps)} opportunities died pre-broker")
            if any(o["broker_error"] for o in obs):
                _sig("execution", "broker_error_observed", LEVEL_DEGRADED,
                     "broker call error inside window")

        # ── store-backed signals (C/D/F) ──
        sym = _norm_symbol(symbol or self.symbol or "")
        if sym and sym != "UNKNOWN":
            root = os.path.join(performance_root(self.base_dir), sym)

            # C. repeated re-locks / probation failures
            scars = _load_json(os.path.join(root, SCAR_STATE_FILE))
            for key, rec in scars.items():
                if int(rec.get("lock_count", 0) or 0) >= RELOCK_INSTABILITY:
                    _sig("adaptive", "repeated_relocks", LEVEL_DEGRADED,
                         f"{key}: lock_count {rec.get('lock_count')} "
                         "(probation keeps failing)")

            # D. false-suppression clusters
            metrics = _load_json(os.path.join(root, METRICS_FILE))
            for dim, table in metrics.items():
                if not isinstance(table, dict):
                    continue
                for key, b in table.items():
                    false_ = int(b.get("false_suppressions", 0) or 0)
                    acc = b.get("suppression_accuracy")
                    if false_ >= FALSE_SUPPRESS_CLUSTER and (
                            acc is not None and acc < SUPPRESS_ACCURACY_FLOOR):
                        _sig("suppression", "false_suppression_cluster",
                             LEVEL_DEGRADED,
                             f"{dim}({key}): {false_} false suppressions, "
                             f"accuracy {acc}")
                    # F. suppression metrics self-consistency
                    total = int(b.get("suppressed_total", 0) or 0)
                    parts = sum(int(b.get(f, 0) or 0) for f in (
                        "correct_suppressions", "false_suppressions",
                        "neutral_suppressions", "expired_suppressions"))
                    if parts != total:
                        _sig("memory", "suppression_metrics_mismatch",
                             LEVEL_CRITICAL,
                             f"{dim}({key}): parts {parts} != total {total}")

            # F. tables vs ledger integrity
            ledger = _load_json(os.path.join(root, LEDGER_FILE))
            if ledger:
                for dim, fname in TABLE_FILES.items():
                    table = _load_json(os.path.join(root, fname))
                    tot = sum(int(b.get("trades", 0) or 0)
                              for b in table.values() if isinstance(b, dict))
                    if table and tot != len(ledger):
                        _sig("memory", "table_ledger_mismatch", LEVEL_CRITICAL,
                             f"{dim}: table trades {tot} != ledger {len(ledger)}")

        return signals

    # ── PHASE 3.3 — score_instability ─────────────────────────────────────────

    @staticmethod
    def score_instability(signals: list) -> tuple:
        """(instability_score 0-100, health_state)."""
        score = min(100, sum(_LEVEL_POINTS.get(s["level"], 8) for s in signals))
        if any(s["level"] == LEVEL_CRITICAL for s in signals):
            return score, STATE_CRITICAL
        if score == 0:
            return 0, STATE_HEALTHY
        if score < 25:
            return score, STATE_WATCHLIST
        if score < 50:
            return score, STATE_DEGRADED
        return score, STATE_CRITICAL

    # ── PHASE 3.4 — generate_health_report ───────────────────────────────────

    def generate_health_report(self, signals: list) -> dict:
        organ_health = {}
        for organ in ORGANS:
            organ_signals = [s for s in signals if s["organ"] == organ]
            if not organ_signals:
                organ_health[organ] = STATE_HEALTHY
            else:
                worst = max(_LEVEL_RANK[s["level"]] for s in organ_signals)
                organ_health[organ] = {1: STATE_WATCHLIST, 2: STATE_DEGRADED,
                                       3: STATE_CRITICAL}[worst]
        score, state = self.score_instability(signals)
        return {
            "authority_level":   AUTHORITY_LEVEL,
            "health_state":      state,
            "instability_score": score,
            "organ_health":      organ_health,
            # PHASE 5 forensic aliases — the organism must explain itself
            "brain_health":       organ_health["brain"],
            "authority_health":   organ_health["authority"],
            "adaptive_health":    organ_health["adaptive"],
            "suppression_health": organ_health["suppression"],
            "execution_health":   organ_health["execution"],
            "memory_health":      organ_health["memory"],
            "drift_signals":     signals,
            "watch_flags":       [s["signal"] for s in signals
                                  if s["level"] == LEVEL_WATCH],
            "critical_flags":    [s["signal"] for s in signals
                                  if s["level"] == LEVEL_CRITICAL],
            "window_scans":      len(self._obs),
        }

    # ── public per-scan entry point ───────────────────────────────────────────

    def observe(self, snapshot: dict, symbol: str = None) -> dict:
        """Ingest one scan, evaluate drift, return the health report.
        OBSERVE-ONLY; never raises into the scan loop."""
        try:
            self._obs.append(self.inspect_organs(snapshot))
            signals = self.detect_drift(symbol)
            return self.generate_health_report(signals)
        except Exception as exc:  # noqa: BLE001
            return {
                "authority_level":   AUTHORITY_LEVEL,
                "health_state":      STATE_DEGRADED,
                "instability_score": _LEVEL_POINTS[LEVEL_DEGRADED],
                "organ_health":      {o: STATE_HEALTHY for o in ORGANS},
                "brain_health": STATE_HEALTHY, "authority_health": STATE_HEALTHY,
                "adaptive_health": STATE_HEALTHY, "suppression_health": STATE_HEALTHY,
                "execution_health": STATE_HEALTHY, "memory_health": STATE_HEALTHY,
                "drift_signals": [{"organ": "meta", "signal": "meta_engine_error",
                                   "level": LEVEL_DEGRADED,
                                   "detail": f"{type(exc).__name__}"}],
                "watch_flags": [], "critical_flags": [],
                "window_scans": len(self._obs),
            }
