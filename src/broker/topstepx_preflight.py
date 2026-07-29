"""TopstepX preflight — prove the connection before anything can trade.

Run this first, and after any credential or account change:

    python -m broker.topstepx_preflight

It makes real calls and changes nothing: authenticate, list accounts, resolve the
configured account and contract, pull closed bars, and read open positions. No
order is placed and none can be — this module never imports the order path.

The point is that a failure here is legible. Without it, a wrong account name or
an inactive API subscription looks exactly like a bot that never finds a setup.
"""
from __future__ import annotations

import sys

from dotenv import load_dotenv

load_dotenv()

from broker.base import NotConnectedError                    # noqa: E402
from broker.topstepx_adapter import (                        # noqa: E402
    TopstepXBrokerAdapter, TopstepXConfigError, load_topstepx_config,
)
from broker.topstepx_client import TopstepXAuthError, TopstepXError  # noqa: E402

_OK, _NO, _WARN = "  ok  ", " FAIL ", " WARN "


def _line(state: str, label: str, detail: str = "") -> None:
    print(f"[{state}] {label:<28} {detail}")


def main(argv=None) -> int:
    print("=" * 72)
    print("TOPSTEPX PREFLIGHT - read-only. No order path is imported.")
    print("=" * 72)

    try:
        cfg = load_topstepx_config()
    except TopstepXConfigError as exc:
        _line(_NO, "configuration")
        print(f"\n{exc}\n")
        return 1
    _line(_OK, "configuration", f"user={cfg['username']} account={cfg['account_name']!r} "
                                f"contract={cfg['contract']!r}")

    adapter = TopstepXBrokerAdapter()
    try:
        account = adapter.connect()
    except TopstepXAuthError as exc:
        _line(_NO, "authentication")
        print(f"\n{exc}\n")
        print("Check: the key is from TopstepX -> Settings -> API, the username is your")
        print("TopstepX login (not your email), and the API add-on is active.")
        return 1
    except NotConnectedError as exc:
        _line(_NO, "account permitted")
        print(f"\n{exc}\n")
        return 1
    except TopstepXError as exc:
        _line(_NO, "account / contract")
        print(f"\n{exc}\n")
        return 1

    _line(_OK, "authentication", "session established")
    _line(_OK, "account resolved",
          f"{account.name} (id={account.id})  balance=${account.balance:,.2f}")
    _line(_OK if account.simulated else _WARN, "account type",
          "SIMULATED (practice)" if account.simulated
          else "*** NOT SIMULATED - REAL MONEY ***")

    state = adapter.get_account()
    _line(_OK, "contract resolved",
          f"{state['contract_id']}  tick={state['tick_size']} "
          f"(${state['tick_value']}/tick)")

    try:
        bars = adapter.bars_1m(minutes_back=180)
    except TopstepXError as exc:
        _line(_NO, "market data", str(exc))
        return 1
    if not bars:
        _line(_WARN, "market data", "0 bars returned - market may be closed")
    else:
        _line(_OK, "market data",
              f"{len(bars)} closed 1m bars, last {bars[-1]['timestamp']} "
              f"close={bars[-1]['close']}")

    pos = adapter.get_position()
    _line(_OK, "positions",
          "flat" if pos.get("flat") else f"{pos['side']} {pos['size']} @ {pos['avg_price']}")

    print("-" * 72)
    print("CONNECTION IS GOOD. Two things this does NOT establish:")
    print()
    print("  1. TRAILING DRAWDOWN. Topstep enforces a max loss that follows peak")
    print("     equity. This bot models a static daily ceiling and has no trailing")
    print("     concept, so it can sit well inside its own limits while the account")
    print("     is one trade from being closed. Not fixed by this adapter.")
    print()
    print("  2. PERMISSION TO AUTOMATE. Confirm with Topstep that API/automated")
    print("     trading is allowed on your account type. A rule breach ends an")
    print("     evaluation regardless of whether the strategy was profitable.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
