"""LUNA-VAP-CAPTURE-AND-PERSISTENCE-1 — stop discarding what Luna already receives.

THE INFORMATION BEING LOST. Every GatewayTrade carries price, size and a
millisecond timestamp. `MinuteCandleAggregator.ingest_trade` folds them into
OHLCV and the trade goes out of scope, so `volume += volume` is the exact line
where price attribution dies. Historical OHLCV cannot reconstruct it and no
venue trade-history endpoint is wired: every session that runs without capture
is a session that can NEVER have a volume profile.

WHAT THIS FILE GUARDS, hardest first:

  1. THE CLAIM. The feed has no trade id and no sequence number, so this is
     OBSERVED traded volume, never exact exchange volume -- and that ceiling
     must survive serialization, not just live in a docstring.
  2. ABSENCE IS NOT ZERO. A missing minute means no evidence. Only a minute
     that was venue-EXPECTED, attached before its start, and watched end to end
     on one unbroken connection may be written as observed-zero.
  3. THE CANDLE AUTHORITY IS UNTOUCHED. Capture rides the shared hub's
     append-handler seam and shares no state with the aggregator.
  4. NO SIDE VOCABULARY. `type` is preserved as an opaque code. Nothing in this
     unit -- including these test names -- says BUY or SELL.

V1-V23 are the mission's adversarial cases, named inline.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import market_data.vap_store as STORE                                # noqa: E402
from market_data import price_ticks as TICKS                         # noqa: E402
from market_data.vap_provider import (CONSUMER_NAME, TRADE_EVENT,    # noqa: E402
                                      VapCaptureProvider)

CID = "CON.F.US.MNQ.U26"
TICK = 0.25

#: 2026-09-02 14:31 UTC = 10:31 ET — an ordinary trading minute inside verified
#: calendar authority. Every temporal fixture below is anchored here.
BASE = dt.datetime(2026, 9, 2, 14, 31, tzinfo=dt.timezone.utc)
#: 2026-09-02 21:30 UTC = 17:30 ET — inside the CME daily maintenance hour.
MAINTENANCE = dt.datetime(2026, 9, 2, 21, 30, tzinfo=dt.timezone.utc)
#: Labor Day: KNOWN_SPECIAL, exact hours deliberately not encoded.
SPECIAL = dt.datetime(2026, 9, 7, 14, 31, tzinfo=dt.timezone.utc)


class Runtime:
    """The runtime surface capture actually uses: a generation and an append."""

    def __init__(self, generation=1):
        self.connection_generation = generation
        self.handlers = []

    def attach(self, name, event, handler):
        self.handlers.append((name, event, handler))


class Clock:
    def __init__(self, start): self.now = start
    def __call__(self): return self.now


@pytest.fixture
def cap(tmp_path):
    clock = Clock(BASE)
    p = VapCaptureProvider(contract_id=CID, tick_size=TICK,
                           store_dir=str(tmp_path), clock=clock)
    p.attach(Runtime())
    p._clock_obj = clock                       # test handle only
    return p


def trades(at, rows, contract=CID):
    """One GatewayTrade payload: [contractId, [trade, ...]]."""
    return [contract, [{"contractId": contract, "price": pr, "volume": v,
                        "timestamp": (at + dt.timedelta(seconds=i)).isoformat(),
                        **({} if ty is _ABSENT else {"type": ty})}
                       for i, (pr, v, ty) in enumerate(rows)]]


class _Absent:
    pass


_ABSENT = _Absent()


def rows_for(store_dir, minute=None):
    out = STORE.load(str(store_dir), CID)
    if minute is None:
        return out
    return [r for r in out if r["minute"] == minute.isoformat()]


# ── the price key ─────────────────────────────────────────────────────────────

class TestIntegerTickKey:
    def test_V4_float_noise_lands_on_one_key(self):
        """29250.25 and its float-noisy twin are one price level, not two."""
        exact = TICKS.tick_index(29250.25, TICK)
        noisy = TICKS.tick_index(29250.25 + 1e-11, TICK)
        assert exact == noisy == 117001

    def test_V5_a_materially_off_grid_price_is_refused(self):
        """Rounding it into a neighbour would invent a trade at a price the
        venue cannot quote."""
        assert TICKS.tick_index(29250.30, TICK) is None
        assert TICKS.is_on_grid(29250.30, TICK) is False

    def test_the_key_is_symmetric(self):
        """Unlike `normalize_to_tick`, which ceils for a long and floors for a
        short because it snaps PROTECTION. A bucket key that moved with the side
        would split one level in two."""
        import inspect

        from broker.break_even import normalize_to_tick
        assert "direction" in inspect.signature(normalize_to_tick).parameters
        assert "direction" not in inspect.signature(TICKS.tick_index).parameters

    def test_the_display_price_round_trips(self):
        for price in (29250.25, 29250.50, 29000.00, 1.25):
            assert TICKS.tick_price(TICKS.tick_index(price, TICK), TICK) == price

    def test_unusable_inputs_refuse_rather_than_guess(self):
        for bad in (None, "x", float("nan"), float("inf"), True):
            assert TICKS.tick_index(bad, TICK) is None
        for bad_tick in (0, -0.25, None):
            assert TICKS.tick_index(29250.25, bad_tick) is None

    def test_no_float_ever_becomes_a_key(self, cap, tmp_path):
        cap.on_trade(trades(BASE, [(29250.25, 3, 0)]))
        cap._clock_obj.now = BASE + dt.timedelta(minutes=1)
        cap.on_trade(trades(BASE + dt.timedelta(minutes=1), [(29251.0, 1, 0)]))
        raw = open(STORE.store_path(str(tmp_path), CID), encoding="utf-8").read()
        for line in raw.strip().splitlines():
            for key in json.loads(line)["levels"]:
                assert "." not in key, key
                int(key)


# ── duplication ───────────────────────────────────────────────────────────────

class TestDuplication:
    def test_V1_identical_prints_both_count(self, cap, tmp_path):
        """A swept order prints many same-price 1-lots in one millisecond.
        Measured 2026-08-05: 2,584 trades carried 1,093 such collisions, and
        treating them as duplicates discarded 39% of real volume."""
        payload = [CID, [
            {"contractId": CID, "price": 29250.25, "volume": 1,
             "timestamp": BASE.isoformat(), "type": 0},
            {"contractId": CID, "price": 29250.25, "volume": 1,
             "timestamp": BASE.isoformat(), "type": 0}]]
        cap.on_trade(payload)
        cap._clock_obj.now = BASE + dt.timedelta(minutes=1)
        cap.on_trade(trades(BASE + dt.timedelta(minutes=1), [(29251.0, 1, 0)]))
        first = rows_for(tmp_path, BASE)[0]
        assert first["total_observed_volume"] == 2.0
        assert first["levels"][117001] == 2.0

    def test_V2_byte_identical_batch_replay_is_dropped(self, cap, tmp_path):
        payload = trades(BASE, [(29250.25, 4, 0)])
        cap.on_trade(payload)
        cap.on_trade(json.loads(json.dumps(payload)))     # same bytes, redelivered
        cap._clock_obj.now = BASE + dt.timedelta(minutes=1)
        cap.on_trade(trades(BASE + dt.timedelta(minutes=1), [(29251.0, 1, 0)]))
        assert rows_for(tmp_path, BASE)[0]["total_observed_volume"] == 4.0
        assert cap.diagnostics["duplicate_batches"] == 1

    def test_V3_a_reframed_batch_is_not_claimed_to_be_caught(self, cap, tmp_path):
        """Re-framing splits one payload into two; the hash differs, so both are
        folded. The store must not pretend otherwise."""
        cap.on_trade(trades(BASE, [(29250.25, 2, 0), (29250.50, 2, 0)]))
        cap.on_trade(trades(BASE, [(29250.25, 2, 0)]))     # re-framed subset
        cap._clock_obj.now = BASE + dt.timedelta(minutes=1)
        cap.on_trade(trades(BASE + dt.timedelta(minutes=1), [(29251.0, 1, 0)]))
        assert rows_for(tmp_path, BASE)[0]["total_observed_volume"] == 6.0
        assert "exactly-once" not in cap.describe()["claim"].replace(
            "exactly-once delivery is not claimed", "")

    def test_no_per_trade_dedup_structure_exists(self):
        """STRUCTURAL, NOT TEXTUAL. The module docstring EXPLAINS why per-trade
        dedup is forbidden, so grepping its prose flags the very sentence that
        forbids it. Only the batch ring may exist as state."""
        import ast
        tree = ast.parse(open(os.path.join(ROOT, "src", "market_data",
                                           "vap_provider.py"), encoding="utf-8").read())
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for banned in ("_seen_trades", "_trade_digests", "_seen_prints"):
            assert banned not in attrs, banned
        assert "_seen_batches" in attrs, "the batch replay guard is missing"


# ── raw type, never a side ────────────────────────────────────────────────────

class TestRawTypeIsOpaque:
    def test_V7_raw_codes_are_preserved_without_interpretation(self, cap, tmp_path):
        cap.on_trade(trades(BASE, [(29250.25, 3, 0), (29250.50, 5, 1)]))
        cap._clock_obj.now = BASE + dt.timedelta(minutes=1)
        cap.on_trade(trades(BASE + dt.timedelta(minutes=1), [(29251.0, 1, 0)]))
        row = rows_for(tmp_path, BASE)[0]
        assert row["raw_type_volume"] == {"0": 3.0, "1": 5.0}

    def test_V6_a_missing_type_keeps_the_volume_and_claims_no_side(self, cap, tmp_path):
        cap.on_trade(trades(BASE, [(29250.25, 4, _ABSENT)]))
        cap._clock_obj.now = BASE + dt.timedelta(minutes=1)
        cap.on_trade(trades(BASE + dt.timedelta(minutes=1), [(29251.0, 1, 0)]))
        row = rows_for(tmp_path, BASE)[0]
        assert row["total_observed_volume"] == 4.0
        assert row["unknown_type_volume"] == 4.0
        assert row["raw_type_volume"] == {}

    def test_a_missing_type_is_never_defaulted_to_zero(self, cap, tmp_path):
        cap.on_trade(trades(BASE, [(29250.25, 4, _ABSENT)]))
        cap._clock_obj.now = BASE + dt.timedelta(minutes=1)
        cap.on_trade(trades(BASE + dt.timedelta(minutes=1), [(29251.0, 1, 0)]))
        assert "0" not in rows_for(tmp_path, BASE)[0]["raw_type_volume"]

    def test_no_side_vocabulary_anywhere_in_the_unit(self):
        import ast
        for rel in ("market_data/price_ticks.py", "market_data/vap_store.py",
                    "market_data/vap_provider.py"):
            tree = ast.parse(open(os.path.join(ROOT, "src", *rel.split("/")),
                                  encoding="utf-8").read())
            names = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    names.add(node.id.lower())
                elif isinstance(node, ast.Attribute):
                    names.add(node.attr.lower())
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if len(node.value) < 60:
                        names.add(node.value.lower())
            for banned in ("buy_volume", "sell_volume", "aggressor", "delta",
                           "bid_volume", "ask_volume"):
                assert banned not in names, (rel, banned)


# ── capture continuity ────────────────────────────────────────────────────────

class TestCaptureContinuity:
    def test_V8_startup_mid_minute_is_never_complete(self, cap, tmp_path):
        cap.on_trade(trades(BASE, [(29250.25, 3, 0)]))
        cap._clock_obj.now = BASE + dt.timedelta(minutes=1)
        cap.on_trade(trades(BASE + dt.timedelta(minutes=1), [(29251.0, 1, 0)]))
        assert rows_for(tmp_path, BASE)[0]["status"] == STORE.PARTIAL_START

    def test_V22_a_later_trade_cannot_promote_the_partial_minute(self, cap, tmp_path):
        cap.on_trade(trades(BASE, [(29250.25, 3, 0)]))
        for k in range(1, 4):
            cap._clock_obj.now = BASE + dt.timedelta(minutes=k)
            cap.on_trade(trades(BASE + dt.timedelta(minutes=k), [(29251.0, 1, 0)]))
        assert rows_for(tmp_path, BASE)[0]["status"] == STORE.PARTIAL_START
        later = rows_for(tmp_path, BASE + dt.timedelta(minutes=1))[0]
        assert later["status"] == STORE.COMPLETE

    def test_V9_a_generation_change_mid_minute_interrupts_it(self, cap, tmp_path):
        m1 = BASE + dt.timedelta(minutes=1)
        cap._clock_obj.now = m1
        cap.on_trade(trades(m1, [(29250.25, 3, 0)]))
        cap._runtime.connection_generation = 2            # the socket dropped
        cap.on_trade(trades(m1 + dt.timedelta(seconds=30), [(29250.50, 2, 0)]))
        cap._clock_obj.now = m1 + dt.timedelta(minutes=1)
        cap.on_trade(trades(m1 + dt.timedelta(minutes=1), [(29251.0, 1, 0)]))
        assert rows_for(tmp_path, m1)[0]["status"] == STORE.INTERRUPTED

    def test_a_reconnect_cannot_retroactively_complete_the_minute(self, cap, tmp_path):
        m1 = BASE + dt.timedelta(minutes=1)
        cap._clock_obj.now = m1
        cap.on_trade(trades(m1, [(29250.25, 3, 0)]))
        cap._runtime.connection_generation = 2
        for k in range(2, 5):
            cap._clock_obj.now = BASE + dt.timedelta(minutes=k)
            cap.on_trade(trades(BASE + dt.timedelta(minutes=k), [(29251.0, 1, 0)]))
        assert rows_for(tmp_path, m1)[0]["status"] == STORE.INTERRUPTED

    def test_V23_a_generation_change_denies_completeness_across_the_gap(self, cap, tmp_path):
        cap.on_trade(trades(BASE, [(29250.25, 1, 0)]))
        cap._clock_obj.now = BASE + dt.timedelta(minutes=1)
        cap.on_trade(trades(BASE + dt.timedelta(minutes=1), [(29250.50, 1, 0)]))
        cap._runtime.connection_generation = 7            # dropped during the gap
        cap._clock_obj.now = BASE + dt.timedelta(minutes=5)
        cap.on_trade(trades(BASE + dt.timedelta(minutes=5), [(29251.0, 1, 0)]))
        for k in (2, 3, 4):
            gap = rows_for(tmp_path, BASE + dt.timedelta(minutes=k))
            assert gap == [] or gap[0]["status"] != STORE.COMPLETE, k


# ── observed zero vs missing ──────────────────────────────────────────────────

class TestObservedZeroIsEarned:
    def test_V21_an_expected_empty_minute_observed_end_to_end_is_zero(self, cap, tmp_path):
        cap.on_trade(trades(BASE, [(29250.25, 1, 0)]))
        cap._clock_obj.now = BASE + dt.timedelta(minutes=1)
        cap.on_trade(trades(BASE + dt.timedelta(minutes=1), [(29250.50, 1, 0)]))
        cap._clock_obj.now = BASE + dt.timedelta(minutes=4)
        cap.on_trade(trades(BASE + dt.timedelta(minutes=4), [(29251.0, 1, 0)]))
        for k in (2, 3):
            row = rows_for(tmp_path, BASE + dt.timedelta(minutes=k))[0]
            assert row["status"] == STORE.COMPLETE, k
            assert row["observed_zero_volume"] is True, k
            assert row["total_observed_volume"] == 0.0
            assert row["levels"] == {}

    def test_V13_zero_is_distinguishable_from_missing(self, cap, tmp_path):
        cap.on_trade(trades(BASE, [(29250.25, 1, 0)]))
        cap._clock_obj.now = BASE + dt.timedelta(minutes=1)
        cap.on_trade(trades(BASE + dt.timedelta(minutes=1), [(29250.50, 1, 0)]))
        cap._clock_obj.now = BASE + dt.timedelta(minutes=3)
        cap.on_trade(trades(BASE + dt.timedelta(minutes=3), [(29251.0, 1, 0)]))
        zero = rows_for(tmp_path, BASE + dt.timedelta(minutes=2))[0]
        assert zero["observed_zero_volume"] is True
        # A minute nobody ever observed has NO row at all.
        assert rows_for(tmp_path, BASE - dt.timedelta(minutes=5)) == []

    def test_V19_the_maintenance_hour_manufactures_no_trading_minutes(self, tmp_path):
        """17:00-18:00 ET is a scheduled CME close. Silence there is not an
        observed-zero trading minute, and an arbitrary gap threshold would have
        called it one."""
        clock = Clock(MAINTENANCE)
        p = VapCaptureProvider(contract_id=CID, tick_size=TICK,
                               store_dir=str(tmp_path), clock=clock)
        p.attach(Runtime())
        p.on_trade(trades(MAINTENANCE, [(29250.25, 1, 0)]))
        clock.now = MAINTENANCE + dt.timedelta(minutes=1)
        p.on_trade(trades(MAINTENANCE + dt.timedelta(minutes=1), [(29250.5, 1, 0)]))
        clock.now = MAINTENANCE + dt.timedelta(minutes=5)
        p.on_trade(trades(MAINTENANCE + dt.timedelta(minutes=5), [(29251.0, 1, 0)]))
        for k in (2, 3, 4):
            assert rows_for(tmp_path, MAINTENANCE + dt.timedelta(minutes=k)) == [], k

    def test_V20_an_unknown_cadence_minute_is_unproven_not_zero(self, tmp_path):
        """Labor Day is KNOWN_SPECIAL with exact hours deliberately unencoded."""
        import market_data.venue_calendar as VC
        assert VC.calendar_authority(SPECIAL) == "KNOWN_SPECIAL"
        clock = Clock(SPECIAL)
        p = VapCaptureProvider(contract_id=CID, tick_size=TICK,
                               store_dir=str(tmp_path), clock=clock)
        p.attach(Runtime())
        p.on_trade(trades(SPECIAL, [(29250.25, 1, 0)]))
        clock.now = SPECIAL + dt.timedelta(minutes=1)
        p.on_trade(trades(SPECIAL + dt.timedelta(minutes=1), [(29250.5, 1, 0)]))
        clock.now = SPECIAL + dt.timedelta(minutes=4)
        p.on_trade(trades(SPECIAL + dt.timedelta(minutes=4), [(29251.0, 1, 0)]))
        for k in (2, 3):
            assert rows_for(tmp_path, SPECIAL + dt.timedelta(minutes=k)) == [], k
        observed = rows_for(tmp_path, SPECIAL + dt.timedelta(minutes=1))
        assert observed and observed[0]["status"] == STORE.UNPROVEN

    def test_each_gap_minute_is_judged_on_its_own_cadence(self):
        """A maintenance minute inside a gap does not inherit the expectation of
        the trading minutes around it."""
        src = open(os.path.join(ROOT, "src", "market_data", "vap_provider.py"),
                   encoding="utf-8").read()
        assert "judged on\n    # its OWN venue cadence" in src or \
            "its OWN venue cadence" in src

    def test_venue_calendar_is_the_only_schedule_authority(self):
        import ast
        tree = ast.parse(open(os.path.join(ROOT, "src", "market_data",
                                           "vap_provider.py"), encoding="utf-8").read())
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                mods.add(node.module)
        assert "market_data" in mods
        src = open(os.path.join(ROOT, "src", "market_data", "vap_provider.py"),
                   encoding="utf-8").read()
        assert "venue_calendar" in src
        for invented in ("MARKET_HOURS", "SESSION_HOURS", "GAP_THRESHOLD",
                         "MAX_GAP_MINUTES"):
            assert invented not in src, invented


# ── persistence, restart, retention ───────────────────────────────────────────

class TestPersistence:
    def test_V14_a_failed_write_is_not_claimed_durable(self, cap, monkeypatch):
        monkeypatch.setattr(STORE, "append", lambda *a, **k: False)
        cap.on_trade(trades(BASE, [(29250.25, 3, 0)]))
        cap._clock_obj.now = BASE + dt.timedelta(minutes=1)
        cap.on_trade(trades(BASE + dt.timedelta(minutes=1), [(29251.0, 1, 0)]))
        assert cap.diagnostics["persist_failed"] >= 1
        assert BASE.isoformat() not in cap._sealed_minutes

    def test_the_store_fsyncs_like_the_journal_not_the_candle_file(self):
        src = open(os.path.join(ROOT, "src", "market_data", "vap_store.py"),
                   encoding="utf-8").read()
        assert "os.fsync" in src
        assert "return True" in src and "return False" in src

    def test_V10_sealed_minutes_recover_after_restart(self, tmp_path):
        clock = Clock(BASE)
        first = VapCaptureProvider(contract_id=CID, tick_size=TICK,
                                   store_dir=str(tmp_path), clock=clock)
        first.attach(Runtime())
        first.on_trade(trades(BASE, [(29250.25, 3, 0)]))
        clock.now = BASE + dt.timedelta(minutes=1)
        first.on_trade(trades(BASE + dt.timedelta(minutes=1), [(29251.0, 1, 0)]))
        assert len(rows_for(tmp_path)) == 1

        clock2 = Clock(BASE + dt.timedelta(minutes=5))
        second = VapCaptureProvider(contract_id=CID, tick_size=TICK,
                                    store_dir=str(tmp_path), clock=clock2)
        second.attach(Runtime(generation=1))
        assert BASE.isoformat() in second._sealed_minutes

    def test_V11_an_unsealed_minute_cannot_recover_as_complete(self, tmp_path):
        clock = Clock(BASE)
        first = VapCaptureProvider(contract_id=CID, tick_size=TICK,
                                   store_dir=str(tmp_path), clock=clock)
        first.attach(Runtime())
        first.on_trade(trades(BASE, [(29250.25, 3, 0)]))     # never sealed: crash
        assert rows_for(tmp_path) == []
        clock2 = Clock(BASE + dt.timedelta(minutes=5))
        second = VapCaptureProvider(contract_id=CID, tick_size=TICK,
                                    store_dir=str(tmp_path), clock=clock2)
        second.attach(Runtime())
        assert second._sealed_minutes == set()
        assert rows_for(tmp_path, BASE) == []

    def test_V12_rest_ohlcv_cannot_heal_a_vap_gap(self):
        """REST bars carry no price attribution, so nothing in this unit may
        reach the history endpoint to fill a hole."""
        src = open(os.path.join(ROOT, "src", "market_data", "vap_provider.py"),
                   encoding="utf-8").read()
        for banned in ("retrieveBars", "bars_1m", "_fetch_bars", "backfill"):
            assert banned not in src, banned

    def test_a_torn_final_line_does_not_cost_the_history_before_it(self, tmp_path):
        clock = Clock(BASE)
        p = VapCaptureProvider(contract_id=CID, tick_size=TICK,
                               store_dir=str(tmp_path), clock=clock)
        p.attach(Runtime())
        p.on_trade(trades(BASE, [(29250.25, 3, 0)]))
        clock.now = BASE + dt.timedelta(minutes=1)
        p.on_trade(trades(BASE + dt.timedelta(minutes=1), [(29251.0, 1, 0)]))
        with open(STORE.store_path(str(tmp_path), CID), "a", encoding="utf-8") as fh:
            fh.write('{"schema": "vap_minute.v1", "min')
        assert len(rows_for(tmp_path)) == 1


class TestContractIdentity:
    def test_V15_a_roll_gets_its_own_store(self, tmp_path):
        a = STORE.store_path(str(tmp_path), "CON.F.US.MNQ.U26")
        b = STORE.store_path(str(tmp_path), "CON.F.US.MNQ.Z26")
        assert a != b
        assert "MNQ_U26" in a and "MNQ_Z26" in b

    def test_the_store_is_never_keyed_by_bare_symbol(self, tmp_path):
        assert "MNQ" in STORE.store_path(str(tmp_path), CID)
        assert STORE.store_path(str(tmp_path), CID) != \
            STORE.store_path(str(tmp_path), "MNQ")

    def test_a_foreign_contract_trade_is_discarded(self, cap, tmp_path):
        cap.on_trade(trades(BASE, [(29250.25, 3, 0)], contract="CON.F.US.ES.U26"))
        assert cap.diagnostics["foreign_contract"] == 1
        assert cap.diagnostics["trades"] == 0


class TestRetention:
    def test_V18_pruning_cannot_alter_recent_data(self, tmp_path):
        now = dt.datetime(2027, 3, 1, tzinfo=dt.timezone.utc)
        recent = STORE.build_record(
            contract_id=CID, minute=(now - dt.timedelta(days=5)).isoformat(),
            status=STORE.COMPLETE, tick_size=TICK, levels={117001: 5.0},
            raw_type_volume={"0": 5.0}, trades_observed=2)
        old = STORE.build_record(
            contract_id=CID, minute=(now - dt.timedelta(days=400)).isoformat(),
            status=STORE.COMPLETE, tick_size=TICK, levels={117001: 9.0})
        assert STORE.append(str(tmp_path), old)
        assert STORE.append(str(tmp_path), recent)
        before = [r for r in rows_for(tmp_path) if "2027-02" in r["minute"]][0]
        out = STORE.prune(str(tmp_path), CID, now=now)
        assert out["ok"] and out["dropped"] == 1 and out["kept"] == 1
        after = rows_for(tmp_path)
        assert len(after) == 1
        assert after[0] == before, "a survivor was rewritten by pruning"

    def test_the_horizon_is_the_owner_policy(self):
        assert STORE.VAP_RETENTION_DAYS == 180

    def test_pruning_never_upgrades_a_status(self, tmp_path):
        now = dt.datetime(2027, 3, 1, tzinfo=dt.timezone.utc)
        rec = STORE.build_record(
            contract_id=CID, minute=(now - dt.timedelta(days=2)).isoformat(),
            status=STORE.PARTIAL_START, tick_size=TICK, levels={117001: 1.0})
        assert STORE.append(str(tmp_path), rec)
        STORE.prune(str(tmp_path), CID, now=now)
        assert rows_for(tmp_path)[0]["status"] == STORE.PARTIAL_START


# ── the canonical candle authority ────────────────────────────────────────────

class TestCandleAuthorityUntouched:
    def test_V16_the_aggregator_produces_identical_candles_either_way(self, tmp_path):
        """Capture shares no state with the aggregator, so attaching it cannot
        move a single OHLCV value."""
        from data_feed.topstepx_provider import MinuteCandleAggregator
        payloads = [trades(BASE + dt.timedelta(minutes=k),
                           [(29250.25 + k, 3, 0), (29250.50 + k, 2, 1)])
                    for k in range(4)]
        alone = MinuteCandleAggregator(CID, TICK)
        for p in payloads:
            alone.ingest_event(p)
        alone.roll(BASE + dt.timedelta(minutes=10))

        beside = MinuteCandleAggregator(CID, TICK)
        clock = Clock(BASE)
        cap = VapCaptureProvider(contract_id=CID, tick_size=TICK,
                                 store_dir=str(tmp_path), clock=clock)
        cap.attach(Runtime())
        for k, p in enumerate(payloads):
            clock.now = BASE + dt.timedelta(minutes=k)
            beside.ingest_event(p)
            cap.on_trade(p)
        beside.roll(BASE + dt.timedelta(minutes=10))
        assert alone.closed_candles() == beside.closed_candles()
        assert alone.diagnostics == beside.diagnostics

    def test_V17_the_candle_provider_source_is_unmodified_by_this_unit(self):
        import subprocess
        out = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "--",
             "src/data_feed/topstepx_provider.py",
             "src/broker/topstepx_market_runtime.py"],
            cwd=ROOT, capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        assert out.stdout.strip() == "", (
            f"this unit modified {out.stdout.split()}; the runtime fan-out and "
            f"lifecycle facts were supposed to suffice")

    def test_capture_shares_no_state_with_the_aggregator(self):
        """The docstring NAMES `MinuteCandleAggregator` to explain what is being
        lost, so the guard has to read the code rather than the prose: capture
        must neither import the candle module nor touch aggregator state."""
        import ast
        tree = ast.parse(open(os.path.join(ROOT, "src", "market_data",
                                           "vap_provider.py"), encoding="utf-8").read())
        mods, names, attrs = set(), set(), set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                mods.add(node.module)
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.Import):
                mods.update(a.name for a in node.names)
            elif isinstance(node, ast.Attribute):
                attrs.add(node.attr)
            elif isinstance(node, ast.Name):
                names.add(node.id)
        assert not any(m.startswith("data_feed") for m in mods), sorted(mods)
        assert "MinuteCandleAggregator" not in names
        for banned in ("_closed_minutes", "_closed", "aggregator", "ingest_trade"):
            assert banned not in attrs, banned

    def test_capture_attaches_as_its_own_named_consumer(self, cap):
        assert cap._runtime.handlers == [(CONSUMER_NAME, TRADE_EVENT, cap.on_trade)]
        assert CONSUMER_NAME != "candle-provider"


# ── the claim ─────────────────────────────────────────────────────────────────

class TestTheClaimSurvivesSerialization:
    def test_every_record_states_what_it_is_and_is_not(self, cap, tmp_path):
        cap.on_trade(trades(BASE, [(29250.25, 3, 0)]))
        cap._clock_obj.now = BASE + dt.timedelta(minutes=1)
        cap.on_trade(trades(BASE + dt.timedelta(minutes=1), [(29251.0, 1, 0)]))
        row = rows_for(tmp_path, BASE)[0]
        assert row["volume_claim"] == "total_observed_volume"
        assert "never a claim of exact exchange volume" in row["claim_note"]

    def test_status_and_volume_claim_are_separate_axes(self):
        """COMPLETE is a capture-continuity verdict. It is not a claim that the
        exchange printed nothing else."""
        rec = STORE.build_record(contract_id=CID, minute=BASE.isoformat(),
                                 status=STORE.COMPLETE, tick_size=TICK,
                                 levels={117001: 4.0}, observed_zero_volume=True)
        assert rec["status"] == STORE.COMPLETE
        assert rec["observed_zero_volume"] is False, "volume was not zero"

    def test_zero_can_never_be_claimed_under_a_weak_status(self):
        for status in (STORE.PARTIAL_START, STORE.INTERRUPTED, STORE.UNPROVEN):
            rec = STORE.build_record(contract_id=CID, minute=BASE.isoformat(),
                                     status=status, tick_size=TICK, levels={},
                                     observed_zero_volume=True)
            assert rec["observed_zero_volume"] is False, status

    def test_no_profile_math_was_built(self):
        import ast
        for rel in ("price_ticks.py", "vap_store.py", "vap_provider.py"):
            tree = ast.parse(open(os.path.join(ROOT, "src", "market_data", rel),
                                  encoding="utf-8").read())
            fns = {n.name.lower() for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef)}
            for banned in ("poc", "value_area", "vah", "val", "hvn", "lvn",
                           "profile", "acceptance", "developing_poc"):
                assert banned not in fns, (rel, banned)

    def test_no_brain_or_strategy_surface_is_reachable(self):
        import ast
        for rel in ("price_ticks.py", "vap_store.py", "vap_provider.py"):
            tree = ast.parse(open(os.path.join(ROOT, "src", "market_data", rel),
                                  encoding="utf-8").read())
            mods = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    mods.add(node.module.split(".")[0])
                elif isinstance(node, ast.Import):
                    mods.update(a.name.split(".")[0] for a in node.names)
            for banned in ("ai_brain", "structure", "execution_gate",
                           "decision_authority", "risk", "playbooks", "broker"):
                assert banned not in mods, (rel, banned)

    def test_capture_never_raises_on_malformed_input(self, cap):
        for bad in (None, [], [CID], [CID, None], [CID, [None]],
                    [CID, [{"price": "x", "volume": 1, "timestamp": "nope"}]],
                    [CID, [{}]]):
            assert cap.on_trade(bad) == 0
