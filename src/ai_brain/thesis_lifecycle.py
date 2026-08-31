"""
Phase AB-7 — Persistent Thesis Lifecycle Engine.

The THESIS-1 audit proved the ECU is stateless at the thesis level: the Brain
regenerates `brain_thesis` from scratch every scan and the object is never loaded
back, so one-scan evidence flicker produces QUALIFIED->NO_PLAYBOOK churn and
70->0 qualification collapse.

This engine sits between thesis generation (`ai_brain.ecu.produce_thesis`) and the
consumers (qualification / playbook / toolbox / regime). The Brain still produces a
CANDIDATE thesis each scan; this engine maintains a persisted ACTIVE thesis and, per
scan, decides one lifecycle action: continue / strengthen / weaken / threaten /
promote / invalidate / replace. The active thesis survives across scans and restarts.

CORE RULE: a thesis is replaced only by invalidation or overwhelming evidence —
never by a single contrary candle or a one-scan no_playbook flicker.

AB-7.2 — Playbook Lifecycle Integration. The playbook is now persisted *with* the
thesis instead of being overwritten by the candidate every scan. A single
no_playbook scan no longer wipes the active playbook (the brain emits the literal
string "none" on ~66% of scans); the playbook carries its own lifecycle
(FORMING/ACTIVE/EXECUTABLE/WEAKENING/THREATENED/INVALIDATED) and only dies on
repeated absence or a sustained opposing playbook. Hardness ordering is enforced:
DIRECTION is harder to change than PLAYBOOK, which is harder to change than TOOL.
Conflicted / neutral theses also decay faster than directional ones.

AUTHORITY (gated by THESIS_LIFECYCLE_MODE, default `shadow`):
  - shadow (default): compute + persist + journal the lifecycle; the live pipeline
    is bit-for-bit unchanged (the caller leaves `brain_thesis` = candidate).
  - enforce: the caller overwrites `brain_thesis` with `as_brain_thesis()` so the
    consumers see the stabilized active thesis.

Persistence mirrors `ai_brain.stance_memory`: live state in
data/ai_brain/active_thesis.json, an append-only journal in
data/ai_brain/theses/YYYYMMDD_theses.jsonl. Never raises.
Rollback: THESIS_LIFECYCLE_MODE=shadow (or unset).
"""
import json
import os
import re
import uuid
from datetime import datetime

# ── Status / action / type vocabularies ──────────────────────────────────────
STATUS_FORMING      = "FORMING"
STATUS_DEVELOPING   = "DEVELOPING"
STATUS_ACTIVE       = "ACTIVE"
STATUS_EXECUTABLE   = "EXECUTABLE"
STATUS_WEAKENING    = "WEAKENING"
STATUS_THREATENED   = "THREATENED"
STATUS_INVALIDATED  = "INVALIDATED"
STATUS_COMPLETED    = "COMPLETED"
STATUS_EXPIRED      = "EXPIRED"

ACT_CREATE_NEW                = "CREATE_NEW"
ACT_CONTINUE                  = "CONTINUE"
ACT_STRENGTHEN                = "STRENGTHEN"
ACT_WEAKEN                    = "WEAKEN"
ACT_THREATEN                  = "THREATEN"
ACT_PROMOTE_TO_EXECUTABLE     = "PROMOTE_TO_EXECUTABLE"
ACT_INVALIDATE                = "INVALIDATE"
ACT_COMPLETE                  = "COMPLETE"
ACT_EXPIRE                    = "EXPIRE"
ACT_REPLACE_AFTER_INVALIDATION = "REPLACE_AFTER_INVALIDATION"
ACT_NONE                      = "NONE"

_DIRECTIONAL = ("bullish", "bearish")


# ── Env gating ────────────────────────────────────────────────────────────────

def lifecycle_enabled() -> bool:
    """AB-7 runs only under the ECU; this flag gates whether the lifecycle layer
    is active at all. shadow/enforce both run the engine; `off` skips it."""
    return _mode() in ("shadow", "enforce")


def _mode() -> str:
    m = os.getenv("THESIS_LIFECYCLE_MODE", "shadow").lower().strip()
    return m if m in ("shadow", "enforce", "off") else "shadow"


def enforce_mode() -> bool:
    return _mode() == "enforce"


def _min_age() -> int:
    try:
        return max(1, int(os.getenv("THESIS_MIN_AGE_SCANS", "3")))
    except (TypeError, ValueError):
        return 3


def _consecutive_required() -> int:
    try:
        return max(1, int(os.getenv("THESIS_INVALIDATION_CONSECUTIVE", "2")))
    except (TypeError, ValueError):
        return 2


def _max_age_scans() -> int:
    try:
        return max(0, int(os.getenv("THESIS_MAX_AGE_SCANS", "240")))
    except (TypeError, ValueError):
        return 240


