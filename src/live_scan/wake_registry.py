"""EVENT-WAKE-ACTIONABLE-STRUCTURE-1 — tap Luna on the shoulder. Nothing more.

2026-08-21, 10:24. The bullish 1m FVG 29243.00-29251.25 completed when the 10:23
candle settled at 10:24:00, and price traded into it during that same minute
(low 29249.50). The surrounding scans were 10:23:51 -- before the gap existed --
and 10:25:11, by which point the executable ask was 29251.50, back above the
zone. By 10:26:27 it was 29279.50.

    ENTRY_TRIGGERED     YES, in the market
    DECISION_PRESENTED  NO

Everything beneath timing was already repaired: the gap is named, selectable,
verifiable, and its identity survives into the candidate. The organism simply
was not asked while price was there. The production loop slept
`time.sleep(interval)` AFTER a 19s call -- a 79s start-to-start interval against
a ~60s live entry.

    THE REGISTRY HAS ZERO EXPOSURE AUTHORITY.

Its entire authority is: "request a fresh normal production evaluation". It may
never create a candidate, select a tool, author risk, price an entry, set a stop
or choose an objective. After every wake the UNCHANGED `scan_once()` re-proves
everything from canonical snapshot, toolbox, catalog, Brain and risk -- so a
wake may lawfully end in stand_down, catalog refusal, Luna PASS or risk refusal.

    FALSE-POSITIVE WAKE IS ALLOWED. FALSE-POSITIVE AUTHORIZATION IS NOT.

That is what makes the raw detector safe here. `fvg_execution_instances` is the
CANONICAL plain-FVG constructor -- not a parallel detector -- and its eligible
set was measured to be a strict SUPERSET of what the catalog publishes (12 of 12
archived snapshots, zero violations). The later layers only ever narrow. So the
registry can over-wake and never under-wake, and it decides nothing.

THREAD OWNERSHIP, STATED EXPLICITLY:

    production main thread   SOLE WRITER of the published registry. Runs the
                             pure canonical refresh. Owns everything downstream.
    market-data pump thread  READS an immutable published snapshot and owns ONLY
                             its own ephemeral OUTSIDE/INSIDE episode state.
                             It sets events. It never calls the Brain, never
                             builds a snapshot, never runs the toolbox, never
                             touches a stateful tracker.

The lock guards ONLY the publication and reading of one tuple reference. FVG
computation, quote processing and provider work all happen outside it. The GIL
is not the synchronisation theorem here -- the lock is.
"""
from __future__ import annotations

import threading

#: A published armed occurrence. Immutable by construction: the main thread
#: swaps a whole new tuple rather than mutating entries the pump may be reading.
#: `initial_inside` is how "armed while price is ALREADY in the zone" survives
#: the thread boundary without the main thread reaching into pump-owned state.
ARMED_FIELDS = ("occurrence_id", "direction", "zone_low", "zone_high",
                "initial_inside")

INSIDE = "INSIDE"
OUTSIDE = "OUTSIDE"

#: Wake reasons, for telemetry only. They authorize nothing.
WAKE_ARMED_INSIDE = "armed_while_inside"
WAKE_ENTERED = "entered_zone"


def _num(value):
    """A real finite number, or None. Booleans are not prices."""
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if out != out or out in (float("inf"), float("-inf")) else out


def executable_for(direction: str, bid, ask):
    """The sided price a trade would ACTUALLY pay, per existing doctrine.

    Bullish pays the ASK, bearish hits the BID. A candle high/low or a last
    trade is not an executable interaction and may never substitute -- the
    2026-08-21 gap was entered on a candle low the market never offered to a
    buyer at that instant.
    """
    if str(direction or "").lower() == "bullish":
        return _num(ask)
    if str(direction or "").lower() == "bearish":
        return _num(bid)
    return None


