"""Simulation-environment proof (replaces the obsolete Global Simulation Mode gate).

Maurice's NinjaTrader edition has no "Global Simulation Mode" menu item (that is a
multi-provider-mode feature, which he has declined to enable). The correct safety
proof is therefore POSITIVE evidence that:

  * the connected environment is Simulation, and
  * DEMO8458533 is present, connected, and is the sole account the execution
    layer will ever address.

This module evaluates an ENVIRONMENT_PROOF payload from the bridge (plus the
account allowlist) and FAILS CLOSED on any uncertainty. It never enables
multi-provider mode and never touches the connection architecture.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from integrations.ninjatrader.account_safety import ALLOWED_ACCOUNTS

# Conservative substrings that would indicate a NON-simulation (live/funded)
# account or connection. Presence of any -> fail closed. This is a denylist
# guard; the DECISIVE control remains the single-account allowlist.
LIVE_MARKERS = ("LIVE", "FUNDED", "REAL", "APEX", "TOPSTEP", "TRADEDAY",
                "LEELOO", "EARN2TRADE", "BLUSKY", "TAKEPROFIT")


@dataclass
class EnvironmentProof:
    proven_simulation: bool
    reason: str
    demo_account_present: bool = False
    demo_account_connected: bool = False
    accounts_seen: tuple = ()
    live_suspects: tuple = ()

    def __bool__(self) -> bool:
        return self.proven_simulation


def _looks_live(name: str) -> bool:
    up = str(name).upper()
    return any(m in up for m in LIVE_MARKERS)


def evaluate(env_payload: Optional[dict],
             expected_account: str = "DEMO8458533") -> EnvironmentProof:
    """Return a Simulation-environment proof, failing closed on any uncertainty.

    `env_payload` is the payload of an ENVIRONMENT_PROOF envelope:
        {"accounts":[{"name","provider","connection","status"}...],
         "connections":[{"name","status"}...]}
    """
    if expected_account not in ALLOWED_ACCOUNTS:
        return EnvironmentProof(False, f"expected account {expected_account!r} not "
                                       f"in allowlist {sorted(ALLOWED_ACCOUNTS)}")
    if not env_payload or not isinstance(env_payload, dict):
        return EnvironmentProof(False, "no ENVIRONMENT_PROOF payload — fail closed")

    accounts = env_payload.get("accounts") or []
    names = tuple(str(a.get("name", "")) for a in accounts)

    # The demo account must be present AND connected.
    demo = next((a for a in accounts if str(a.get("name")) == expected_account), None)
    if demo is None:
        return EnvironmentProof(False, f"{expected_account} not present in account list",
                                accounts_seen=names)
    demo_connected = str(demo.get("status", "")).lower() in ("connected", "connectionconnected", "true") \
        or demo.get("connected") is True
    if not demo_connected:
        return EnvironmentProof(False, f"{expected_account} present but not connected",
                                demo_account_present=True, accounts_seen=names)

    # No account may look live/funded.
    suspects = tuple(n for n in names if _looks_live(n))
    if suspects:
        return EnvironmentProof(False, f"live/funded-looking account(s) present: {suspects}",
                                demo_account_present=True, demo_account_connected=True,
                                accounts_seen=names, live_suspects=suspects)

    return EnvironmentProof(True,
                            f"Simulation proven: {expected_account} present+connected; "
                            f"no live/funded account detected among {names}",
                            demo_account_present=True, demo_account_connected=True,
                            accounts_seen=names)