def _max_reload_age_minutes() -> int:
    """Wall-clock idle time after which a persisted thesis is not resurrected.

    Default 720 (12h): an intraday restart still recovers its thesis, an
    overnight or multi-day gap never does. 0 disables the check.
    """
    try:
        return max(0, int(os.getenv("THESIS_MAX_RELOAD_AGE_MINUTES", "720")))
    except (TypeError, ValueError):
        return 720


def _minutes_since(stamp) -> "float | None":
    """Minutes between `stamp` and now, or None if it cannot be read.

    Tolerant of the NinjaTrader 7-digit fractional second ("…:00.0000000-04:00"),
    which datetime.fromisoformat rejects, and of naive stamps.
    """
    if not stamp:
        return None
    text = str(stamp).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # trim over-long fractional seconds to the 6 digits fromisoformat accepts
    m = re.match(r"^(.*\.\d{6})\d+(.*)$", text)
    if m:
        text = m.group(1) + m.group(2)
    try:
        when = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    now = datetime.now(when.tzinfo) if when.tzinfo else datetime.now()
    return (now - when).total_seconds() / 60.0


def _decay_step() -> int:
    try:
        return max(1, int(os.getenv("THESIS_CONFIDENCE_DECAY_STEP", "8")))
    except (TypeError, ValueError):
        return 8


def _exec_confidence() -> int:
    try:
        return max(0, int(os.getenv("THESIS_EXECUTABLE_CONFIDENCE", "70")))
    except (TypeError, ValueError):
        return 70


# ── AB-7.2 — playbook lifecycle knobs ─────────────────────────────────────────

# Candidate playbook values that carry NO actionable playbook this scan. The
# brain emits the literal string "none" most of the time; treating these as a
# real playbook is exactly the AB-7.1 bug that wiped the persisted playbook.
_NO_PLAYBOOK_SENTINELS = ("", "none", "no_playbook", "null", "wait", "n/a")


def _norm_playbook(v) -> "str | None":
    """Canonical playbook signal: a real playbook-family string, or None when the
    candidate carries no actionable playbook this scan."""
    if isinstance(v, (list, tuple)):
        v = v[0] if v else None
    if v is None:
        return None
    s = str(v).strip().lower()
    return None if s in _NO_PLAYBOOK_SENTINELS else s


def _playbook_absent_invalidation() -> int:
    """Consecutive no-playbook scans that retire an active playbook (Rule 3).
    Must exceed 1 so a single no_playbook flicker never kills the playbook."""
    try:
        return max(2, int(os.getenv("PLAYBOOK_ABSENT_INVALIDATION", "4")))
    except (TypeError, ValueError):
        return 4


def _playbook_switch_consecutive() -> int:
    """Consecutive scans of a *different* playbook required before the active
    playbook rotates. Keeps playbook harder to change than tool (instant)."""
    try:
        return max(1, int(os.getenv("PLAYBOOK_SWITCH_CONSECUTIVE", "2")))
    except (TypeError, ValueError):
        return 2


def _max_age_nondirectional() -> int:
    """Tighter age cap for conflicted / neutral (non-directional) theses so they
    decay faster than directional ones. 0 disables the tighter cap."""
    try:
        return max(0, int(os.getenv("THESIS_MAX_AGE_NONDIRECTIONAL", "12")))
    except (TypeError, ValueError):
        return 12


# ── Persistence paths ─────────────────────────────────────────────────────────

def _ai_brain_dir() -> str:
    return os.getenv("AI_BRAIN_DIR", os.path.join("data", "ai_brain"))


def _active_path() -> str:
    return os.path.join(_ai_brain_dir(), "active_thesis.json")


def _archive_path(ts: str) -> str:
    day = (ts or datetime.utcnow().isoformat())[:10].replace("-", "")
    return os.path.join(_ai_brain_dir(), "theses", f"{day}_theses.jsonl")


# ── Candidate → thesis-type mapping ───────────────────────────────────────────

def map_thesis_type(direction: str, phase: str, opportunity: bool) -> str:
    """Map a candidate's (direction, narrative_phase, opportunity) to a thesis_type,
    including the non-trade observation types (the system is no longer forced to
    pick bullish-trade / bearish-trade / no_playbook)."""
    d = (direction or "neutral").lower()
    p = (phase or "").lower()

    if d not in _DIRECTIONAL:
        if p == "exhaustion":
            return "trend_exhaustion_monitoring"
        return "no_trade_observation"

    if p in ("manipulation", "reversal"):
        return f"{d}_reversal_attempt"
    if p in ("expansion", "range_expansion"):
        return f"{d}_expansion"
    if p == "exhaustion":
        return "trend_exhaustion_monitoring"
    # continuation, distribution, transition, accumulation, default
    return f"{d}_continuation"


def _is_trade_type(thesis_type: str) -> bool:
    return thesis_type not in (
        "no_trade_observation",
        "trend_exhaustion_monitoring",
        "consolidation_at_highs",
        "consolidation_at_lows",
    )


