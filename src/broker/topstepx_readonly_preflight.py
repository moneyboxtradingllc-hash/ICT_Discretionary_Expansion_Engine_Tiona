"""TOPSTEPX-INTEGRATION — Phase 2 read-only preflight.

    python -m broker.topstepx_readonly_preflight

Proves the whole venue path short of writing: credentials load, API-key login
is accepted, the pinned account resolves uniquely and is tradable and visible,
the active MNQ contract comes from the API, both realtime hubs connect and
subscribe, reconnect restores subscriptions in order, and the true open
position / working order state is read back.

It cannot place, modify, cancel or close an order. That is enforced by
`TopstepXReadOnlySession`, not by this script's good intentions: the session
has no write methods and its transport refuses every non-allowlisted endpoint.

Every line printed and every value written to the evidence artifact passes
through the redaction layer first. The exit code is 0 only when every required
check passed.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from broker import topstepx_order_discovery as DISC
from broker.topstepx_client import (                          # noqa: E402
    TopstepXAuthError, TopstepXError, TopstepXPinError,
)
from broker.topstepx_readonly import (                        # noqa: E402
    ReadOnlyViolation, TopstepXReadOnlySession,
)
from broker import topstepx_account_role as account_role      # noqa: E402
from broker.topstepx_realtime import RealtimeError            # noqa: E402
from broker.topstepx_redaction import (                       # noqa: E402
    account_fingerprint, assert_clean, redacted_account_label,
)

# Anchored to the repository root, not the working directory. Running the
# preflight as `python -m broker.topstepx_readonly_preflight` from src/ would
# otherwise scatter evidence into src/data/ — evidence that lands somewhere
# different depending on where you stood is evidence nobody can find twice.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EVIDENCE_PATH = os.path.join(_REPO_ROOT, "data", "integration", "topstepx",
                             "readonly_preflight.json")

# Market events must be newer than this to count as fresh. Outside RTH a quiet
# feed is expected, so staleness is REPORTED as a warning rather than failing
# the run — a preflight that cannot be run in the evening is a preflight that
# does not get run.
FRESH_WINDOW_SECONDS = 90.0

_OK, _NO, _WARN = "  ok  ", " FAIL ", " WARN "


class Check:
    """One recorded preflight result. `required` drives the exit code."""

    def __init__(self, key: str, label: str, required: bool = True) -> None:
        self.key, self.label, self.required = key, label, required
        self.state, self.detail = "skipped", ""

    def ok(self, detail: str = "") -> "Check":
        self.state, self.detail = "pass", detail
        return self

    def fail(self, detail: str = "") -> "Check":
        self.state, self.detail = "fail", detail
        return self

    def warn(self, detail: str = "") -> "Check":
        self.state, self.detail = "warn", detail
        return self

    def as_dict(self) -> dict:
        return {"check": self.key, "label": self.label, "state": self.state,
                "detail": assert_clean(self.detail, f"check:{self.key}"),
                "required": self.required}


class Preflight:
    def __init__(self, session_factory=None, clock=None) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.checks: list = []
        self.artifact: dict = {}

    def _add(self, c: Check) -> Check:
        self.checks.append(c)
        state = {"pass": _OK, "fail": _NO, "warn": _WARN}.get(c.state, " skip ")
        print(f"[{state}] {c.label:<34} {assert_clean(c.detail, c.key)}")
        return c

    # ── config ────────────────────────────────────────────────────────────────
    @staticmethod
    def load_config() -> dict:
        """Read the pinning contract from the environment. Values never printed."""
        cfg = {
            "username": os.getenv("TOPSTEPX_USERNAME", "").strip(),
            "api_key": os.getenv("TOPSTEPX_API_KEY", "").strip(),
            "account_id": os.getenv("TOPSTEPX_ACCOUNT_ID", "").strip(),
            "account_name": os.getenv("TOPSTEPX_ACCOUNT_NAME", "").strip(),
            "contract": os.getenv("TOPSTEPX_CONTRACT", "MNQ").strip() or "MNQ",
            "expected_fingerprint": os.getenv("TOPSTEPX_ACCOUNT_FINGERPRINT", "").strip(),
        }
        missing = [k for k in ("username", "api_key") if not cfg[k]]
        if missing:
            raise TopstepXError(
                "missing " + ", ".join(f"TOPSTEPX_{k.upper()}" for k in missing)
                + ". Set them in .env (gitignored) — see .env.template. "
                  "Never paste them into a chat or a commit.")
        if not cfg["account_id"] and not cfg["account_name"]:
            raise TopstepXPinError(
                "no account pinned: set TOPSTEPX_ACCOUNT_ID (preferred) or "
                "TOPSTEPX_ACCOUNT_NAME. This preflight will not choose for you.")
        return cfg

    # ── run ───────────────────────────────────────────────────────────────────
    def run(self) -> int:
        started = self._clock()
        print("=" * 74)
        print("TOPSTEPX READ-ONLY PREFLIGHT — structurally write-incapable")
        print("=" * 74)

        try:
            cfg = self.load_config()
        except (TopstepXError, TopstepXPinError) as exc:
            self._add(Check("secrets", "local secret loading").fail(str(exc)))
            return self._finish(started, blocker="configuration")
        self._add(Check("secrets", "local secret loading").ok(
            "credentials present; values never read into output"))

        session = (self._session_factory() if self._session_factory
                   else TopstepXReadOnlySession(cfg["username"], cfg["api_key"]))

        try:
            self._add(Check("write_surface", "write surface absent").ok(
                f"{len(session.assert_no_write_surface())} write methods verified absent"))
        except ReadOnlyViolation as exc:
            self._add(Check("write_surface", "write surface absent").fail(str(exc)))
            return self._finish(started, blocker="read-only guarantee")

        # 1-6 auth
        try:
            auth = session.authenticate()
            self._add(Check("auth", "API-key authentication").ok("PASS"))
            self._add(Check("token", "JWT received").ok(
                f"non-empty {auth['token_type']}, expires {auth['expires_at']}"))
        except TopstepXAuthError as exc:
            self._add(Check("auth", "API-key authentication").fail(str(exc)))
            return self._finish(started, session=session, blocker="authentication")

        # 7-10 account pinning
        try:
            acct = session.pin(account_id=cfg["account_id"] or None,
                               account_name=cfg["account_name"],
                               expected_fingerprint=cfg["expected_fingerprint"])
            fp = account_fingerprint(acct.id, acct.name)
            self._add(Check("account_pin", "account pinned uniquely").ok(
                f"{redacted_account_label(acct.name)} {fp}"))
            self._add(Check("account_trade", "account canTrade").ok("true"))
            self._add(Check("account_visible", "account isVisible").ok("true"))
            # TOPSTEPX-COMBINE-ROLE: venue environment and account role are two
            # facts. Rendering `simulated=true` as "practice" told the operator
            # his Trading Combine was a throwaway account. Never again.
            role = account_role.describe(acct.simulated)
            self._add(Check("venue_environment", "venue environment", required=False).ok(
                role["venue_environment"]))
            self._add(Check("account_role", "operator-declared role", required=False).ok(
                role["operator_declared_account_role"]))
        except (TopstepXPinError, TopstepXError) as exc:
            self._add(Check("account_pin", "account pinned uniquely").fail(str(exc)))
            return self._finish(started, session=session, blocker="account pinning")

        # 11-12 contract
        try:
            c = session.resolve_contract(cfg["contract"])
            self._add(Check("contract", "active contract from API").ok(
                f"{c.id} ({c.name}) — {c.description}"))
            self._add(Check("contract_meta", "contract metadata valid").ok(
                f"tick={c.tick_size} value=${c.tick_value}/tick active={c.active}"))
        except TopstepXError as exc:
            self._add(Check("contract", "active contract from API").fail(str(exc)))
            return self._finish(started, session=session, blocker="contract discovery")

        # 22-25 REST state
        try:
            positions = session.open_positions()
            # The operator acts on this report, so it says WHICH SURFACE it
            # read. `searchOpen` omits Suspended bracket children by contract.
            found = DISC.discover_orders(session)
            orders = found["working"] or []
            self._add(Check("positions", "open-position search").ok(
                f"{len(positions)} open position(s)"))
            self._add(Check("orders", "order discovery").ok(
                f"{len(orders)} working order(s) via {found['source']}")
                if found["complete"] else
                Check("orders", "order discovery").fail(
                    f"{len(orders)} seen, but the view is {found['source']}"))
            self._add(Check("flat", "account flat?").ok(
                "FLAT" if not positions else "NOT FLAT"))
            self._add(Check("working", "working orders?").ok(
                "none" if not orders else f"{len(orders)} present")
                if found["complete"] else
                Check("working", "working orders?").fail(
                    "absence not proven from an incomplete order view"))
        except TopstepXError as exc:
            self._add(Check("positions", "open-position search").fail(str(exc)))
            return self._finish(started, session=session, blocker="state read")

        # 13-21 realtime
        self._realtime(session)

        return self._finish(started, session=session)

    def _realtime(self, session) -> None:
        try:
            hub = session.connect_user_hub()
            self._add(Check("user_hub", "user hub connected").ok("handshake ok"))
            self._add(Check("user_subs", "user subscriptions").ok(
                ", ".join(hub.health.subscriptions)))
            replayed = hub.reconnect()
            self._add(Check("user_reconnect", "reconnect resubscribes in order").ok(
                " -> ".join(replayed)))
            hub.pump(max_messages=4)
        except RealtimeError as exc:
            self._add(Check("user_hub", "user hub connected").fail(str(exc)))

        try:
            mhub = session.connect_market_hub()
            self._add(Check("market_hub", "market hub connected").ok("handshake ok"))
            self._add(Check("market_subs", "MNQ quote/trade subscriptions").ok(
                ", ".join(mhub.health.subscriptions)))
            mhub.pump(max_messages=8)
            age = mhub.health.age_seconds(self._clock())
            fresh = Check("market_fresh", "market data freshness", required=False)
            if age is None:
                self._add(fresh.warn("no events yet — market may be closed"))
            elif age > FRESH_WINDOW_SECONDS:
                self._add(fresh.warn(f"last event {age:.0f}s ago (> {FRESH_WINDOW_SECONDS:.0f}s)"))
            else:
                self._add(fresh.ok(f"last event {age:.1f}s ago"))
        except RealtimeError as exc:
            self._add(Check("market_hub", "market hub connected").fail(str(exc)))

    # ── evidence ──────────────────────────────────────────────────────────────
    def _finish(self, started, session=None, blocker: Optional[str] = None) -> int:
        ended = self._clock()
        eastern = ended.astimezone(timezone(timedelta(hours=-4)))
        failed = [c for c in self.checks if c.required and c.state == "fail"]

        zero_write = (session.zero_write_proof() if session is not None
                      else {"write_calls_made": 0, "write_attempts": [],
                            "endpoints_called": [], "note": "no session constructed"})

        self.artifact = {
            "mission": "TOPSTEPX-INTEGRATION — Phase 2 read-only preflight",
            "generated_at_utc": ended.isoformat(),
            "generated_at_eastern": eastern.isoformat(),
            "duration_seconds": round((ended - started).total_seconds(), 2),
            "verdict": "BLOCKED" if blocker else ("PASS" if not failed else "FAIL"),
            "blocker": blocker,
            "checks": [c.as_dict() for c in self.checks],
            "zero_write_proof": zero_write,
            "stream_health": {
                "user_hub": session.user_hub.describe() if session and session.user_hub else None,
                "market_hub": session.market_hub.describe() if session and session.market_hub else None,
            },
            "account": self._account_evidence(session),
            "contract": self._contract_evidence(session),
            "secret_redaction_proof": {
                "secrets_in_artifact": 0,
                "method": "broker.topstepx_redaction.assert_clean on every field",
                "username_logged": False,
                "api_key_logged": False,
                "jwt_logged": False,
            },
        }

        os.makedirs(os.path.dirname(EVIDENCE_PATH), exist_ok=True)
        body = assert_clean(json.dumps(self.artifact, indent=2, default=str), "artifact")
        with open(EVIDENCE_PATH, "w", encoding="utf-8") as fh:
            fh.write(body)

        print("-" * 74)
        print(f"VERDICT: {self.artifact['verdict']}"
              + (f"  (blocker: {blocker})" if blocker else ""))
        print(f"evidence: {EVIDENCE_PATH}")
        print(f"write calls made: {zero_write.get('write_calls_made')}   "
              f"write attempts refused: {len(zero_write.get('write_attempts') or [])}")
        print("=" * 74)
        return 1 if (failed or blocker) else 0

    @staticmethod
    def _account_evidence(session) -> Optional[dict]:
        if session is None or getattr(session, "account", None) is None:
            return None
        a = session.account
        return {"fingerprint": account_fingerprint(a.id, a.name),
                "label": redacted_account_label(a.name),
                "can_trade": a.can_trade, "is_visible": a.is_visible,
                "simulated": a.simulated,
                **account_role.describe(a.simulated),
                "id": "[REDACTED]", "name": "[REDACTED]"}

    @staticmethod
    def _contract_evidence(session) -> Optional[dict]:
        if session is None or getattr(session, "contract", None) is None:
            return None
        c = session.contract
        return {"id": c.id, "name": c.name, "description": c.description,
                "tick_size": c.tick_size, "tick_value": c.tick_value,
                "active": c.active}


def main(argv=None) -> int:
    try:
        return Preflight().run()
    except ReadOnlyViolation as exc:
        print(f"\nREAD-ONLY VIOLATION: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
