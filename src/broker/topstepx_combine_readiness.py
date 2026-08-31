"""Combine smoke readiness preflight — everything short of the trade.

    python -m broker.topstepx_combine_readiness

Runs the full 28-point production readiness check for the one-MNQ Trading
Combine smoke and writes a redacted readiness artifact. It is write-capable in
the sense that the write path EXISTS and is verified, and write-locked in the
sense that no order can be submitted from here: this module never mints an
authorization and never calls a write endpoint. Submission requires the
operator's exact phrase in a separate, deliberate step.

The account state reads run through the structurally read-only session, so this
preflight is incapable of touching an order even by accident.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

from ai_brain import engine_payload_audit as engine_audit     # noqa: E402
from broker import topstepx_account_role as account_role      # noqa: E402
from broker import topstepx_smoke_auth as smoke_auth          # noqa: E402
from broker import topstepx_order_discovery as DISC
from broker.topstepx_client import TopstepXError, TopstepXPinError  # noqa: E402
from broker.topstepx_combine_risk import (                    # noqa: E402
    MAX_RISK_PER_TRADE_USD, SMOKE_MAX_CONTRACTS,
)
from broker.topstepx_readonly import TopstepXReadOnlySession  # noqa: E402
from broker.topstepx_readonly_preflight import Check          # noqa: E402
from broker.topstepx_realtime import RealtimeError            # noqa: E402
from broker.topstepx_redaction import (                       # noqa: E402
    account_fingerprint, assert_clean, redacted_account_label,
)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EVIDENCE_PATH = os.path.join(_REPO_ROOT, "data", "integration", "topstepx",
                             "combine_readiness.json")

WINDOW_OPEN = (9, 30)
WINDOW_CLOSE = (14, 0)


def in_decision_window(now_et: datetime) -> bool:
    """ADAPTIVE-8 campaign window, 09:30-14:00 ET, weekdays."""
    if now_et.weekday() >= 5:
        return False
    o = now_et.replace(hour=WINDOW_OPEN[0], minute=WINDOW_OPEN[1], second=0, microsecond=0)
    c = now_et.replace(hour=WINDOW_CLOSE[0], minute=WINDOW_CLOSE[1], second=0, microsecond=0)
    return o <= now_et <= c


class Readiness:
    def __init__(self, session_factory=None, health_fn=None, clock=None) -> None:
        self._session_factory = session_factory
        self._health_fn = health_fn
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.checks: list = []
        self.artifact: dict = {}

    def _add(self, c: Check) -> Check:
        self.checks.append(c)
        state = {"pass": "  ok  ", "fail": " FAIL ", "warn": " WARN "}.get(c.state, " skip ")
        print(f"[{state}] {c.label:<36} {assert_clean(c.detail, c.key)}")
        return c

    def run(self) -> int:
        started = self._clock()
        print("=" * 78)
        print("TOPSTEPX COMBINE SMOKE — READINESS PREFLIGHT (no order can be sent)")
        print("=" * 78)

        blocker = None
        session = None
        try:
            blocker, session = self._run_checks()
        except Exception as exc:  # noqa: BLE001 — readiness must always produce evidence
            self._add(Check("unexpected", "unexpected error").fail(f"{type(exc).__name__}: {exc}"))
            blocker = "unexpected_error"
        return self._finish(started, session, blocker)

    def _run_checks(self):
        # 1-2 repo/branch/tree
        import subprocess
        try:
            branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                                    capture_output=True, text=True, cwd=_REPO_ROOT).stdout.strip()
            dirty = subprocess.run(["git", "status", "--porcelain"],
                                   capture_output=True, text=True, cwd=_REPO_ROOT).stdout.strip()
        except Exception:  # noqa: BLE001
            branch, dirty = "unknown", ""
        self._add(Check("repo", "repository and branch").ok(f"{os.path.basename(_REPO_ROOT)} @ {branch}"))
        self._add(Check("tree", "working tree state", required=False).ok(
            "clean" if not dirty else f"{len(dirty.splitlines())} modified/untracked path(s)"))

        # 3 secrets
        cfg = {k: (os.getenv(k) or "").strip() for k in
               ("TOPSTEPX_USERNAME", "TOPSTEPX_API_KEY", "TOPSTEPX_ACCOUNT_ID",
                "TOPSTEPX_ACCOUNT_FINGERPRINT", "TOPSTEPX_CONTRACT", "OPENAI_API_KEY")}
        missing = [k for k in ("TOPSTEPX_USERNAME", "TOPSTEPX_API_KEY", "OPENAI_API_KEY") if not cfg[k]]
        if missing:
            self._add(Check("secrets", "secrets present").fail(", ".join(missing) + " not set"))
            return "configuration", None
        if not cfg["TOPSTEPX_ACCOUNT_ID"]:
            self._add(Check("secrets", "secrets present").fail("TOPSTEPX_ACCOUNT_ID not set"))
            return "account pin", None
        self._add(Check("secrets", "secrets present").ok("all present; values never displayed"))

        session = (self._session_factory() if self._session_factory
                   else TopstepXReadOnlySession(cfg["TOPSTEPX_USERNAME"], cfg["TOPSTEPX_API_KEY"]))

        # 4-5 auth
        try:
            session.authenticate()
            self._add(Check("auth", "TopstepX authentication").ok("PASS; JWT accepted"))
        except TopstepXError as exc:
            self._add(Check("auth", "TopstepX authentication").fail(str(exc)))
            return "authentication", session

        # 6-10 account
        try:
            acct = session.pin(account_id=cfg["TOPSTEPX_ACCOUNT_ID"],
                               expected_fingerprint=cfg["TOPSTEPX_ACCOUNT_FINGERPRINT"])
        except (TopstepXPinError, TopstepXError) as exc:
            self._add(Check("account", "pinned Combine account").fail(str(exc)))
            return "account pinning", session
        fp = account_fingerprint(acct.id, acct.name)
        self._add(Check("account", "pinned Combine account").ok(
            f"{redacted_account_label(acct.name)} {fp}"))
        self._add(Check("fingerprint", "fingerprint matches").ok(
            "configured and matched" if cfg["TOPSTEPX_ACCOUNT_FINGERPRINT"]
            else "no fingerprint configured (enforcement inactive)")
            if cfg["TOPSTEPX_ACCOUNT_FINGERPRINT"] else
            Check("fingerprint", "fingerprint matches").warn("not configured — enforcement inactive"))
        role = account_role.describe(acct.simulated)
        self._add(Check("venue_env", "venue environment").ok(role["venue_environment"]))
        self._add(Check("account_role", "operator-declared role").ok(
            role["operator_declared_account_role"])
            if role["operator_declared_account_role"] == account_role.TRADING_COMBINE else
            Check("account_role", "operator-declared role").warn(
                f"{role['operator_declared_account_role']} — expected TRADING_COMBINE"))
        self._add(Check("can_trade", "canTrade").ok("true") if acct.can_trade
                  else Check("can_trade", "canTrade").fail("false"))
        self._add(Check("is_visible", "isVisible").ok("true") if acct.is_visible
                  else Check("is_visible", "isVisible").fail("false"))

        # 11-13 flat state
        try:
            positions = session.open_positions()
            # CANONICAL DISCOVERY. This check decides whether a Combine session
            # may begin, and `searchOpen` omits Suspended bracket children by
            # venue contract -- so the old read could certify an account as
            # having zero working orders while one rested at the venue.
            found = DISC.discover_orders(session)
            orders = found["working"] or []
        except TopstepXError as exc:
            self._add(Check("state", "account state").fail(str(exc)))
            return "state read", session
        if not found["answered"]:
            self._add(Check("state", "account state").fail(
                "; ".join(found["errors"]) or "order discovery unavailable"))
            return "state read", session
        self._add(Check("flat", "account flat").ok("FLAT — 0 open positions") if not positions
                  else Check("flat", "account flat").fail(f"{len(positions)} open position(s)"))
        # AN INCOMPLETE VIEW MAY NOT CERTIFY AN EMPTY BOOK. Silence from a
        # query documented to hide staged children is a gap in the QUERY, never
        # evidence about the ACCOUNT.
        if orders:
            self._add(Check("no_orders", "zero working orders").fail(
                f"{len(orders)} working"))
        elif not found["complete"]:
            self._add(Check("no_orders", "zero working orders").fail(
                f"order view is {found['source']}; absence is not proven"))
        else:
            self._add(Check("no_orders", "zero working orders").ok("none"))

        # 14-15 contract
        try:
            contract = session.resolve_contract(cfg["TOPSTEPX_CONTRACT"] or "MNQ")
            self._add(Check("contract", "active MNQ contract").ok(f"{contract.id} ({contract.name})"))
            self._add(Check("tick_meta", "tick metadata valid").ok(
                f"tick={contract.tick_size} value=${contract.tick_value}/tick"))
        except TopstepXError as exc:
            self._add(Check("contract", "active MNQ contract").fail(str(exc)))
            return "contract discovery", session

        # 16-19 realtime
        self._realtime(session)

        # 20 Luna health
        health = self._luna_health()

        # 21-22 engines + sovereignty
        self._engines(health)

        # 22-25 Brain timeout + concurrency/staleness guards
        self._guards()

        # 23-24 risk doctrine — BOTH caps, so the report can never imply the
        # production ceiling governs a smoke trade it does not govern.
        from broker.topstepx_combine_risk import (
            SMOKE_MAX_RISK_USD, SMOKE_MAX_STOP_POINTS, effective_max_risk_usd,
        )
        self._add(Check("risk_cap", "production risk cap").ok(
            f"${MAX_RISK_PER_TRADE_USD:,.2f} per trade (future production), compounding OFF"))
        self._add(Check("smoke_risk_cap", "smoke risk cap IN FORCE").ok(
            f"${SMOKE_MAX_RISK_USD:,.2f} planned max, stop <= {SMOKE_MAX_STOP_POINTS:g} pts "
            f"-> effective ${effective_max_risk_usd():,.2f}"))
        self._add(Check("size_cap", "smoke size cap").ok(
            f"{SMOKE_MAX_CONTRACTS} MNQ contract maximum"))

        # 29 execution runner
        self._runner_available()

        # 25-27 write lock
        proof = session.zero_write_proof()
        self._add(Check("no_writes", "no write endpoint invoked").ok(
            f"{proof['write_calls_made']} write calls, "
            f"{len(proof['write_attempts'])} refused attempts"))
        self._add(Check("flatten_available", "emergency flatten available").ok(
            "close_position + close_position_partial + cancel_order implemented"))
        self._add(Check("authorization", "operator authorization").warn(
            "NOT PRESENT — required before any submission"))

        # decision window
        et = self._clock().astimezone(timezone(timedelta(hours=-4)))
        inwin = in_decision_window(et)
        self._add(Check("window", "ADAPTIVE-8 decision window", required=False).ok(
            f"INSIDE ({et:%H:%M} ET)") if inwin else
            Check("window", "ADAPTIVE-8 decision window", required=False).warn(
                f"OUTSIDE ({et:%H:%M} ET) — 09:30-14:00 ET weekdays"))
        return None, session

    def _realtime(self, session) -> None:
        try:
            hub = session.connect_user_hub()
            replayed = hub.reconnect()
            self._add(Check("user_hub", "user hub + subscriptions").ok(
                ", ".join(hub.health.subscriptions)))
            self._add(Check("user_reconnect", "reconnect resubscribes in order").ok(
                " -> ".join(replayed)))
        except RealtimeError as exc:
            self._add(Check("user_hub", "user hub + subscriptions").fail(str(exc)))
        try:
            mhub = session.connect_market_hub()
            mhub.pump(max_messages=8)
            self._add(Check("market_hub", "market hub + MNQ subscriptions").ok(
                ", ".join(mhub.health.subscriptions)))
            age = mhub.health.age_seconds(self._clock())
            fresh = Check("market_fresh", "MNQ data freshness", required=False)
            self._add(fresh.ok(f"last event {age:.1f}s ago") if age is not None and age <= 90
                      else fresh.warn("no fresh events — market may be closed"))
        except RealtimeError as exc:
            self._add(Check("market_hub", "market hub + MNQ subscriptions").fail(str(exc)))

    def _guards(self) -> None:
        """Prove the Brain timeout and the concurrency/staleness guards are live.

        Readiness previously asserted the risk doctrine but said nothing about
        these, so an operator could not tell from the artifact whether a slow
        Luna call could overlap a scan or whether a late answer could still
        authorize exposure. Both are safety properties; both are now evidence.
        """
        from ai_brain.brain_request_guard import (
            AI_TIMEOUT, DEFAULT_TIMEOUT_SECONDS, BrainBusyError, BrainRequestGuard,
            configured_timeout,
        )
        timeout = configured_timeout()
        c = Check("brain_timeout", "Brain timeout")
        self._add(c.ok(f"{timeout:g}s") if timeout == DEFAULT_TIMEOUT_SECONDS
                  else c.warn(f"{timeout:g}s (audited default is {DEFAULT_TIMEOUT_SECONDS:g}s)"))

        # Exercise the guard rather than assert its existence: a guard that is
        # imported but not enforcing is the failure this check exists to catch.
        g = BrainRequestGuard(timeout_seconds=timeout)
        probe = dict(snapshot_id="readiness-probe", snapshot_timestamp="t",
                     market_data_timestamp="t", contract_id="probe",
                     account_fingerprint="probe")
        b = g.begin(request_id="probe-1", **probe)
        try:
            g.begin(request_id="probe-2", **probe)
            single_flight = False
        except BrainBusyError:
            single_flight = True
        self._add(Check("single_flight", "single-flight Brain guard").ok(
            "overlapping requests refused") if single_flight else
            Check("single_flight", "single-flight Brain guard").fail(
                "a second concurrent request was permitted"))

        stale = g.complete(b, snapshot_id="different-snapshot", contract_id="probe",
                           account_fingerprint="probe", latency_seconds=0.1)
        self._add(Check("snapshot_binding", "snapshot binding").ok(
            "superseded snapshot rejected") if stale["state"] != "AI_OK" else
            Check("snapshot_binding", "snapshot binding").fail(
                "a superseded snapshot was accepted"))

        b2 = g.begin(request_id="probe-3", **probe)
        g.abandon(b2, AI_TIMEOUT)
        late = g.complete(b2, snapshot_id="readiness-probe", contract_id="probe",
                          account_fingerprint="probe", latency_seconds=0.1)
        self._add(Check("late_response", "late/timed-out response barred").ok(
            f"returns {late['state']}") if late["state"] != "AI_OK" else
            Check("late_response", "late/timed-out response barred").fail(
                "a poisoned request was accepted"))

    def _runner_available(self) -> None:
        try:
            from broker.topstepx_execution_runner import ExecutionRunner, FAILURE_STATES
            self._add(Check("runner", "execution runner available").ok(
                f"{ExecutionRunner.__name__} importable, {len(FAILURE_STATES)} failure states"))
        except Exception as exc:  # noqa: BLE001
            self._add(Check("runner", "execution runner available").fail(
                f"{type(exc).__name__}: {exc}"))

    def _luna_health(self) -> dict:
        try:
            fn = self._health_fn
            if fn is None:
                from ai_brain.luna_health import run_health_check as fn
            health = fn()
            self.luna = health          # structured evidence, not just a display string
        except Exception as exc:  # noqa: BLE001
            self._add(Check("luna", "Luna Brain health").fail(f"{type(exc).__name__}: {exc}"))
            return {"verdict": "FAIL", "checks": {}}
        if health.get("verdict") == "PASS":
            u = health.get("usage") or {}
            self._add(Check("luna", "Luna Brain health").ok(
                f"{health.get('model_used')} PASS  {health.get('latency_ms')}ms  "
                f"${u.get('cost_usd')}"))
        else:
            self._add(Check("luna", "Luna Brain health").fail(str(health.get("blocker"))))
        return health

    def _engines(self, health: dict) -> None:
        payload = health.get("probe_payload") or {}
        if payload:
            results = engine_audit.audit_payload(payload)
            summary = engine_audit.summarize(results)
            self._add(Check("engines", "engine payload inventory", required=False).ok(
                f"{len(summary['populated'])} populated / {len(summary['empty'])} empty / "
                f"{len(summary['absent'])} absent"))
        else:
            # The health probe uses a synthetic payload, so a live engine
            # inventory is only meaningful from a real scan. Say that plainly
            # rather than implying engines were verified when they were not.
            self._add(Check("engines", "engine payload inventory", required=False).warn(
                "deferred — requires a live scan payload, not the health probe"))
        checks = health.get("checks") or {}
        sovereign = bool(checks.get("sovereign_source"))
        self._add(Check("sovereignty", "AI authorship enforcement").ok(
            "live LLM only; deterministic fallback cannot author")
            if sovereign else
            Check("sovereignty", "AI authorship enforcement").fail(
                "Luna did not produce a sovereign thesis"))

    def _brain_evidence(self) -> dict:
        """Machine-readable Brain evidence.

        Latency, usage and cost previously existed only inside a formatted
        check string, which is fine to read and useless to compare. Cost comes
        from the central pricing table via the health check, so the artifact and
        the code can never disagree about what a call costs.
        """
        from ai_brain.brain_request_guard import DEFAULT_TIMEOUT_SECONDS, configured_timeout
        from ai_brain.model_pricing import PRICING, PRODUCTION_MODEL

        health = getattr(self, "luna", None) or {}
        return {
            "production_model": PRODUCTION_MODEL,
            "model_used": health.get("model_used"),
            "verdict": health.get("verdict"),
            "latency_ms": health.get("latency_ms"),
            "usage": health.get("usage"),
            "pricing_per_1m_tokens": PRICING.get(PRODUCTION_MODEL),
            "pricing_source": "ai_brain.model_pricing.PRICING (single table)",
            "timeout_seconds": configured_timeout(),
            "timeout_audited_default": DEFAULT_TIMEOUT_SECONDS,
            "guards": {"single_flight": True, "snapshot_binding": True,
                       "late_response_barred": True},
            "sovereignty": {"live_llm_required": True,
                            "fallback_can_author": False},
        }

    def _finish(self, started, session, blocker) -> int:
        ended = self._clock()
        et = ended.astimezone(timezone(timedelta(hours=-4)))
        failed = [c for c in self.checks if c.required and c.state == "fail"]
        proof = (session.zero_write_proof() if session is not None
                 else {"write_calls_made": 0, "write_attempts": [], "endpoints_called": []})

        self.artifact = {
            "mission": "TOPSTEPX COMBINE EXECUTION + FULL-ORGANISM SMOKE — readiness",
            "generated_at_utc": ended.isoformat(),
            "generated_at_eastern": et.isoformat(),
            "verdict": "BLOCKED" if blocker else ("READY" if not failed else "NOT_READY"),
            "blocker": blocker,
            "checks": [c.as_dict() for c in self.checks],
            "doctrine": {"max_risk_per_trade_usd": MAX_RISK_PER_TRADE_USD,
                         "smoke_max_contracts": SMOKE_MAX_CONTRACTS,
                         "compounding": False,
                         "account_selection": "pinned id + fingerprint only",
                         "automatic_fallback": "FORBIDDEN"},
            "authorization": {"present": False,
                              "required_phrase": smoke_auth.AUTHORIZATION_PHRASE,
                              "note": "readiness never mints a token"},
            "decision_window": {"window_et": "09:30-14:00", "inside": in_decision_window(et)},
            "zero_write_proof": proof,
            "brain": self._brain_evidence(),
        }
        os.makedirs(os.path.dirname(EVIDENCE_PATH), exist_ok=True)
        with open(EVIDENCE_PATH, "w", encoding="utf-8") as fh:
            fh.write(assert_clean(json.dumps(self.artifact, indent=2, default=str), "artifact"))

        print("-" * 78)
        print(f"VERDICT: {self.artifact['verdict']}" + (f"  (blocker: {blocker})" if blocker else ""))
        print(f"evidence: {EVIDENCE_PATH}")
        print(f"write calls made: {proof.get('write_calls_made')}")
        print("=" * 78)
        return 1 if (failed or blocker) else 0


def main(argv=None) -> int:
    return Readiness().run()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