# ── ActiveThesis construction ─────────────────────────────────────────────────

def _candidate_fields(candidate: dict) -> dict:
    """Extract the canonical fields from a produce_thesis()-shaped candidate."""
    c = candidate or {}
    bb = (c.get("brain_block") or {})
    out = (bb.get("output") or {}) if isinstance(bb, dict) else {}
    return {
        "direction":         (c.get("direction") or "neutral").lower(),
        "forbidden":         c.get("forbidden_direction"),
        "opportunity":       bool(c.get("opportunity")),
        "phase":             c.get("opportunity_type"),
        "playbook_family":   c.get("playbook_family"),
        "tool_family":       c.get("tool_family"),
        "confidence":        int(c.get("confidence") or 0),
        "reasoning":         c.get("dominant_reasoning") or "",
        "invalidation_level": out.get("invalidation_level"),
        "contradictions":    out.get("contradiction_flags") or [],
    }


def _new_thesis(cf: dict, ts: str, snapshot_id: str, origin: str) -> dict:
    ttype = map_thesis_type(cf["direction"], cf["phase"], cf["opportunity"])
    pb = _norm_playbook(cf["playbook_family"])
    return {
        "thesis_id":             f"TH_{uuid.uuid4().hex[:12]}",
        "created_at":            ts,
        "last_updated_at":       ts,
        "age_scans":             1,
        "age_minutes":           0.0,
        "direction":             cf["direction"],
        "playbook_family":       pb,
        "playbook_status":       (STATUS_FORMING if pb else None),
        "playbook_age_scans":    (1 if pb else 0),
        "tool_family":           cf["tool_family"],
        "thesis_type":           ttype,
        "status":                STATUS_FORMING,
        "confidence":            cf["confidence"],
        "confidence_history":    [cf["confidence"]],
        "supporting_evidence":   [cf["reasoning"]] if cf["reasoning"] else [],
        "weakening_evidence":    [],
        "contradiction_evidence": list(cf["contradictions"]),
        "invalidation_conditions": _invalidation_conditions(cf),
        "confirmation_conditions": [],
        "execution_conditions":  [],
        "invalidation_level":    cf["invalidation_level"],
        "forbidden_direction":   cf["forbidden"],
        "last_update_reason":    f"created from candidate ({origin})",
        "source_snapshot_id":    snapshot_id,
        "origin_reason":         origin,
        "replacement_allowed":   False,
        "invalidated_reason":    None,
        # internal counters (persisted)
        "_contrary_count":       0,
        "_no_playbook_count":    0,
        "_playbook_absent_count": 0,
        "_pending_playbook":     None,
        "_pending_playbook_count": 0,
    }


def _invalidation_conditions(cf: dict) -> list:
    conds = []
    if cf.get("invalidation_level") is not None:
        d = cf["direction"]
        side = "below" if d == "bullish" else ("above" if d == "bearish" else "level")
        conds.append(f"price {side} {cf['invalidation_level']}")
    conds.append(f"{_consecutive_required()} consecutive opposing/no_playbook scans")
    conds.append("opposing displacement / protected level broken with acceptance")
    return conds


# ── The engine ────────────────────────────────────────────────────────────────

