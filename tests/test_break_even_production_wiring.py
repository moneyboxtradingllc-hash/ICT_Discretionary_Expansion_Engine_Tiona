"""BREAK-EVEN-2B — the production management path actually invokes the actuator.

`1356ccb` certified CAPABILITY. This certifies OWNERSHIP: that the deterministic
management tick calls it, exactly once, from exactly one place, with no model
consulted, and that a protection defect reaches the certified safety authority
instead of a second flatten implementation grown inside break-even.

Venue lineage below is the REAL 2026-08-25 T2 specimen — entry 3446535520 with
children 3446535522 (stop) / 3446535523 (target). The FAVOURABLE PRICE MOVEMENT
is synthetic: that trade never reached +1R, and pretending otherwise would put a
fabricated outcome into the record.

No broker. No provider. No network.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from broker import break_even as BE                                  # noqa: E402
from broker import break_even_actuator as ACT                        # noqa: E402
from broker import topstepx_mission_state as MS                      # noqa: E402
from broker import topstepx_production_loop as PL                    # noqa: E402

CID = "CON.F.US.MNQ.U26"

# ── REAL 2026-08-25 T2 venue lineage ────────────────────────────────────────
T2_ENTRY, T2_STOP, T2_TARGET = 3446535520, 3446535522, 3446535523
T2_FILL, T2_STOP_PX, T2_TARGET_PX = 29226.25, 29192.00, 29409.25
T2_SIZE = 5
T2_R = T2_FILL - T2_STOP_PX          # 34.25 points, from the real geometry


def t2_position(size=T2_SIZE):
    return {"id": 830922009, "contract_id": CID, "side": "long", "size": size,
            "avg_price": T2_FILL, "opened_at": "2026-08-25T14:49:20.296104+00:00"}


def t2_children(stop_px=T2_STOP_PX):
    return [{"id": T2_STOP, "contract_id": CID, "status": 1, "type": 4,
             "side": 1, "size": T2_SIZE, "limit_price": None,
             "stop_price": stop_px, "parent_order_id": T2_ENTRY},
            {"id": T2_TARGET, "contract_id": CID, "status": 1, "type": 1,
             "side": 1, "size": T2_SIZE, "limit_price": T2_TARGET_PX,
             "stop_price": None, "parent_order_id": T2_ENTRY}]


# ══ 6 · EXACTLY ONE PRODUCTION OWNER ════════════════════════════════════════
class TestSingleOwner:
    """Two owners could each read fresh truth, each see an eligible advance,
    and each write — the duplicate mutation exactly-once-EFFECT forbids."""

    def test_only_one_production_module_invokes_the_actuator(self):
        import subprocess
        src = os.path.join(ROOT, "src")
        hits = []
        for root, _dirs, files in os.walk(src):
            if "__pycache__" in root:
                continue
            for fn in files:
                if not fn.endswith(".py") or fn == "break_even_actuator.py":
                    continue
                path = os.path.join(root, fn)
                with open(path, encoding="utf-8") as fh:
                    body = fh.read()
                if "apply_break_even" in body:
                    hits.append(os.path.relpath(path, ROOT).replace("\\", "/"))
        assert hits == ["src/broker/topstepx_production_loop.py"], hits

    def test_the_owner_is_the_management_method(self):
        import inspect
        body = inspect.getsource(PL.ProductionLoop.manage_open_position)
        assert "apply_break_even" in body

    def test_management_runs_before_the_entry_authority_gate(self):
        """So it keeps working once the cap is spent and cognition is off."""
        import inspect
        body = inspect.getsource(PL.ProductionLoop._scan_once)
        assert body.index("manage_open_position") < body.index(
            "entry_authority_exhausted")


# ══ harness ═════════════════════════════════════════════════════════════════
class Ctx:
    protection_baseline_armed = True
    active_protective_stop = T2_STOP_PX


class Runner:
    def __init__(self):
        self.execution_context = Ctx()
        self.flattens = []

    def emergency_flatten(self, reason):
        self.flattens.append(reason)
        return {"flattened": True, "reason": reason}


class Capture:
    """The attribute surface `topstepx_execution_price.from_capture` reads."""

    def __init__(self, bid, ask, age):
        self.best_bid, self.best_ask = bid, ask
        self.last_trade = ask
        self.market_data_age_seconds = age
        self.contract_id = CID


class Quote:
    def __init__(self, bid, ask, fresh=True):
        self.bid, self.ask, self.fresh = bid, ask, fresh

    def capture(self):
        return Capture(self.bid, self.ask, 0.01 if self.fresh else 999.0)


class Venue:
    def __init__(self, positions, orders):
        self._p, self._o, self.modifies = list(positions), list(orders), []

    def open_positions(self):
        return [dict(p) for p in self._p]

    def open_orders(self):
        return [dict(o) for o in self._o]

    def query_orders(self, *, statuses=None, contract_id=None):
        """`/api/Order/v2/query` -- the COMPLETE discovery surface.

        Production reads this, not `searchOpen`, because `searchOpen` omits
        Suspended bracket children by venue contract. A fixture without this
        method models the degraded fallback, where absence can never be proven.
        No status filter is applied, matching production.
        """
        rows = [dict(o) for o in self._o]
        if contract_id:
            rows = [o for o in rows
                    if (o.get("contract_id") or o.get("contractId")) == contract_id]
        return rows

    def recent_trades(self, since=None):
        return []

    def modify_order(self, order_id, *, size=None, limit_price=None,
                     stop_price=None, trail_price=None):
        self.modifies.append({"order_id": order_id, "stop_price": stop_price})
        for o in self._o:
            if o["id"] == order_id and stop_price is not None:
                o["stop_price"] = stop_price
        return {"success": True}


class Contract:
    id = CID
    tick_size = 0.25
    tick_value = 0.50


class PS:
    def __init__(self, venue, quote, runner):
        self.session, self.quote_provider, self.runner = venue, quote, runner
        self.contract = Contract()


class Mission:
    """The durable mission surface `manage_open_position` consumes."""

    def __init__(self, store_dir, session_id="PRAC-20260825", state=MS.POSITION_OPEN):
        self.store_dir, self.session_id = store_dir, session_id
        self.authorization = type("A", (), {"session_id": session_id,
                                            "maximum_trades": 2})()
        self._m = type("M", (), {"order_id": T2_ENTRY, "state": state,
                                 "mission_id": f"{session_id}-T2"})()

    @property
    def active_mission(self):
        return self._m

    def mission_path(self, index):
        return os.path.join(self.store_dir,
                            f"trade_mission_{self.session_id}_{index}.json")

    def trades_used(self):
        return 2

    trade_missions = []


def write_durable(tmp_path, *, session_id="PRAC-20260825", fill=T2_FILL,
                  stop=T2_STOP_PX, size=T2_SIZE, direction="long"):
    """The two artifacts the R baseline is reconstructed from."""
    mid = f"{session_id}-T2"
    mp = os.path.join(str(tmp_path), f"trade_mission_{session_id}_1.json")
    with open(mp, "w", encoding="utf-8") as fh:
        json.dump({"mission_id": mid, "contract_id": CID, "order_id": T2_ENTRY,
                   "account_fingerprint": "acct:aaaaaaaaaaaa",
                   "fill_price": fill, "filled_quantity": size,
                   "token_id": "tok"}, fh)
    sp = os.path.join(str(tmp_path), f"submissions_{session_id}.jsonl")
    with open(sp, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "mission_id": mid, "submission_id": "s1", "token_id": "tok",
            "state": "SUBMISSION_STARTED",
            "geometry": {"direction": direction, "entry_price": fill,
                         "stop_price": stop, "target_price": T2_TARGET_PX,
                         "stop_points": 30.0, "size": size,
                         "contract_id": CID}}) + "\n")
    return mp, sp


def loop_for(tmp_path, *, bid, ask, stop_px=T2_STOP_PX, positions=None,
             orders=None, state=MS.POSITION_OPEN):
    write_durable(tmp_path)
    venue = Venue(positions if positions is not None else [t2_position()],
                  orders if orders is not None else t2_children(stop_px))
    runner = Runner()
    runner.execution_context.active_protective_stop = stop_px
    loop = PL.ProductionLoop.__new__(PL.ProductionLoop)
    loop.ps = PS(venue, Quote(bid, ask), runner)
    loop.mission = Mission(str(tmp_path), state=state)
    return loop, venue, runner


# ══ 7 · THE MANAGED ADVANCE, REAL LINEAGE ═══════════════════════════════════
class TestManagedAdvance:
    """+1R for this long is bid >= fill + 34.25 = 29260.50 (synthetic move)."""

    def test_below_1R_sends_no_write(self, tmp_path):
        loop, venue, _ = loop_for(tmp_path, bid=29240.0, ask=29240.25)
        out = loop.manage_open_position()
        assert out["status"] == "decision_declines"
        assert venue.modifies == []

    def test_at_1R_the_owned_stop_is_advanced_once(self, tmp_path):
        loop, venue, _ = loop_for(tmp_path, bid=29261.0, ask=29261.25)
        out = loop.manage_open_position()
        assert out["status"] == ACT.APPLIED, out
        assert len(venue.modifies) == 1
        assert venue.modifies[0]["order_id"] == T2_STOP, "wrong order modified"
        assert venue.modifies[0]["stop_price"] > T2_STOP_PX, "stop must improve"

    def test_the_advance_is_exactly_once_across_repeated_ticks(self, tmp_path):
        loop, venue, _ = loop_for(tmp_path, bid=29261.0, ask=29261.25)
        assert loop.manage_open_position()["status"] == ACT.APPLIED
        for _ in range(4):
            again = loop.manage_open_position()
            assert again["status"] == ACT.HELD
        assert len(venue.modifies) == 1

    def test_the_target_is_never_written(self, tmp_path):
        loop, venue, _ = loop_for(tmp_path, bid=29261.0, ask=29261.25)
        loop.manage_open_position()
        after = [o for o in venue.open_orders() if o["id"] == T2_TARGET][0]
        assert after["limit_price"] == T2_TARGET_PX
        assert after["parent_order_id"] == T2_ENTRY
        assert after["size"] == T2_SIZE

    def test_R_comes_from_the_fill_and_ORIGINAL_stop(self, tmp_path):
        loop, _, _ = loop_for(tmp_path, bid=29261.0, ask=29261.25)
        out = loop.manage_open_position()
        assert out["baseline"]["initial_risk_points"] == T2_R
        assert out["baseline"]["original_initial_stop"] == T2_STOP_PX


# ══ 5 · TRIGGER SIDE AND FRESHNESS ══════════════════════════════════════════
class TestTriggerAuthority:

    def test_a_long_triggers_from_the_BID_not_the_ask(self, tmp_path):
        """Ask alone across +1R must not trigger: a long exits into the bid."""
        loop, venue, _ = loop_for(tmp_path, bid=29259.0, ask=29262.0)
        out = loop.manage_open_position()
        assert out["status"] == "decision_declines"
        assert venue.modifies == []

    def test_a_stale_quote_holds(self, tmp_path):
        loop, venue, _ = loop_for(tmp_path, bid=29261.0, ask=29261.25)
        loop.ps.quote_provider.fresh = False
        out = loop.manage_open_position()
        assert out["status"] == "no_fresh_quote"
        assert venue.modifies == []


# ══ 3 · PROTECTION DEFECT -> CERTIFIED SAFETY AUTHORITY ═════════════════════
class TestProtectionDefectRouting:

    def test_a_missing_owned_stop_enters_emergency_flatten(self, tmp_path):
        """The one case where HOLD is wrong: the ORIGINAL protection is gone,
        so the reason a failed advance normally holds no longer applies."""
        only_target = [o for o in t2_children() if o["id"] == T2_TARGET]
        loop, venue, runner = loop_for(tmp_path, bid=29261.0, ask=29261.25,
                                       orders=only_target)
        out = loop.manage_open_position()
        assert out["status"] == "protection_defect"
        assert len(runner.flattens) == 1
        assert venue.modifies == [], "no stop write on a missing stop"

    def test_an_ordinary_failed_advance_does_NOT_flatten(self, tmp_path):
        """Original stop still protects the trade — never kill it."""
        loop, venue, runner = loop_for(tmp_path, bid=29261.0, ask=29261.25)

        def refuse(order_id, **kw):
            venue.modifies.append({"order_id": order_id,
                                   "stop_price": kw.get("stop_price")})
            return {"success": True}          # accepted, never lands
        venue.modify_order = refuse
        out = loop.manage_open_position()
        assert out["status"] == ACT.AMBIGUOUS
        assert runner.flattens == [], "a protected position was flattened"


# ══ 8 · RESTART ════════════════════════════════════════════════════════════
class TestRestartIntegration:

    def test_restart_with_the_original_stop_keeps_management_available(self, tmp_path):
        loop, venue, _ = loop_for(tmp_path, bid=29240.0, ask=29240.25)
        out = loop.manage_open_position()
        assert out["status"] == "decision_declines"
        assert out["baseline"]["initial_risk_points"] == T2_R

    def test_restart_after_the_effect_landed_sends_no_second_write(self, tmp_path):
        """The venue already shows break-even; a cold process must not re-send."""
        be = BE.cost_adjusted_break_even(direction="long", entry_fill_price=T2_FILL,
                                         contract=Contract(), quantity=T2_SIZE)
        loop, venue, _ = loop_for(tmp_path, bid=29261.0, ask=29261.25,
                                  stop_px=be, orders=t2_children(be))
        out = loop.manage_open_position()
        assert out["status"] in (ACT.HELD, "decision_declines")
        assert venue.modifies == []

    def test_a_manually_improved_stop_is_never_weakened(self, tmp_path):
        loop, venue, _ = loop_for(tmp_path, bid=29261.0, ask=29261.25,
                                  stop_px=29250.0, orders=t2_children(29250.0))
        out = loop.manage_open_position()
        assert out["status"] in (ACT.HELD, "decision_declines")
        assert venue.modifies == []


# ══ 12 · NO COGNITION, AND THE MISSION MUST BE LIVE ═════════════════════════
class TestManagementIsDeterministic:

    def test_no_provider_is_consulted(self, tmp_path):
        import ai_brain.narrative_brain as NB
        calls = []
        real = NB.run_narrative_brain
        NB.run_narrative_brain = lambda *a, **k: calls.append(1)
        try:
            loop, _, _ = loop_for(tmp_path, bid=29261.0, ask=29261.25)
            loop.manage_open_position()
        finally:
            NB.run_narrative_brain = real
        assert calls == []

    def test_a_terminal_mission_is_not_managed(self, tmp_path):
        loop, venue, _ = loop_for(tmp_path, bid=29261.0, ask=29261.25,
                                  state=MS.COMPLETE)
        out = loop.manage_open_position()
        assert out["status"] == "mission_not_position_open"
        assert venue.modifies == []

    def test_management_never_raises(self, tmp_path):
        loop, _, _ = loop_for(tmp_path, bid=29261.0, ask=29261.25)
        loop.ps.session = None                # catastrophic input
        out = loop.manage_open_position()
        assert out["status"] in ("error", ACT.REFUSED, "no_live_mission",
                                 "venue_unreadable_for_effect_identity")
