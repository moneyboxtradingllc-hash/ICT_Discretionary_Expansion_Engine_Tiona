"""
Phase 1R — Setup Lifecycle Tracker.
Tracks active trade setups as living objects across consecutive scan snapshots.
Pure observation only. No execution. No orders. No broker actions.
"""
from __future__ import annotations

import os

_QUAL_ORDER = {
    "elite": 4, "qualified": 3, "candidate": 2,
    "watchlist": 1, "no_trade": 0, "decay": -1, "invalidated": -2,
}

# SETUP-PERSIST (2026-07-08) — transient-flicker grace window.
# The 2026-07-08 lifecycle assassination proved the primary setup killer:
# "Playbook dropped to no_playbook" (15 of 20 invalidation deaths) fired on a
# SINGLE scan of no_playbook, while qualification flickered to no_trade on
# 123/163 scans (75%) — so setups died at age 1 (71%), avg lifespan 1.45 scans,
# never surviving a confirmation window. This grace lets a setup remain DORMANT
# (age/lifecycle preserved, but NOT traded — the scan is still no_trade) for a
# bounded number of consecutive no_playbook scans before it is killed, so a
# transient qualification dip no longer destroys and resets the setup. Genuine
# invalidations (state-transition, entry-trigger invalidated, toxic risk, or
# SUSTAINED no_playbook past the window) still kill immediately. Default 0 =
# legacy immediate-kill (byte-identical). Rollback = SETUP_NO_PLAYBOOK_GRACE=0.
_NO_PLAYBOOK_REASON = "Playbook dropped to no_playbook"


def _no_playbook_grace() -> int:
    try:
        return max(0, int(os.getenv("SETUP_NO_PLAYBOOK_GRACE", "0")))
    except ValueError:
        return 0

# Path arrays are capped so memory stays bounded during long sessions.
_PATH_CAP = 20

# Risk tiers that force setup invalidation regardless of qualification state.
_TOXIC_RISK_TIERS = {"dangerous", "conflicted", "toxic"}


# ── Snapshot field extractors ────────────────────────────────────────────────

def _playbook(snap: dict) -> str:
    return (snap.get("playbook", {}).get("selected_playbook") or "no_playbook").lower()


def _direction(snap: dict) -> str:
    return (snap.get("playbook", {}).get("direction") or "neutral").lower()


def _preferred_tool(snap: dict) -> str | None:
    return snap.get("toolbox", {}).get("preferred_tool") or None


def _tool_family(tool: str | None) -> str:
    if not tool:
        return "none"
    for prefix in ("bullish_", "bearish_"):
        if tool.startswith(prefix):
            return tool[len(prefix):]
    return tool


def _tool_status(snap: dict) -> str:
    return (snap.get("toolbox", {}).get("best_available_effective_status") or "no_tool").lower()


def _qual_status(snap: dict) -> str:
    return (snap.get("qualification", {}).get("status") or "no_trade").lower()


def _qual_rank(status: str) -> int:
    return _QUAL_ORDER.get(status.lower(), 0)


def _ai_confidence(snap: dict) -> int:
    return snap.get("ai_context", {}).get("confidence_score") or 0


def _mechanical_score(snap: dict) -> int:
    return snap.get("qualification", {}).get("opportunity_score") or 0


def _risk_tier(snap: dict) -> str:
    return (snap.get("risk", {}).get("risk_tier") or "blocked").lower()


def _trade_allowed(snap: dict) -> bool:
    return bool(snap.get("risk", {}).get("trade_allowed", False))


def _transition_type(snap: dict) -> str:
    return (snap.get("state_transition", {}).get("transition_type") or "stable").lower()


def _lifecycle_phase(snap: dict) -> str:
    return (snap.get("state_transition", {}).get("setup_lifecycle") or "dormant").lower()


def _trigger_status(snap: dict) -> str:
    tb = snap.get("toolbox", {})
    preferred = tb.get("preferred_tool")
    candidates = tb.get("tool_candidates", [])
    if preferred:
        pref_c = next((c for c in candidates if c.get("tool") == preferred), {})
        tp = pref_c.get("trigger_prep", {})
        return (tp.get("effective_trigger_status") or "n/a").lower()
    return "n/a"


def _zone_info(snap: dict) -> tuple[float | None, float | None]:
    """Returns (zone_low, zone_high) from the preferred tool's price_level."""
    tb = snap.get("toolbox", {})
    preferred = tb.get("preferred_tool")
    candidates = tb.get("tool_candidates", [])
    if not preferred:
        return None, None
    pref_c = next((c for c in candidates if c.get("tool") == preferred), {})
    pl = pref_c.get("price_level", {})
    if not pl:
        return None, None
    z_lo = pl.get("zone_low") or pl.get("level")
    z_hi = pl.get("zone_high") or pl.get("level") or z_lo
    try:
        return float(z_lo), float(z_hi)
    except (TypeError, ValueError):
        return None, None