class ThesisLifecycleEngine:
    """Holds the persisted active thesis across scans. Instantiate once before the
    scan loop; call update() each iteration. Never raises."""

    def __init__(self, persist: bool = True, symbol: str = None):
        self._active = None
        self._persist = persist
        # DECON-3: defaulted to "QQQ". Theses are persisted per symbol, so an
        # unnamed MNQ engine would match and resurrect a stored QQQ thesis.
        from doctrine.instrument_identity import PRODUCTION_INSTRUMENT
        self._symbol = symbol or os.getenv("SCAN_SYMBOL") or PRODUCTION_INSTRUMENT
        # Foreign/identity-less persisted state found at load, if any.
        # Always defined so callers and telemetry never branch on hasattr.
        self.quarantined = None
        if persist:
            self._load()

    # ── persistence ───────────────────────────────────────────────────────────
    def _load(self) -> None:
        self.quarantined = None
        try:
            path = _active_path()
            if not os.path.exists(path):
                return
            data = json.load(open(path, encoding="utf-8"))
            active = data.get("active")
            if not active:
                return
            # Restart safety: only resurrect a same-instrument, non-terminal,
            # in-age thesis.
            #
            # DECONTAMINATE (2026-08-06): this checked only active["symbol"],
            # but the record stores the instrument at the FILE level. The stale
            # 2026-06-15 QQQ thesis therefore had active.get("symbol") is None,
            # the guard never fired, and only the idle-expiry check incidentally
            # kept it out of an MNQ session. Identity is now checked where it is
            # actually written, and a foreign thesis is QUARANTINED -- reported,
            # never relabelled, never fed to the Brain.
            stored = (active.get("symbol") or data.get("symbol") or "").strip()
            if stored and stored != self._symbol:
                self.quarantined = {"reason": "foreign_instrument",
                                    "stored_instrument": stored,
                                    "session_instrument": self._symbol,
                                    "thesis_id": active.get("thesis_id"),
                                    "created_at": active.get("created_at"),
                                    "path": path}
                self._active = None
                return
            if not stored:
                self.quarantined = {"reason": "missing_instrument_identity",
                                    "stored_instrument": None,
                                    "session_instrument": self._symbol,
                                    "thesis_id": active.get("thesis_id"),
                                    "created_at": active.get("created_at"),
                                    "path": path}
                self._active = None
                return
            if active.get("status") in (STATUS_INVALIDATED, STATUS_EXPIRED, STATUS_COMPLETED):
                return
            cap = _max_age_scans()
            if cap and int(active.get("age_scans", 0)) > cap:
                active["status"] = STATUS_EXPIRED
                active["invalidated_reason"] = "expired on reload (max age exceeded)"
                self._active = active
                return
            # age_scans counts scans, not time, so a thesis that sat on disk for
            # weeks is indistinguishable from one opened three scans ago. Observed
            # 2026-07-24: a thesis created 2026-06-15 reloaded with age_scans=10,
            # far under the cap, and was carried into a live session 39 days later.
            # A thesis is an intraday object; the clock has to be consulted too.
            stale_after = _max_reload_age_minutes()
            idle = _minutes_since(active.get("last_updated_at"))
            if stale_after and idle is not None and idle > stale_after:
                active["status"] = STATUS_EXPIRED
                active["invalidated_reason"] = (
                    f"expired on reload (idle {int(idle)} min > {stale_after} min)")
                self._active = active
                return
            self._active = active
        except Exception:  # noqa: BLE001
            self._active = None

    def _save(self) -> None:
        if not self._persist:
            return
        try:
            path = _active_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            payload = {"symbol": self._symbol,
                       "active": (dict(self._active, symbol=self._symbol)
                                  if self._active else None)}
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, default=str)
        except Exception:  # noqa: BLE001
            pass

    # ── history revision (CONTINUITY-2B, 2026-08-11) ─────────────────────────
    def invalidate_on_history_revision(self, revision: int, ts: str = "") -> dict:
        """Kill an active thesis that was formed from a superseded tape.

        `thesis_state` reaches `trade_qualification_engine`, so a thesis built
        while twenty minutes of history were missing keeps gating candidates
        after the tape is repaired. It cannot be re-derived the way a swing can
        -- it was a reading of evidence, and that evidence has changed -- so it
        is INVALIDATED rather than replayed.

        Uses the existing lifecycle vocabulary rather than a new one: `_load`
        already discards a persisted thesis in INVALIDATED, so this survives a
        restart without any additional mechanism. Never raises.
        """
        try:
            if not self._active:
                return {"invalidated": False, "reason": "no active thesis"}
            thesis = self._active
            thesis["status"] = STATUS_INVALIDATED
            thesis["invalidation_reason"] = (
                f"market history revised to r{revision}; this thesis was formed "
                "from a tape that has since been repaired")
            thesis["invalidated_at_history_revision"] = int(revision)
            self._journal("invalidated_by_history_revision", thesis, ts or "")
            self._active = None
            self._save()
            return {"invalidated": True, "revision": int(revision),
                    "thesis_id": thesis.get("thesis_id") or thesis.get("id")}
        except Exception:  # noqa: BLE001 — may never cost a scan
            return {"invalidated": False, "error": True}

    def _journal(self, action: str, thesis: dict, ts: str) -> None:
        if not self._persist:
            return
        try:
            path = _archive_path(ts)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            row = {"timestamp": ts, "action": action, "symbol": self._symbol,
                   "thesis_id": thesis.get("thesis_id"),
                   "status": thesis.get("status"),
                   "direction": thesis.get("direction"),
                   "thesis_type": thesis.get("thesis_type"),
                   "playbook_family": thesis.get("playbook_family"),
                   "playbook_status": thesis.get("playbook_status"),
                   "playbook_age_scans": thesis.get("playbook_age_scans"),
                   "confidence": thesis.get("confidence"),
                   "age_scans": thesis.get("age_scans"),
                   "reason": thesis.get("last_update_reason")}
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, default=str) + "\n")
        except Exception:  # noqa: BLE001
            pass

    # ── public API ──────────────────────────────────────────────────────────────
    def update(self, candidate: dict, evidence: dict = None, timestamp: str = None) -> dict:
        """Advance the lifecycle by one scan. Returns the thesis_lifecycle block.
        Never raises."""
        try:
            return self._update(candidate or {}, evidence or {},
                                timestamp or datetime.utcnow().isoformat())
        except Exception as exc:  # noqa: BLE001
            return {"enabled": True, "mode": _mode(), "action": ACT_NONE,
                    "active_thesis": self._active,
                    "error": f"thesis lifecycle error (non-blocking): {exc}"}

    def _update(self, candidate: dict, evidence: dict, ts: str) -> dict:
        cf = _candidate_fields(candidate)
        snap_id = evidence.get("snapshot_id") or ts

        # ── No active thesis: create one if the candidate carries any state ──────
        if self._active is None:
            self._active = _new_thesis(cf, ts, snap_id, "fresh_candidate")
            return self._emit(ACT_CREATE_NEW, ts)

        a = self._active

        # ── Expiry (hard age cap) ────────────────────────────────────────────────
        # Conflicted / neutral (non-directional) theses decay faster than
        # directional ones — they should not linger for dozens of scans (AB-7.1
        # replay found conflicted theses persisting 52 scans in WEAKENING).
        cap = _max_age_scans()
        nd_cap = _max_age_nondirectional()
        if nd_cap and (a["direction"] not in _DIRECTIONAL or not _is_trade_type(a["thesis_type"])):
            cap = min(cap, nd_cap) if cap else nd_cap
        if cap and a["age_scans"] >= cap:
            a["status"] = STATUS_EXPIRED
            a["last_update_reason"] = "max age reached"
            a["invalidated_reason"] = "expired"
            out = self._emit(ACT_EXPIRE, ts)
            self._retire_and_maybe_replace(cf, ts, snap_id)
            return out

        # ── Hard material invalidation (bypasses the consecutive-scan rule) ──────
        hard = self._hard_invalidation(a, cf, evidence)
        if hard:
            a["status"] = STATUS_INVALIDATED
            a["invalidated_reason"] = hard
            a["last_update_reason"] = f"hard invalidation: {hard}"
            a["weakening_evidence"].append(hard)
            out = self._emit(ACT_INVALIDATE, ts)
            return self._retire_and_maybe_replace(cf, ts, snap_id, base=out)

        agrees = self._candidate_agrees(a, cf)

        if agrees:
            return self._advance_agreeing(a, cf, ts)
        return self._advance_contrary(a, cf, ts, snap_id)

    # ── agreement / contradiction ────────────────────────────────────────────────
    def _candidate_agrees(self, a: dict, cf: dict) -> bool:
        """A candidate agrees when it does not oppose the active direction.
        Same direction = agreement; a neutral / no-opportunity candidate is a
        WEAKENING signal (handled as contrary, but non-opposing)."""
        ad, cd = a["direction"], cf["direction"]
        if ad in _DIRECTIONAL:
            return cd == ad
        # non-directional active (observation): agreement = matching thesis_type
        return map_thesis_type(cf["direction"], cf["phase"], cf["opportunity"]) == a["thesis_type"]

    def _advance_agreeing(self, a: dict, cf: dict, ts: str) -> dict:
        a["age_scans"] += 1
        a["last_updated_at"] = ts
        a["_contrary_count"] = 0
        a["_no_playbook_count"] = 0
        # tool may rotate freely within a held direction/playbook (easiest to change)
        if cf["tool_family"]:
            a["tool_family"] = cf["tool_family"]
        if cf["invalidation_level"] is not None:
            a["invalidation_level"] = cf["invalidation_level"]

        prev_conf = a["confidence"]
        # confidence eases toward the candidate (smoothed, no instant jumps)
        step = _decay_step()
        target = cf["confidence"]
        if target > prev_conf:
            a["confidence"] = min(prev_conf + step, target)
            action = ACT_STRENGTHEN
        elif target < prev_conf:
            a["confidence"] = max(prev_conf - step, target)
            action = ACT_CONTINUE
        else:
            action = ACT_CONTINUE
        a["confidence_history"].append(a["confidence"])
        if cf["reasoning"]:
            a["supporting_evidence"] = (a["supporting_evidence"] + [cf["reasoning"]])[-10:]

        # status progression
        a["status"] = self._progress_status(a, cf)
        # playbook lifecycle runs AFTER the thesis status is known so an EXECUTABLE
        # thesis can carry an EXECUTABLE playbook. Direction agreed; the playbook
        # persists unless its own evidence says otherwise.
        self._advance_playbook(a, cf, opposing=False)
        if a["status"] == STATUS_EXECUTABLE and prev_conf and action == ACT_CONTINUE:
            action = ACT_PROMOTE_TO_EXECUTABLE
        elif self._just_promoted(a, cf):
            action = ACT_PROMOTE_TO_EXECUTABLE

        a["last_update_reason"] = f"candidate agrees ({cf['direction']}); conf {prev_conf}->{a['confidence']}"
        return self._emit(action, ts)

    def _advance_contrary(self, a: dict, cf: dict, ts: str, snap_id: str) -> dict:
        a["age_scans"] += 1
        a["last_updated_at"] = ts
        opposing = cf["direction"] in _DIRECTIONAL and a["direction"] in _DIRECTIONAL \
            and cf["direction"] != a["direction"]
        no_playbook = (not cf["opportunity"]) or (cf["playbook_family"] in (None, "", "no_playbook"))

        a["_contrary_count"] = int(a.get("_contrary_count", 0)) + 1
        if no_playbook:
            a["_no_playbook_count"] = int(a.get("_no_playbook_count", 0)) + 1

        # decay confidence (gradual, never instant 0 unless invalidation)
        a["confidence"] = max(0, a["confidence"] - _decay_step())
        a["confidence_history"].append(a["confidence"])
        note = ("opposing " + cf["direction"]) if opposing else "no_playbook/neutral"
        a["weakening_evidence"] = (a["weakening_evidence"] + [note])[-10:]
        if opposing and cf["contradictions"]:
            a["contradiction_evidence"] = (a["contradiction_evidence"] + list(cf["contradictions"]))[-10:]

        young = a["age_scans"] <= _min_age()
        enough = a["_contrary_count"] >= _consecutive_required()

        # invalidate only after enough consecutive contrary scans AND past min age,
        # OR confidence fully decayed. A single contrary scan never kills.
        if (enough and not young) or a["confidence"] <= 0:
            a["status"] = STATUS_INVALIDATED
            a["invalidated_reason"] = (
                f"{a['_contrary_count']} consecutive contrary scans"
                if a["confidence"] > 0 else "confidence decayed to zero")
            a["last_update_reason"] = f"invalidated: {a['invalidated_reason']}"
            out = self._emit(ACT_INVALIDATE, ts)
            return self._retire_and_maybe_replace(cf, ts, snap_id, base=out)

        # survive: weaken (non-opposing) or threaten (opposing directional)
        a["status"] = STATUS_THREATENED if opposing else STATUS_WEAKENING
        action = ACT_THREATEN if opposing else ACT_WEAKEN
        # The playbook is held while the thesis survives. An opposing-direction
        # scan never rotates the playbook to the opposing side; it only threatens
        # the held playbook (treated as no actionable signal for THIS thesis).
        self._advance_playbook(a, cf, opposing=opposing)
        a["last_update_reason"] = (
            f"{note}; contrary {a['_contrary_count']}/{_consecutive_required()} "
            f"(age {a['age_scans']}, min {_min_age()}); conf {a['confidence']}")
        return self._emit(action, ts)

    # ── helpers ───────────────────────────────────────────────────────────────
    def _hard_invalidation(self, a: dict, cf: dict, evidence: dict) -> "str | None":
        # invalidation_level breach using current price
        level = a.get("invalidation_level")
        price = evidence.get("current_price")
        if level is not None and price is not None:
            try:
                level_f, price_f = float(level), float(price)
                if a["direction"] == "bullish" and price_f < level_f:
                    return f"price {price_f} broke bullish invalidation {level_f}"
                if a["direction"] == "bearish" and price_f > level_f:
                    return f"price {price_f} broke bearish invalidation {level_f}"
            except (TypeError, ValueError):
                pass
        # protected level broken with acceptance, opposing side
        if a["direction"] == "bullish" and evidence.get("protected_low_status") == "violating":
            return "protected low broken (bullish thesis)"
        if a["direction"] == "bearish" and evidence.get("protected_high_status") == "violating":
            return "protected high broken (bearish thesis)"
        # external forced stand-down
        if evidence.get("news_standdown"):
            return "news forced stand-down"
        if evidence.get("risk_hard_block"):
            return "risk governor hard block"
        return None

    def _progress_status(self, a: dict, cf: dict) -> str:
        if not _is_trade_type(a["thesis_type"]):
            return STATUS_ACTIVE if a["age_scans"] >= _min_age() else STATUS_DEVELOPING
        if (cf["opportunity"] and a["confidence"] >= _exec_confidence()
                and a["age_scans"] >= _min_age() and cf["direction"] in _DIRECTIONAL):
            return STATUS_EXECUTABLE
        if a["confidence"] >= 55 and a["age_scans"] >= _min_age():
            return STATUS_ACTIVE
        if a["age_scans"] >= 2:
            return STATUS_DEVELOPING
        return STATUS_FORMING

    def _just_promoted(self, a: dict, cf: dict) -> bool:
        return (a["status"] == STATUS_EXECUTABLE
                and len(a["confidence_history"]) >= 2)

    # ── AB-7.2 — playbook lifecycle ─────────────────────────────────────────────
    def _advance_playbook(self, a: dict, cf: dict, opposing: bool = False) -> None:
        """Advance the playbook's own lifecycle for one scan. The playbook is
        persisted WITH the thesis: a single no_playbook scan never kills it
        (Rule 1); it weakens/threatens first and only retires on repeated absence
        or a sustained opposing playbook (Rule 3). Mutates `a` in place.

        Hardness ordering: a playbook rotates only after
        PLAYBOOK_SWITCH_CONSECUTIVE sustained scans of a different family, so it
        is harder to change than the tool (which rotates every scan) and easier
        than the direction (which also needs min-age + a confidence floor)."""
        # An opposing-direction scan carries no actionable playbook for THIS
        # thesis; treat it as absence so it threatens but never rotates.
        incoming = None if opposing else _norm_playbook(cf.get("playbook_family"))
        cur = a.get("playbook_family")

        # ── No playbook signal this scan ───────────────────────────────────────
        if incoming is None:
            a["_pending_playbook"] = None
            a["_pending_playbook_count"] = 0
            if not cur:
                return  # nothing to hold
            a["_playbook_absent_count"] = int(a.get("_playbook_absent_count", 0)) + 1
            if a["_playbook_absent_count"] >= _playbook_absent_invalidation():
                # repeated absence is evidence — retire the playbook (Rule 3)
                a["playbook_family"]    = None
                a["playbook_status"]    = STATUS_INVALIDATED
                a["playbook_age_scans"] = 0
            else:
                a["playbook_status"] = STATUS_THREATENED if opposing else STATUS_WEAKENING
            return

        # ── Same playbook as the active one: strengthen / age ─────────────────
        if cur and incoming == cur:
            a["_playbook_absent_count"]   = 0
            a["_pending_playbook"]        = None
            a["_pending_playbook_count"]  = 0
            a["playbook_age_scans"]       = int(a.get("playbook_age_scans", 0)) + 1
            a["playbook_status"]          = self._progress_playbook_status(a)
            return

        # ── A different, real playbook ─────────────────────────────────────────
        if cur:
            # opposing playbook evidence — confirm before rotating (Rule 3)
            a["_playbook_absent_count"] = 0
            if a.get("_pending_playbook") == incoming:
                a["_pending_playbook_count"] = int(a.get("_pending_playbook_count", 0)) + 1
            else:
                a["_pending_playbook"]       = incoming
                a["_pending_playbook_count"] = 1
            if a["_pending_playbook_count"] >= _playbook_switch_consecutive():
                a["playbook_family"]         = incoming   # rotate (old retired -> new forming)
                a["playbook_age_scans"]      = 1
                a["playbook_status"]         = STATUS_FORMING
                a["_pending_playbook"]       = None
                a["_pending_playbook_count"] = 0
            else:
                a["playbook_status"] = STATUS_THREATENED
            return

        # ── No active playbook yet: adopt immediately ─────────────────────────
        a["playbook_family"]        = incoming
        a["playbook_age_scans"]     = 1
        a["playbook_status"]        = STATUS_FORMING
        a["_playbook_absent_count"] = 0

    def _progress_playbook_status(self, a: dict) -> str:
        age = int(a.get("playbook_age_scans", 0))
        # the playbook can only be EXECUTABLE while the thesis itself is
        if a.get("status") == STATUS_EXECUTABLE and age >= 2:
            return STATUS_EXECUTABLE
        if age >= _min_age():
            return STATUS_ACTIVE
        return STATUS_FORMING

    def _confidence_trend(self, a: dict) -> str:
        h = a.get("confidence_history") or []
        if len(h) < 2:
            return "flat"
        if h[-1] > h[-2]:
            return "rising"
        if h[-1] < h[-2]:
            return "falling"
        return "flat"

    def _retire_and_maybe_replace(self, cf: dict, ts: str, snap_id: str,
                                  base: dict = None) -> dict:
        """Archive the invalidated/expired thesis; seed a replacement from the
        current candidate only if it carries directional state."""
        retired = self._active
        self._journal(base["action"] if base else ACT_INVALIDATE, retired, ts)
        if cf["direction"] in _DIRECTIONAL or cf["opportunity"]:
            self._active = _new_thesis(cf, ts, snap_id, "replace_after_invalidation")
            self._active["replacement_allowed"] = True
            out = self._emit(ACT_REPLACE_AFTER_INVALIDATION, ts)
            return out
        self._active = None
        self._save()
        return base or {"enabled": True, "mode": _mode(), "action": ACT_INVALIDATE,
                        "active_thesis": None}

    def _emit(self, action: str, ts: str) -> dict:
        a = self._active
        if a is not None:
            self._save()
            self._journal(action, a, ts)
        return {
            "enabled":        True,
            "mode":           _mode(),
            "action":         action,
            "active_thesis":  dict(a) if a else None,
            "status":         a.get("status") if a else None,
            "thesis_id":      a.get("thesis_id") if a else None,
            "direction":      a.get("direction") if a else None,
            "thesis_type":    a.get("thesis_type") if a else None,
            "confidence":     a.get("confidence") if a else None,
            "age_scans":      a.get("age_scans") if a else None,
            "is_trade_thesis": _is_trade_type(a["thesis_type"]) if a else False,
            # AB-7.2 — playbook lifecycle + confidence trend (for R1 / qualification)
            "playbook_family":    a.get("playbook_family") if a else None,
            "playbook_status":    a.get("playbook_status") if a else None,
            "playbook_age_scans": a.get("playbook_age_scans") if a else None,
            "confidence_trend":   self._confidence_trend(a) if a else None,
        }

    def as_brain_thesis(self) -> "dict | None":
        """Render the active thesis in produce_thesis() shape so enforce mode can
        overwrite snapshot['brain_thesis']. Returns None when no executable/active
        directional thesis is held."""
        a = self._active
        if a is None or a["status"] in (STATUS_INVALIDATED, STATUS_EXPIRED, STATUS_COMPLETED):
            return None
        directional = a["direction"] in _DIRECTIONAL
        return {
            "owner":             "ai_brain",
            "source":            "ab7_active_thesis",
            "direction":         a["direction"],
            "forbidden_direction": a.get("forbidden_direction"),
            "opportunity":       bool(directional and _is_trade_type(a["thesis_type"])),
            "opportunity_type":  a["thesis_type"],
            "playbook_family":   a.get("playbook_family"),
            "tool_family":       a.get("tool_family"),
            "confidence":        a.get("confidence", 0),
            "dominant_reasoning": a.get("last_update_reason", ""),
            "thesis_id":         a.get("thesis_id"),
            "thesis_status":     a.get("status"),
            "thesis_age_scans":  a.get("age_scans"),
            # AB-7.2 — the playbook now persists with the thesis; qualification in
            # enforce mode consumes the stabilized playbook + its lifecycle state.
            "playbook_status":    a.get("playbook_status"),
            "playbook_age_scans": a.get("playbook_age_scans"),
            "confidence_trend":   self._confidence_trend(a),
            # ENTRY-INVARIANT (2026-07-13) — project the INHERITED invalidation
            # (kept across scans at update time, retired on breach) so the
            # entry-eligibility check sees what the active thesis actually
            # holds. Audit: this field existed internally since AB-7 but was
            # dropped from the served projection.
            "invalidation_level": a.get("invalidation_level"),
        }


