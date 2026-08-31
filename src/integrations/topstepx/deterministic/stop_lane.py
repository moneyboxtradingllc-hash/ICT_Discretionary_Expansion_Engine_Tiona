"""Stop the deterministic lane cleanly.

Sets no-new-entries (the STOP file, written by the .ps1), reconciles, flattens
any open protected position per the manual-stop/EOD doctrine, cancels residual
orders after flat, and ends the session state.
"""
from __future__ import annotations

import time

from integrations.topstepx.deterministic.topstepx_lane_client import (
    TopstepXLaneClient)
from integrations.topstepx.deterministic import ACCOUNT, INSTRUMENT
from integrations.topstepx.deterministic.session import SessionAuthority, STOPPED_MANUAL


def main():
    session = SessionAuthority.load() or SessionAuthority()
    session.stop_new_entries(STOPPED_MANUAL)

    # LUNA-TOPSTEPX-ONLY: the NinjaTrader bridge is gone. This client
    # deliberately presents the SAME surface (connect/position/
    # order_summary/flatten/close), so the manual stop path keeps its
    # exact behaviour with TopstepX underneath.
    c = TopstepXLaneClient()
    if not c.connect():
        print("stop_lane: bridge not connected; STOP flag set, session marked stopped.")
        return
    try:
        pos = c.position(INSTRUMENT)
        orders = c.order_summary()
        print(f"stop_lane: position={pos} orders={orders}")
        if pos.get("known") and int(pos.get("qty", 0)) != 0:
            print("stop_lane: flattening open position + cancelling residual orders")
            flat = c.flatten(INSTRUMENT)   # cancels working orders then flattens
            print(f"stop_lane: flatten -> {flat}")
            time.sleep(1.0)
        elif orders.get("working_order_count"):
            c.flatten(INSTRUMENT)          # cancel residual working orders while flat
        pos2 = c.position(INSTRUMENT)
        orders2 = c.order_summary()
        session.apply_reconciliation(pos2, orders2)
        print(f"stop_lane: final position={pos2} orders={orders2} state={session.state}")
    finally:
        c.close()
    print("DETERMINISTIC_MNQ_SIM_ONLY: STOPPED")


if __name__ == "__main__":
    main()