class WakeRegistry:
    """Armed plain-FVG occurrences, watched for executable-price interaction."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._armed: tuple = ()          # published snapshot, main writes
        self._episode: dict = {}         # pump-owned OUTSIDE/INSIDE per occurrence
        #: Level-triggered. An event set while Luna is mid-flight STAYS set, so
        #: the loop runs one immediate fresh cycle when the call returns rather
        #: than losing the transition. Queuing snapshots would answer a newer
        #: question with older evidence; one bit cannot go stale.
        self.structure_birth = threading.Event()
        self.trade_wake = threading.Event()
        self.wakes: list = []            # telemetry, never authority

    # ── PUMP THREAD ─────────────────────────────────────────────────────────
    def note_bar_closed(self) -> None:
        """A completed bar MAY have created something worth watching.

        This is all the market-data thread is permitted to conclude. It does not
        refresh, does not detect, and emphatically does not call the Brain.
        """
        self.structure_birth.set()

    def armed(self) -> tuple:
        """The published snapshot. Read under the lock, evaluated outside it."""
        with self._lock:
            return self._armed

    def on_quote(self, bid=None, ask=None) -> list:
        """Detect OUTSIDE -> INSIDE transitions. Returns the wakes it raised.

        A missing or unusable sided quote is NOT an interaction: absence of a
        price is not proof price is in the zone, and waking on it would be
        waking on ignorance.
        """
        fired = []
        armed = self.armed()
        live = {row[0] for row in armed}
        # Drop episode state for occurrences that no longer exist, so a later
        # re-appearance of the same id starts honestly rather than inheriting a
        # stale INSIDE that would suppress its first wake.
        for gone in [oid for oid in self._episode if oid not in live]:
            self._episode.pop(gone, None)

        for occurrence_id, direction, low, high, initial_inside in armed:
            if occurrence_id not in self._episode:
                # First sighting: seed from what the MAIN thread observed at
                # publication, so an armed-while-inside zone does not fire a
                # second, duplicate wake on the very next quote.
                self._episode[occurrence_id] = INSIDE if initial_inside else OUTSIDE
                continue
            price = executable_for(direction, bid, ask)
            if price is None:
                continue
            now = INSIDE if low <= price <= high else OUTSIDE
            was = self._episode[occurrence_id]
            self._episode[occurrence_id] = now
            if was == OUTSIDE and now == INSIDE:
                fired.append({"occurrence_id": occurrence_id, "reason": WAKE_ENTERED,
                              "direction": direction, "price": price})
        if fired:
            self.wakes.extend(fired)
            self.trade_wake.set()
        return fired

    # ── PRODUCTION MAIN THREAD ──────────────────────────────────────────────
    @staticmethod
    def annotate(bars: list) -> dict:
        """Completed 1m bars -> annotated timeframe views, via THE ONE annotator.

        `build_timeframes` and `annotated_timeframe` are both canonical and are
        the exact composition `build_snapshot` uses. Reassembling a private
        version would create a second definition of `temporal_status`, and
        `fvg_execution_instances` filters on precisely that field.
        """
        from data_feed.timeframe_builder import build_timeframes
        from market_data.snapshot_builder import annotated_timeframe
        raw = build_timeframes(bars) or {}
        return {tf: (annotated_timeframe(raw.get(tf) or [], tf).get("recent_candles") or [])
                for tf in ("1m", "3m", "5m", "15m")}

    def refresh_from_bars(self, bars: list, contract, *, bid=None, ask=None) -> dict:
        """The production entry point: completed bars in, armed registry out."""
        try:
            by_tf = self.annotate(bars)
        except Exception as exc:  # noqa: BLE001 — watching may never kill a scan
            return {"armed": len(self.armed()), "refreshed": False,
                    "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
        return self.refresh(by_tf, contract, bid=bid, ask=ask)

    def _canonical_rows(self, candles_by_tf: dict, contract, *, bid, ask):
        """THE ONE derivation of armed rows. Pure. Shared by refresh and bootstrap.

        Both callers must agree exactly on what is armed and on what counts as
        inside; two copies of this walk would be two answers to the same
        question, which is the defect class this whole unit exists to remove.
        """
        from toolbox.price_levels import fvg_execution_instances

        rows, armed_inside = [], []
        for tf, minutes in (("1m", 1), ("3m", 3), ("5m", 5), ("15m", 15)):
            candles = (candles_by_tf or {}).get(tf) or []
            if not candles:
                continue
            for direction in ("bullish", "bearish"):
                for occ in fvg_execution_instances(candles, direction, minutes,
                                                   contract=contract):
                    oid = occ.get("occurrence_id")
                    low, high = _num(occ.get("low")), _num(occ.get("high"))
                    if not (occ.get("execution_eligible") and oid
                            and low is not None and high is not None):
                        continue
                    price = executable_for(direction, bid, ask)
                    inside = price is not None and low <= price <= high
                    rows.append((oid, direction, low, high, inside))
                    if inside:
                        armed_inside.append(oid)
        return rows, armed_inside

    def bootstrap(self, candles_by_tf: dict, contract, *, bid=None, ask=None) -> dict:
        """STARTUP ONLY. ARM AND SEED. NEVER WAKE.

        Without this the registry is empty until the first bar closes, so for up
        to a minute after a restart there is no armed occurrence and therefore no
        OUTSIDE -> INSIDE detector. A gap that already existed before the restart
        could be entered and exited inside that window with no wake -- exactly
        the timing failure this unit exists to remove, reintroduced through the
        startup door.

        SEEDING IS NOT TRIGGERING. The normal initial `scan_once()` is about to
        present the current market state to Luna anyway. If bootstrap raised a
        first-episode wake for an occurrence that is already inside, the loop
        would spend an immediate SECOND Brain call on the same unchanged state.
        So bootstrap seeds the episode at its true current value and emits
        nothing:

            startup OUTSIDE -> later INSIDE   WAKE      (the missing theorem)
            startup INSIDE  -> still INSIDE   no wake
            startup INSIDE  -> OUTSIDE        re-arm
            then    OUTSIDE -> INSIDE         WAKE

        THIS SUPPRESSION IS SCOPED TO STARTUP AND TO ALREADY-EXISTING
        OCCURRENCES. It does not touch runtime doctrine: an occurrence BORN
        during the session with price already inside it is still a first
        interaction episode and still wakes immediately. That is the 10:24
        specimen and `refresh` continues to own it -- a newly armed id is not in
        `known`, so it wakes exactly as before.

        THREAD OWNERSHIP. This is the one place the main thread writes
        `_episode`, and it is safe for a single structural reason: the caller
        bootstraps BEFORE publishing the registry to the provider, so the pump
        cannot hold a reference to it yet. After publication `_episode` is
        pump-owned again and this is never called.

        Never raises.
        """
        try:
            rows, armed_inside = self._canonical_rows(
                candles_by_tf, contract, bid=bid, ask=ask)
        except Exception as exc:  # noqa: BLE001 — startup may never be blocked
            return {"armed": len(self._armed), "bootstrapped": False,
                    "seeded_inside": [],
                    "error": f"{type(exc).__name__}: {str(exc)[:120]}"}

        with self._lock:
            self._armed = tuple(rows)
            # Seeded here rather than on the pump's first quote, so the very
            # next quote is already a TRANSITION and not a first sighting.
            self._episode = {oid: (INSIDE if inside else OUTSIDE)
                             for oid, _dir, _lo, _hi, inside in rows}
        return {"armed": len(rows), "bootstrapped": True,
                "seeded_inside": list(armed_inside), "error": None}

    def bootstrap_from_bars(self, bars: list, contract, *, bid=None, ask=None) -> dict:
        """The production startup entry point: completed bars in, armed out."""
        try:
            by_tf = self.annotate(bars)
        except Exception as exc:  # noqa: BLE001
            return {"armed": len(self.armed()), "bootstrapped": False,
                    "seeded_inside": [],
                    "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
        return self.bootstrap(by_tf, contract, bid=bid, ask=ask)

    def refresh(self, candles_by_tf: dict, contract, *, bid=None, ask=None) -> dict:
        """Re-derive armed occurrences from the CANONICAL plain-FVG constructor.

        PURE INPUTS ONLY -- completed candles and the exact contract. It does not
        call `build_snapshot`, `run_toolbox` or any stateful tracker, so it is
        safe on this thread and would be safe on any: nothing it touches is
        mutated. Never raises: a refresh failure must not cost a scan.
        """
        try:
            rows, armed_inside = self._canonical_rows(
                candles_by_tf, contract, bid=bid, ask=ask)
        except Exception as exc:  # noqa: BLE001 — watching must never kill a scan
            return {"armed": len(self._armed), "refreshed": False,
                    "error": f"{type(exc).__name__}: {str(exc)[:120]}"}

        known = {row[0] for row in self._armed}
        with self._lock:
            self._armed = tuple(rows)

        # ARMED WHILE ALREADY INSIDE IS THE FIRST EPISODE, not a state to sit in
        # waiting for an exit that may never come. This is literally the
        # 2026-08-21 specimen: the gap completed at 10:24:00 with price already
        # trading through it, and requiring a future re-entry would have missed
        # the entire window.
        first = [oid for oid in armed_inside if oid not in known]
        if first:
            self.wakes.extend({"occurrence_id": oid, "reason": WAKE_ARMED_INSIDE}
                              for oid in first)
            self.trade_wake.set()
        return {"armed": len(rows), "refreshed": True,
                "armed_while_inside": first, "error": None}

    # ── LOOP PLUMBING ───────────────────────────────────────────────────────
    def wait(self, timeout: float) -> dict:
        """Sleep until the deadline OR an event. Returns what woke us.

        Replaces an uninterruptible `time.sleep`. Both events are polled on one
        short tick because `threading.Event` cannot wait on two objects; the tick
        is a wait granularity, never a quote poll -- no market data is read here.
        """
        import time
        deadline = time.monotonic() + max(0.0, float(timeout))
        while True:
            if self.trade_wake.is_set():
                return {"woke": "interaction", "early": True}
            if self.structure_birth.is_set():
                return {"woke": "structure", "early": True}
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {"woke": "deadline", "early": False}
            time.sleep(min(0.25, remaining))

    def consume_structure(self) -> bool:
        was = self.structure_birth.is_set()
        self.structure_birth.clear()
        return was

    def consume_interaction(self) -> bool:
        was = self.trade_wake.is_set()
        self.trade_wake.clear()
        return was

    def health(self) -> dict:
        return {"armed": len(self.armed()), "episodes": len(self._episode),
                "wakes": len(self.wakes),
                "structure_pending": self.structure_birth.is_set(),
                "interaction_pending": self.trade_wake.is_set()}
