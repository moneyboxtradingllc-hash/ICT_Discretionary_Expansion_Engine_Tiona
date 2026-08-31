"""
Phase NA-1 — Protected Swing Intelligence.

June 11 gap: the 10:00 buy-side raid created a protected high and the
~11:00 sell-side raid created a protected low, and no subsystem modeled
either. The structure engine counted the raid wick as a higher high
(bullish strength); the liquidity engine detected the sweep but forgot it
one scan later. Protected levels are the system's first persistent
liquidity memory.

Definitions (ICT semantics, same primitives as liquidity_engine):
  PROTECTED HIGH — a swing high swept from below (above_high) whose raid
    was rejected (reclaim: close back below). Buy stops there are spent;
    the high is defended until price CLOSES back above it.
  PROTECTED LOW — mirror image (below_low sweep + reclaim), defended until
    price closes back below it.

The tracker is stateful across scans (like SetupTracker): a protected
level persists until violated, not until the next scan forgets the sweep.

Never raises. State degrades safely on missing data.
"""
import os

# MTF-RESTORATION (2026-08-11). Was ("15m", "5m") -- 1m and 3m could never
# register protected structure at all. On 2026-08-10 that discarded 90 of 140
# sweep+reclaim events, and they came from exactly the two timeframes the
# doctrine assigns to transition and execution.
_REGISTER_TFS = ("15m", "5m", "3m", "1m")

#: What each timeframe MEANS. Registering all four is not the same as treating
#: them alike: a 1m protected high is execution-local evidence, a 15m one is
#: context. They are published side by side, never flattened into each other
#: and never ranked by distance.
TIMEFRAME_ROLES = {"15m": "context", "5m": "active_leg",
                   "3m": "transition", "1m": "execution"}
#: Context first, execution last. Ordering only -- NOT precedence.
TIMEFRAME_ORDER = ("15m", "5m", "3m", "1m")


def timeframe_role(tf: str) -> str:
    return TIMEFRAME_ROLES.get(str(tf), "unknown")


def _violation_buffer_pct() -> float:
    try:
        return float(os.getenv("NARRATIVE_PROTECTED_BUFFER_PCT", "0.05")) / 100.0
    except (TypeError, ValueError):
        return 0.0005


def _current_price(snapshot: dict) -> "float | None":
    tfs = snapshot.get("timeframes", {}) or {}
    for tf in ("1m", "3m", "5m", "15m"):
        lc = (tfs.get(tf) or {}).get("last_candle")
        if lc and lc.get("close") is not None:
            try:
                return float(lc["close"])
            except (TypeError, ValueError):
                pass
    ez = (snapshot.get("trade_intent", {}) or {}).get("entry_zone") or {}
    cp = ez.get("current_price")
    try:
        return float(cp) if cp is not None else None
    except (TypeError, ValueError):
        return None