# ── Identity builders ────────────────────────────────────────────────────────

def _make_setup_id(symbol: str, snap: dict) -> str | None:
    """Full setup identifier including zone when available."""
    pb   = _playbook(snap)
    d    = _direction(snap)
    tool = _preferred_tool(snap)
    if pb == "no_playbook" or not tool:
        return None
    date_str = (snap.get("timestamp") or "")[:10].replace("-", "")
    z_lo, z_hi = _zone_info(snap)
    zone_str = ""
    if z_lo is not None and z_hi is not None:
        zone_str = f"_{int(z_lo * 100)}_{int(z_hi * 100)}"
    return f"{symbol}_{date_str}_{pb}_{d}_{tool}{zone_str}"


def _make_setup_key(snap: dict) -> str | None:
    """Minimal identity for same-setup detection — ignores zone drift."""
    pb   = _playbook(snap)
    d    = _direction(snap)
    tool = _preferred_tool(snap)
    if pb == "no_playbook" or not tool:
        return None
    return f"{pb}_{d}_{_tool_family(tool)}"


# ── Phase determination ───────────────────────────────────────────────────────

def _determine_phase(snap: dict, age_scans: int, transition_path: list[str]) -> str:
    lifecycle  = _lifecycle_phase(snap)
    trans_type = _transition_type(snap)
    qual       = _qual_status(snap)

    if lifecycle == "invalidated" or trans_type == "invalidation":
        return "invalidated"
    if lifecycle == "actionable_candidate":
        return "actionable"
    if lifecycle == "blocked_by_risk":
        return "blocked"

    if age_scans == 1:
        return "born"

    # Decay: two or more decline signals in recent history
    recent       = transition_path[-3:]
    decay_count  = sum(1 for t in recent if t in ("downgrade", "decay", "invalidation"))
    if decay_count >= 2 or trans_type == "decay":
        return "decaying"

    if trans_type == "upgrade":
        return "maturing"

    if qual in ("candidate", "qualified", "elite"):
        return "forming"
    if qual == "watchlist":
        return "forming"

    return "forming"


# ── Invalidation check ────────────────────────────────────────────────────────

def _check_invalidation(snap: dict, has_active: bool) -> str | None:
    """Returns a reason string if the active setup should be invalidated, else None."""
    if snap.get("state_transition", {}).get("invalidated"):
        return "State transition flagged invalidated"

    if _trigger_status(snap) == "invalidated":
        return "Entry trigger invalidated"

    if has_active and _playbook(snap) == "no_playbook":
        return "Playbook dropped to no_playbook"

    tier = _risk_tier(snap)
    if tier in _TOXIC_RISK_TIERS:
        return f"Risk tier became {tier}"

    return None


# ── Path helper ───────────────────────────────────────────────────────────────

def _append(path: list, value) -> list:
    path.append(value)
    return path[-_PATH_CAP:]


# ── SetupTracker ──────────────────────────────────────────────────────────────

