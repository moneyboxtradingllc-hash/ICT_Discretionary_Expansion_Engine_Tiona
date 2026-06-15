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
    return {
        "thesis_id":             f"TH_{uuid.uuid4().hex[:12]}",
        "created_at":            ts,
        "last_updated_at":       ts,
        "age_scans":             1,
        "age_minutes":           0.0,
        "direction":             cf["direction"],
        "playbook_family":       cf["playbook_family"],
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
        self._symbol = symbol or os.getenv("SCAN_SYMBOL", "QQQ")
        if persist:
            self._load()

    # ── persistence ───────────────────────────────────────────────────────────
    def _load(self) -> None:
        try:
            path = _active_path()
            if not os.path.exists(path):
                return
            data = json.load(open(path, encoding="utf-8"))
            active = data.get("active")
            if not active:
                return
            # Restart safety: only resurrect a same-symbol, non-terminal, in-age thesis.
            if active.get("symbol") and active.get("symbol") != self._symbol:
                return
            if active.get("status") in (STATUS_INVALIDATED, STATUS_EXPIRED, STATUS_COMPLETED):
                return
            cap = _max_age_scans()
            if cap and int(active.get("age_scans", 0)) > cap:
                active["status"] = STATUS_EXPIRED
                active["invalidated_reason"] = "expired on reload (max age exceeded)"
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
        cap = _max_age_scans()
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
        # tool may rotate freely within a held direction/playbook
        if cf["tool_family"]:
            a["tool_family"] = cf["tool_family"]
        if cf["playbook_family"]:
            a["playbook_family"] = cf["playbook_family"]
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