# ── Evidence extraction (live snapshot) ───────────────────────────────────────

def extract_evidence(snapshot: dict, candidate: dict) -> dict:
    """Pull the invalidation/material-change evidence available at the ECU insertion
    point. Defensive: missing data simply never triggers a hard invalidation."""
    ev = {"snapshot_id": snapshot.get("timestamp")}
    try:
        # current price from the most granular available last candle
        tfs = snapshot.get("timeframes", {}) or {}
        for tf in ("1m", "3m", "5m", "15m"):
            lc = (tfs.get(tf, {}) or {}).get("last_candle")
            if lc and lc.get("close") is not None:
                ev["current_price"] = float(lc["close"])
                break
        ps = snapshot.get("protected_swings", {}) or {}
        ev["protected_high_status"] = ps.get("protected_high_status")
        ev["protected_low_status"] = ps.get("protected_low_status")
        nc = snapshot.get("news_context")
        if isinstance(nc, dict):
            ev["news_standdown"] = bool(nc.get("forced_stand_down") or nc.get("stand_down"))
        risk = snapshot.get("risk", {}) or {}
        ev["risk_hard_block"] = (risk.get("risk_tier") in ("blocked",)) and not risk.get("trade_allowed", True)
    except Exception:  # noqa: BLE001
        pass
    return ev