class SetupTracker:
    """
    Tracks the active trade setup across consecutive scan snapshots.
    Instantiate once before the scan loop; call update() each iteration.
    No execution. Observation only.
    """

    def __init__(self):
        self._active:    dict | None = None
        self._setup_key: str | None  = None
        self._dormant:   int         = 0   # SETUP-PERSIST — consecutive dormant scans

    def update(self, snapshot: dict, symbol: str) -> dict:
        """
        Process the latest snapshot and return the current setup_lifecycle dict.
        Must be called AFTER state_transition has been injected into snapshot.
        """
        # ── Check if active setup should be invalidated ────────────────────
        if self._active is not None and not self._active["invalidated"]:
            reason = _check_invalidation(snapshot, has_active=True)
            if reason:
                # SETUP-PERSIST — a TRANSIENT no_playbook (qualification flicker)
                # does not kill: the setup goes dormant (age/lifecycle preserved,
                # NOT tradeable this scan) for up to the grace window, then dies
                # if no_playbook persists. All other invalidation reasons, and a
                # sustained no_playbook past the window, kill immediately.
                grace = _no_playbook_grace()
                if (reason == _NO_PLAYBOOK_REASON and grace > 0
                        and self._dormant < grace):
                    self._dormant += 1
                    self._active["current_phase"] = "dormant"
                    self._active["last_seen_at"]  = snapshot.get("timestamp", "")
                    self._active["reason"] = (
                        f"Transient no_playbook — setup preserved "
                        f"(dormant {self._dormant}/{grace})")
                    out = self._build_output()
                    out["dormant"]       = True
                    out["dormant_scans"] = self._dormant
                    return out
                self._active["invalidated"]   = True
                self._active["reason"]        = reason
                self._active["current_phase"] = "invalidated"
                self._active["last_seen_at"]  = snapshot.get("timestamp", "")
                out = self._build_output()
                self._active    = None
                self._setup_key = None
                self._dormant   = 0
                return out

        # ── Determine identity for this scan ──────────────────────────────
        new_key = _make_setup_key(snapshot)
        new_id  = _make_setup_id(symbol, snapshot)

        if new_key is None:
            # No trackable playbook/tool this scan — return null, preserve active
            # (tool may momentarily disappear due to market data gap; don't reset)
            if self._active is None:
                return _null_output()
            # If playbook is gone and we still have an active setup, it was already
            # caught by _check_invalidation above. So just return null here.
            return _null_output()

        # ── Same setup or new setup? ───────────────────────────────────────
        if self._active is None or new_key != self._setup_key:
            self._start_new(symbol, snapshot, new_id, new_key)
        else:
            self._update_existing(snapshot, new_id)

        return self._build_output()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _start_new(self, symbol: str, snap: dict, setup_id: str, setup_key: str):
        ts   = snap.get("timestamp", "")
        qual = _qual_status(snap)
        self._setup_key = setup_key
        self._dormant   = 0   # SETUP-PERSIST — fresh setup, no dormancy
        self._active = {
            "setup_id":               setup_id,
            "symbol":                 symbol,
            "playbook":               _playbook(snap),
            "direction":              _direction(snap),
            "preferred_tool":         _preferred_tool(snap),
            "started_at":             ts,
            "last_seen_at":           ts,
            "age_scans":              1,
            "current_phase":          "born",
            "highest_quality_reached": qual,
            "current_quality":        qual,
            "quality_path":           [qual],
            "transition_path":        [_transition_type(snap)],
            "tool_path":              [_tool_status(snap)],
            "risk_path":              [_risk_tier(snap)],
            "ai_confidence_path":     [_ai_confidence(snap)],
            "mechanical_score_path":  [_mechanical_score(snap)],
            "invalidated":            False,
            "completed":              False,
            "reason":                 "New setup born",
            "warnings":               [],
        }

    def _update_existing(self, snap: dict, new_id: str):
        a    = self._active
        qual = _qual_status(snap)

        # SETUP-PERSIST — the setup recovered a valid playbook this scan; clear
        # dormancy so the grace window is available again for a future dip.
        self._dormant = 0

        # Update mutable identity fields (zone may drift slightly)
        a["setup_id"]       = new_id
        a["preferred_tool"] = _preferred_tool(snap)
        a["last_seen_at"]   = snap.get("timestamp", "")
        a["age_scans"]     += 1
        a["current_quality"] = qual

        if _qual_rank(qual) > _qual_rank(a["highest_quality_reached"]):
            a["highest_quality_reached"] = qual

        trans = _transition_type(snap)
        a["quality_path"]          = _append(a["quality_path"],          qual)
        a["transition_path"]       = _append(a["transition_path"],       trans)
        a["tool_path"]             = _append(a["tool_path"],             _tool_status(snap))
        a["risk_path"]             = _append(a["risk_path"],             _risk_tier(snap))
        a["ai_confidence_path"]    = _append(a["ai_confidence_path"],    _ai_confidence(snap))
        a["mechanical_score_path"] = _append(a["mechanical_score_path"], _mechanical_score(snap))

        a["current_phase"] = _determine_phase(snap, a["age_scans"], a["transition_path"])

        if trans == "upgrade":
            a["reason"] = f"Setup upgraded to {qual}"
        elif trans == "downgrade":
            a["reason"] = f"Setup downgraded to {qual}"
        elif a["current_phase"] == "decaying":
            a["reason"] = "Setup confidence or qualification is declining"
        else:
            a["reason"] = f"Setup remains active at {qual}"

        # Surface any warnings from the state transition engine
        a["warnings"] = snap.get("state_transition", {}).get("warnings", [])[:]

    def _build_output(self) -> dict:
        a = self._active
        return {
            "active":                   True,
            "setup_id":                 a["setup_id"],
            "symbol":                   a["symbol"],
            "playbook":                 a["playbook"],
            "direction":                a["direction"],
            "preferred_tool":           a["preferred_tool"],
            "started_at":               a["started_at"],
            "last_seen_at":             a["last_seen_at"],
            "age_scans":                a["age_scans"],
            "current_phase":            a["current_phase"],
            "highest_quality_reached":  a["highest_quality_reached"],
            "current_quality":          a["current_quality"],
            "quality_path":             a["quality_path"],
            "transition_path":          a["transition_path"],
            "tool_path":                a["tool_path"],
            "risk_path":                a["risk_path"],
            "ai_confidence_path":       a["ai_confidence_path"],
            "mechanical_score_path":    a["mechanical_score_path"],
            "invalidated":              a["invalidated"],
            "completed":                a["completed"],
            "reason":                   a["reason"],
            "warnings":                 a["warnings"],
        }


def _null_output() -> dict:
    return {
        "active":   False,
        "setup_id": None,
        "reason":   "No active playbook or tool",
    }
