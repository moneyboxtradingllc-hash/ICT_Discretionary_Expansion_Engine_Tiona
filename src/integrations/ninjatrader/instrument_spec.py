"""Phase 5 — Centralized MNQ instrument specification.

ONE source of truth for the MNQ contract. Every other module imports these
values; none of them re-declare tick size, point value, or quantity ceilings.

The physical constants (point value $2.00, tick 0.25, tick value $0.50) are
NOT trusted merely because the mission states them. They are asserted for
internal consistency here and MUST be reconciled against NinjaTrader's loaded
MasterInstrument metadata (INSTRUMENT_METADATA envelope) before any order path
is considered verified. `reconcile_with_platform` performs that check.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

from integrations.ninjatrader import MAX_CONTRACTS_FOUNDATION

CANONICAL_SYMBOL = "MNQ"
DENIED_ROOTS = ("NQ",)          # full-size E-mini Nasdaq-100 — explicitly denied
EXCHANGE = "CME"
CURRENCY = "USD"
SESSION_TIMEZONE = "America/New_York"

# Expected MNQ physical constants (to be VERIFIED against platform metadata).
EXPECTED_TICK_SIZE = 0.25       # index points
EXPECTED_POINT_VALUE = 2.00     # USD per index point per contract
EXPECTED_TICK_VALUE = 0.50      # USD per tick per contract  (= tick_size * point_value)


class InstrumentSpecError(ValueError):
    """Raised when an instrument spec is internally inconsistent or unsafe."""


def _almost_equal(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(float(a) - float(b)) <= tol


@dataclass
class InstrumentSpec:
    """A fully-resolved, execution-ready MNQ contract specification.

    provider_symbol and ninjatrader_name are recorded SEPARATELY from the
    canonical symbol so that a research/continuous symbol can never be confused
    with the exact tradable expiry.
    """
    canonical_symbol: str = CANONICAL_SYMBOL
    provider_symbol: str = ""            # symbol used to request data
    ninjatrader_name: str = ""           # exact NT instrument display name, e.g. "MNQ 09-26"
    expiry: str = ""                     # explicit contract expiry code, e.g. "2026-09" / "09-26"
    exchange: str = EXCHANGE
    currency: str = CURRENCY
    tick_size: float = EXPECTED_TICK_SIZE
    point_value: float = EXPECTED_POINT_VALUE
    tick_value: float = EXPECTED_TICK_VALUE
    quantity_increment: int = 1
    minimum_quantity: int = 1
    maximum_quantity: int = MAX_CONTRACTS_FOUNDATION
    session_template: str = "rth_0930_1130_ET"
    timezone: str = SESSION_TIMEZONE
    session_identifier: str = "MNQ_RTH"
    resolver_provenance: str = ""        # how the expiry was resolved
    rollover_state: str = "unknown"      # active | rollover_window | expired | unknown
    data_connection: str = ""            # NT data connection name
    order_connection: str = ""           # NT order routing (Sim101)
    metadata_verified: bool = False      # True only after reconcile_with_platform passes

    # ── internal consistency ────────────────────────────────────────────────
    def validate(self) -> list:
        """Return a list of problems (empty = internally valid). Never raises."""
        problems = []
        if self.canonical_symbol != CANONICAL_SYMBOL:
            problems.append(f"canonical_symbol must be {CANONICAL_SYMBOL!r}")
        # NQ must never masquerade as MNQ.
        upper_names = [str(self.ninjatrader_name).upper(), str(self.provider_symbol).upper()]
        for nm in upper_names:
            root = nm.split(" ")[0].strip()
            if root in DENIED_ROOTS:
                problems.append(f"denied full-size root {root!r} present in {nm!r}")
        if self.tick_size <= 0:
            problems.append("tick_size must be > 0")
        if self.point_value <= 0:
            problems.append("point_value must be > 0")
        # tick_value must equal tick_size * point_value.
        if not _almost_equal(self.tick_value, self.tick_size * self.point_value):
            problems.append(
                f"tick_value {self.tick_value} != tick_size*point_value "
                f"{self.tick_size * self.point_value}")
        if self.quantity_increment != 1:
            problems.append("quantity_increment must be 1 (whole contracts)")
        if self.minimum_quantity < 1:
            problems.append("minimum_quantity must be >= 1")
        if self.maximum_quantity > MAX_CONTRACTS_FOUNDATION:
            problems.append(
                f"maximum_quantity {self.maximum_quantity} exceeds foundation ceiling "
                f"{MAX_CONTRACTS_FOUNDATION}")
        if self.maximum_quantity < self.minimum_quantity:
            problems.append("maximum_quantity < minimum_quantity")
        if not self.expiry:
            problems.append("expiry must be explicit (blank expiry is not tradable)")
        if self.rollover_state == "expired":
            problems.append("contract is expired")
        return problems

    def is_valid(self) -> bool:
        return not self.validate()

    def assert_valid(self) -> "InstrumentSpec":
        problems = self.validate()
        if problems:
            raise InstrumentSpecError("; ".join(problems))
        return self

    # ── platform reconciliation ─────────────────────────────────────────────
    def reconcile_with_platform(self, platform_meta: dict) -> dict:
        """Compare declared constants against NinjaTrader MasterInstrument metadata.

        platform_meta is the payload of an INSTRUMENT_METADATA envelope, expected
        to carry: tick_size, point_value, (optional) currency, instrument_name,
        expiry. Returns a report dict; sets metadata_verified only when the tick
        size AND point value match and the resolved instrument is MNQ (not NQ).
        """
        report = {"matches": True, "mismatches": [], "checked": {}}

        def _check(name, declared, actual, comparator=_almost_equal):
            report["checked"][name] = {"declared": declared, "platform": actual}
            if actual is None:
                report["matches"] = False
                report["mismatches"].append(f"{name}: platform value missing")
                return
            if not comparator(declared, actual):
                report["matches"] = False
                report["mismatches"].append(
                    f"{name}: declared {declared} != platform {actual}")

        _check("tick_size", self.tick_size, platform_meta.get("tick_size"))
        _check("point_value", self.point_value, platform_meta.get("point_value"))

        pv = platform_meta.get("point_value")
        ts = platform_meta.get("tick_size")
        if pv is not None and ts is not None:
            _check("tick_value", self.tick_value, ts * pv)

        # Instrument identity: platform name must be MNQ and must not be NQ.
        pname = str(platform_meta.get("instrument_name", "")).upper()
        if pname:
            root = pname.split(" ")[0].strip()
            report["checked"]["instrument_root"] = {"platform": root}
            if root in DENIED_ROOTS:
                report["matches"] = False
                report["mismatches"].append(f"platform instrument root {root!r} is DENIED")
            elif root != CANONICAL_SYMBOL:
                report["matches"] = False
                report["mismatches"].append(
                    f"platform instrument root {root!r} is not {CANONICAL_SYMBOL!r}")

        self.metadata_verified = report["matches"] and self.is_valid()
        report["metadata_verified"] = self.metadata_verified
        return report

    def to_dict(self) -> dict:
        return asdict(self)


def default_unresolved_spec() -> InstrumentSpec:
    """A spec skeleton with no expiry. Intentionally INVALID until an expiry is
    resolved by contract_resolver — proves the system fails closed on a blank
    contract."""
    return InstrumentSpec()