# ── AB-7.3a — read-only thesis state projection ───────────────────────────────

def thesis_state(lifecycle: "dict | None") -> dict:
    """AB-7.3a — a read-only, mode-independent view of the persistent thesis for
    downstream consumers (qualification, readiness, execution gate).

    Pure projection of the lifecycle block produced by ThesisLifecycleEngine.update.
    Consumers MAY read this; they MUST NOT mutate it and it carries NO authority of
    its own — it only exposes the stabilized state so the validators can stop
    flickering. `present` is False whenever there is no live, non-terminal thesis,
    so a consumer that ignores it sees exactly the legacy (pre-AB-7.3) behavior."""
    lc = lifecycle or {}
    at = lc.get("active_thesis") or {}

    def _pick(key):
        v = lc.get(key)
        return at.get(key) if v is None else v

    status  = _pick("status")
    enabled = bool(lc.get("enabled"))
    present = bool(enabled and status not in
                   (None, STATUS_INVALIDATED, STATUS_EXPIRED, STATUS_COMPLETED))
    return {
        "present":            present,
        "enabled":            enabled,
        "thesis_status":      status,
        "thesis_age_scans":   int(_pick("age_scans") or 0),
        "thesis_confidence":  int(_pick("confidence") or 0),
        "confidence_trend":   lc.get("confidence_trend") or "flat",
        "direction":          _pick("direction"),
        "is_trade_thesis":    bool(lc.get("is_trade_thesis")),
        "playbook_status":    _pick("playbook_status"),
        "playbook_age_scans": int(_pick("playbook_age_scans") or 0),
        "playbook_family":    _pick("playbook_family"),
    }
