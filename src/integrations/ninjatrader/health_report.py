"""Phase 15 — NinjaTrader integration health report + launcher banner.

Pure assembly from supplied evidence. It NEVER claims GUI state it cannot see;
unknown fields are reported as such. The launcher banner is unambiguous.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

from integrations.ninjatrader import (
    INTEGRATION_VERSION, INTEGRATION_ERA, MAX_CONTRACTS_FOUNDATION,
    AUTOMATED_ORDER_SUBMISSION_ARMED,
)


@dataclass
class IntegrationHealth:
    ninjatrader_installed: Optional[bool] = None
    ninjatrader_running: Optional[bool] = None
    version: str = "unknown"
    interface_selected: str = "ninjascript_bridge"
    interface_connected: Optional[bool] = None
    data_connection_name: str = "unknown"
    sim_account_visible: Optional[bool] = None
    global_sim_mode_user_confirmed: Optional[bool] = None
    active_mnq_expiry: str = "unresolved"
    tick_size: Optional[float] = None
    point_value: Optional[float] = None
    tick_value: Optional[float] = None
    quote_freshness_seconds: Optional[float] = None
    latest_completed_bar: str = "none"
    warmup_bar_count: int = 0
    position_state: str = "unknown"
    working_order_count: Optional[int] = None
    reconciliation_state: str = "unreconciled"
    order_submission_armed: bool = AUTOMATED_ORDER_SUBMISSION_ARMED
    last_error: str = ""
    last_heartbeat: str = "none"
    integration_version: str = INTEGRATION_VERSION
    integration_era: str = INTEGRATION_ERA

    def to_dict(self) -> dict:
        return asdict(self)


def launcher_banner(active_mnq_expiry: str = "<unresolved>") -> str:
    """The mandatory, unambiguous startup banner."""
    armed = "ENABLED" if AUTOMATED_ORDER_SUBMISSION_ARMED else "DISABLED"
    return "\n".join([
        "======================================================================",
        f"NINJATRADER ACCOUNT: DEMO8458533",
        f"INSTRUMENT: {active_mnq_expiry}",
        f"AUTOMATED ORDER SUBMISSION: {armed}",
        f"MAX CONTRACTS: {MAX_CONTRACTS_FOUNDATION}",
        f"LIVE ACCOUNTS: FORBIDDEN",
        f"OPENAI CALLS: DISABLED FOR INTEGRATION TEST",
        "======================================================================",
    ])