class ProtectedSwingTracker:
    """Tracks the active protected high/low across scans."""

    def __init__(self):
        # PER-TIMEFRAME state. The old single slot kept only the most EXTREME
        # level across timeframes, so a 15m high suppressed a live 5m one and
        # ratcheted away from price until violated -- the mechanism behind
        # 53/53 bearish invalidations arriving from the 15m at a median 88.75
        # points, against a 40-point execution ceiling.
        self.protected_highs = {}    # tf -> {"level","timeframe","registered_at",...}
        self.protected_lows = {}

    # ── backward-compatible summary ──────────────────────────────────────────
    # Consumers across brain_input, outcome assembly and memory read these two
    # names. They remain the CONTEXT synthesis -- the most extreme registered
    # level -- while the per-timeframe truth lives beside them and is what the
    # invalidation catalog now publishes.
    @property
    def protected_high(self):
        vals = [v for v in self.protected_highs.values() if v]
        return max(vals, key=lambda r: r["level"]) if vals else None

    @property
    def protected_low(self):
        vals = [v for v in self.protected_lows.values() if v]
        return min(vals, key=lambda r: r["level"]) if vals else None

    @staticmethod
    def _register(existing, *, tf, side, level, ts, basis) -> dict:
        """One protected-swing life gets ONE birthday.

        PROTECTED-SWING-CAUSAL-TIME-1. This used to be a blind whole-record
        assignment, so the four lifecycle states collapsed into two: a fresh
        raid rejection at a level ALREADY held re-stamped `registered_at` to
        now, even though nothing had died.

        THAT IS THE OPPOSITE OF WHAT THE ORGANISM PROMISES. `brain_prompt` tells
        the Brain that `registered_at` is "WHEN the raid was rejected and the
        level was born", that a still-listed level "has not been violated since
        `registered_at`", and instructs it to "compare `registered_at` against
        the current timestamp and say how long the level has survived". The
        tracker was resetting exactly that clock. Measured on the archived live
        payloads, the 2026-08-24 3m protected low at 29171.5 was delivered on
        four consecutive scans with `registered_at` equal to the scan each time,
        while the level had in fact been defended since 12:41 -- so the survival
        duration the Brain was asked to compute was always zero. Across that
        session 24 of 33 lives were re-stamped, one of them 18 times.

        The direction of the error is what makes it costly: a re-affirmation is
        a SECOND raid rejected at the same level, which is STRENGTHENING
        evidence. It made the level look YOUNGER. The best-defended levels read
        as the most newly minted.

        FOUR STATES, NOW DISTINGUISHED:

            FORMATION       slot empty -> new life, `registered_at` assigned once
            RE-AFFIRMATION  same live swing -> formation provenance PRESERVED
            REPLACEMENT     a different level takes the slot -> new life
            VIOLATION       handled below by `pop`; the life ends

        SAMENESS IS ASKED OF THE EXISTING PRIMITIVE, not of raw floats.
        `swing_id` already encodes timeframe, side and the canonically rounded
        level, and it is the repository's own answer to "is this the same
        protected level?". Comparing `level == level` here would have invented a
        second price-identity law next to the one the record already carries.

        `swing_id` REMAINS NON-UNIQUE ACROSS LIVES, deliberately. It is only
        consulted for a slot that is CURRENTLY OCCUPIED, so it can never merge a
        level with a dead predecessor at the same price: a violation empties the
        slot, and the next registration therefore sees `existing is None` and
        mints a new birthday. Two lives of one price stay two lives.

        Every other field is identity or a per-side constant -- see the field
        audit in the unit's tests -- so `registered_at` is the only thing a
        re-affirmation could have moved, and the only thing preserved here.
        """
        record = {
            "level":         round(level, 4),
            "timeframe":     tf,
            "role":          timeframe_role(tf),
            "registered_at": ts,
            "swing_id":      f"{tf}:swing_{side}:{round(level, 4):g}",
            "basis":         basis,
        }
        if existing and existing.get("swing_id") == record["swing_id"]:
            # RE-AFFIRMATION of a life that never died. Newer evidence for the
            # same level is not a new level.
            born = existing.get("registered_at")
            if born:
                record["registered_at"] = born
        return record

    def update(self, snapshot: dict) -> dict:
        """
        Register new protected levels from this scan's sweep evidence and
        clear violated ones. Returns the current state dict. Never raises.
        """
        try:
            return self._update(snapshot or {})
        except Exception as exc:  # noqa: BLE001
            return self.state(warnings=[f"protected swing tracker error: {exc}"])

    def _update(self, snapshot: dict) -> dict:
        liquidity = snapshot.get("liquidity", {}) or {}
        structure = snapshot.get("structure", {}) or {}
        ts        = snapshot.get("timestamp", "")
        price     = _current_price(snapshot)

        # ── Registration: sweep + reclaim, PER TIMEFRAME ────────────────────
        # Each timeframe owns its own slot. A 15m registration no longer
        # suppresses a live 5m/3m/1m one, and nothing ratchets toward the
        # extreme -- the newest registration on a timeframe replaces that
        # timeframe's own prior level, and only that one.
        for tf in _REGISTER_TFS:
            liq = liquidity.get(tf, {}) or {}
            if not (liq.get("sweep_detected") and liq.get("reclaim_detected")):
                continue
            st    = structure.get(tf, {}) or {}
            sweep = liq.get("sweep_direction", "")
            if sweep == "above_high" and st.get("last_swing_high") is not None:
                self.protected_highs[tf] = self._register(
                    self.protected_highs.get(tf), tf=tf, side="high",
                    level=float(st["last_swing_high"]), ts=ts,
                    basis="buy_side_raid_rejected")
            elif sweep == "below_low" and st.get("last_swing_low") is not None:
                self.protected_lows[tf] = self._register(
                    self.protected_lows.get(tf), tf=tf, side="low",
                    level=float(st["last_swing_low"]), ts=ts,
                    basis="sell_side_raid_rejected")

        # ── Violation: a close beyond the level clears THAT timeframe only ───
        if price is not None:
            buf = price * _violation_buffer_pct()
            for tf, rec in list(self.protected_highs.items()):
                if rec and price > rec["level"] + buf:
                    self.protected_highs.pop(tf, None)
            for tf, rec in list(self.protected_lows.items()):
                if rec and price < rec["level"] - buf:
                    self.protected_lows.pop(tf, None)

        return self.state()

    def state(self, warnings: "list | None" = None) -> dict:
        """Summary AND per-timeframe truth, side by side.

        `protected_high` / `protected_low` keep their historical meaning (the
        most extreme registered level) so every existing consumer is unchanged.
        `by_timeframe` is what the invalidation catalog reads: four separate
        structural facts that no longer erase one another.
        """
        return {
            "protected_high": dict(self.protected_high) if self.protected_high else None,
            "protected_low":  dict(self.protected_low) if self.protected_low else None,
            "by_timeframe": {
                "highs": {tf: dict(r) for tf, r in self.protected_highs.items() if r},
                "lows":  {tf: dict(r) for tf, r in self.protected_lows.items() if r},
            },
            "roles": dict(TIMEFRAME_ROLES),
            "warnings":       warnings or [],
        }
