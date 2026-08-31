"""BAR-HALT-OBSERVATION-1 — record the CME halt from three sources. Zero orders.

    python tools/topstepx_halt_observer.py                 # 16:10 -> 16:35 ET today
    python tools/topstepx_halt_observer.py --start 16:10 --stop 16:35
    python tools/topstepx_halt_observer.py --dry-run       # wiring proof, no wait

CME publishes a 16:15-16:30 ET trading halt for MNQ. The canonical store holds a
bar for all fifteen of those minutes on 2026-08-17 while correctly holding none
for the 17:00-18:00 maintenance hour. This tool settles what such a bar means by
recording, over the same interval:

    GatewayTrade    real-time MARKET TRADE events
    GatewayQuote    real-time quote events
    retrieveBars    the history endpoint's own account of those minutes

and laying them beside the published calendar. Four independent propositions,
no order, no account arming, no session authorization.

STRUCTURALLY WRITE-INCAPABLE. It runs on `TopstepXReadOnlySession`, which has no
write METHODS and whose transport refuses every write PATH before a byte leaves
the process. It never builds an ExecutionRunner and never mints a token.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from dotenv import load_dotenv

load_dotenv()

from market_data import halt_observation as HO                      # noqa: E402
from broker.topstepx_readonly import TopstepXReadOnlySession        # noqa: E402
from broker.topstepx_realtime import Subscription                   # noqa: E402

STORE_DIR = os.path.join("data", "market_data", "halt_observations")


def _hhmm(text: str) -> tuple:
    hh, mm = text.split(":")
    return int(hh), int(mm)


def _et_today(now_utc: datetime, hhmm: tuple) -> datetime:
    et = now_utc.astimezone(HO.ET)
    return datetime(et.year, et.month, et.day, hhmm[0], hhmm[1], tzinfo=HO.ET)


class HaltObserver:
    """Collects raw events; decides nothing. Adjudication lives in the module."""

    def __init__(self, *, contract_id: str, window: tuple, clock=None):
        self.contract_id = contract_id
        self.window = window
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.events: list = []
        self.dropped_unparsable = 0

    def _record(self, family: str, payload) -> None:
        # A payload we cannot read is COUNTED, never silently discarded: a
        # capture that quietly loses contradictory events cannot adjudicate.
        if not isinstance(payload, dict):
            self.dropped_unparsable += 1
            return
        stamp = (payload.get("timestamp") or payload.get("lastUpdated")
                 or payload.get("t"))
        self.events.append(HO.normalise_event(
            family=family, payload=payload, received_utc=self.clock(),
            provider_timestamp=stamp, window=self.window))

    # SignalR hands handlers a list of arguments: [contractId, payload|list].
    def on_trade(self, args) -> None:
        self._consume(HO.TRADE, args)

    def on_quote(self, args) -> None:
        self._consume(HO.QUOTE, args)

    def _consume(self, family: str, args) -> None:
        items, unreadable = self._payloads(args)
        # An arriving event we could not parse is COUNTED. Returning an empty
        # list and moving on would let the capture lose exactly the evidence it
        # exists to preserve -- and lose it silently, which is worse.
        self.dropped_unparsable += unreadable
        for item in items:
            self._record(family, item)

    @staticmethod
    def _payloads(args) -> tuple:
        """(readable dicts, count of arriving things we could not read)."""
        body = args[-1] if isinstance(args, (list, tuple)) and args else args
        if isinstance(body, dict):
            return [body], 0
        if isinstance(body, (list, tuple)):
            good = [x for x in body if isinstance(x, dict)]
            return good, len(body) - len(good)
        return [], 0 if body is None else 1

    def attach(self, hub) -> None:
        hub.on("GatewayTrade", self.on_trade)
        hub.on("GatewayQuote", self.on_quote)
        hub.subscribe(Subscription("SubscribeContractQuotes",
                                   (self.contract_id,), "GatewayQuote"))
        hub.subscribe(Subscription("SubscribeContractTrades",
                                   (self.contract_id,), "GatewayTrade"))

    def counts(self) -> dict:
        return {"trade": sum(1 for e in self.events if e["event_family"] == HO.TRADE),
                "quote": sum(1 for e in self.events if e["event_family"] == HO.QUOTE),
                "dropped_unparsable": self.dropped_unparsable}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="16:10", help="ET capture start (HH:MM)")
    ap.add_argument("--stop", default="16:35", help="ET capture stop (HH:MM)")
    ap.add_argument("--halt-start", default="16:15")
    ap.add_argument("--halt-stop", default="16:30")
    ap.add_argument("--symbol", default="MNQ")
    ap.add_argument("--dry-run", action="store_true",
                    help="prove wiring and exit; connects nothing, waits for nothing")
    args = ap.parse_args(argv)

    session = TopstepXReadOnlySession(os.getenv("TOPSTEPX_USERNAME", ""),
                                      os.getenv("TOPSTEPX_API_KEY", ""))
    # RAISES ReadOnlyViolation if any write method exists; returns the names it
    # checked. Reaching the next line IS the proof -- there is no falsy success
    # value to test for, and treating the returned list as "what went wrong"
    # would report a clean session as a failing one.
    checked = session.assert_no_write_surface()
    print(f"  ZERO-WRITE SURFACE            : PROVEN ({len(checked)} write methods absent)")
    if args.dry_run:
        now = datetime.now(timezone.utc)
        window = HO.halt_window(now.astimezone(HO.ET).date(),
                                _hhmm(args.halt_start), _hhmm(args.halt_stop))
        print(f"  HALT WINDOW (resolved)        : {window[0].isoformat()} -> "
              f"{window[1].isoformat()}")
        print(f"  CAPTURE                       : {args.start} -> {args.stop} ET")
        print("  DRY RUN                       : no connection, no wait, no order")
        return 0

    session.authenticate()
    session.pin(account_id=int(os.environ["TOPSTEPX_ACCOUNT_ID"]),
                expected_fingerprint=os.getenv("TOPSTEPX_ACCOUNT_FINGERPRINT", ""))
    contract = session.resolve_contract(args.symbol)

    now = datetime.now(timezone.utc)
    et_date = now.astimezone(HO.ET).date()
    window = HO.halt_window(et_date, _hhmm(args.halt_start), _hhmm(args.halt_stop))
    start_at = _et_today(now, _hhmm(args.start)).astimezone(timezone.utc)
    stop_at = _et_today(now, _hhmm(args.stop)).astimezone(timezone.utc)

    print(f"  CONTRACT                      : {contract.id} ({contract.name})")
    print(f"  CAPTURE                       : {start_at.isoformat()} -> {stop_at.isoformat()}")
    print(f"  PUBLISHED HALT                : {window[0].isoformat()} -> {window[1].isoformat()}")
    if datetime.now(timezone.utc) >= stop_at:
        print("  REFUSED                       : the capture window has already passed")
        return 2

    observer = HaltObserver(contract_id=contract.id, window=window)
    hub = session.connect_market_hub()
    observer.attach(hub)
    print("  SUBSCRIBED                    : GatewayTrade + GatewayQuote")

    while datetime.now(timezone.utc) < start_at:
        time.sleep(1.0)
    print("  CAPTURING                     : …")
    while datetime.now(timezone.utc) < stop_at:
        try:
            hub.pump(max_messages=32)
        except Exception as exc:  # noqa: BLE001 — a pump error may not lose the capture
            print(f"  PUMP ERROR                    : {type(exc).__name__}: {exc}")
        time.sleep(0.2)
    session.close()
    print(f"  CAPTURED                      : {observer.counts()}")

    # The history endpoint's own account of the same minutes, kept RAW.
    minutes_back = int((datetime.now(timezone.utc) - start_at).total_seconds() // 60) + 2
    bars = session.bars_1m(minutes_back=minutes_back)
    span = [b for b in bars
            if start_at <= datetime.fromisoformat(b["timestamp"]) < stop_at]
    print(f"  HISTORY BARS IN WINDOW        : {len(span)}")

    matrix = HO.minute_matrix(events=observer.events, bars=span, window=window,
                              first_minute=start_at, last_minute=stop_at)
    verdict = HO.adjudicate(matrix)

    os.makedirs(STORE_DIR, exist_ok=True)
    path = os.path.join(STORE_DIR,
                        f"halt_{et_date:%Y%m%d}_{contract.id.replace('.', '_')}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"contract": {"id": contract.id, "name": contract.name,
                                "description": getattr(contract, "description", "")},
                   "window_utc": [window[0].isoformat(), window[1].isoformat()],
                   "capture_utc": [start_at.isoformat(), stop_at.isoformat()],
                   "counts": observer.counts(),
                   "raw_events": observer.events,
                   "raw_history_bars": span,
                   "minute_matrix": matrix,
                   "verdict": verdict}, fh, indent=2, default=str)

    print(f"\n  {'minute(ET)':>11} {'state':>34} {'trades':>7} {'tvol':>8} "
          f"{'quotes':>7} {'bar':>4} {'bvol':>8}")
    for row in matrix:
        et = datetime.fromisoformat(row["minute"]).astimezone(HO.ET)
        print(f"  {et:%H:%M}       {row['calendar_state']:>34} {row['trade_events']:>7} "
              f"{row['trade_volume']:>8.0f} {row['quote_events']:>7} "
              f"{'Y' if row['history_bar_present'] else 'n':>4} "
              f"{(row['history_volume'] or 0):>8.0f}")
    print(f"\n  CASE                          : {verdict['case']}")
    print(f"  RULING                        : {verdict['ruling']}")
    print(f"  EVIDENCE                      : {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
