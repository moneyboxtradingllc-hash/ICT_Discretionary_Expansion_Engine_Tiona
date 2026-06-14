"""
OPS-1 — Startup Authority.

THE consolidation point for startup validation. Before scan #1 the bot asks
one question — "Do I have authority to trade today?" — and gets one verdict:

  GRANTED   — all mandatory checks pass; trade normally
  DEGRADED  — mandatory checks pass; observe-only plane impaired
              (trading proceeds, evidence collection is flagged)
  DENIED    — a mandatory check failed; the loop must not evaluate setups

No scores. No percentages. A verdict, with named reasons.

CONSTITUTION:
  - Mandatory checks  = enforcement-path subsystems -> fail CLOSED.
  - Optional checks   = observe-only plane          -> fail OPEN but LOUD.
    (Observe-only systems never receive execution veto power — 5H.)
  - Restart semantics: open position + active journal trade at startup
    -> mode MANAGEMENT_ONLY (manage/protect, no new entries) until the
    position is gone and reconciliation is clean.
  - Config attestation: the effective configuration is captured, persisted,
    and protected values are hard-verified. Drift is obvious or fatal.
"""
import json
import os
from datetime import datetime

import pytz

_EASTERN  = pytz.timezone("America/New_York")
def _ops_dir() -> str:
    return os.getenv("OPS_DIR", os.path.join("data", "ops"))


def _lock_path() -> str:
    return os.path.join(_ops_dir(), "bot.lock")

# Protected configuration: ceilings/expectations that define a legal session.
_PROTECTED = {
    "PAPER_TRADING_ONLY":       ("equals",  "true"),
    "MAX_TRADES_PER_DAY":       ("max_int", 2),
    "RISK_PER_TRADE_DOLLARS":   ("max_num", 500.0),
    "DAILY_LOSS_LIMIT_DOLLARS": ("max_num", 500.0),
}

_ATTESTED_KEYS = [
    "EXECUTION_ENABLED", "ALLOW_PAPER_ORDERS", "PAPER_TRADING_ONLY",
    "PAPER_ACTIVATION_MODE", "PAPER_EXIT_ON_STOP", "BROKER_STOP_ENABLED",
    "MAX_TRADES_PER_DAY", "ONE_POSITION_AT_A_TIME",
    "RISK_PER_TRADE_DOLLARS", "DAILY_LOSS_LIMIT_DOLLARS",
    "ADAPTIVE_MANAGEMENT_ENABLED", "THESIS_MONITOR_ENABLED",
    "RULE_GOVERNANCE_ENABLED", "REGIME_AUTHORITY_ENABLED",
    "EOD_NO_ENTRY_AFTER", "EOD_FLATTEN_AT", "EOD_POLICY",
    "AI_MODEL", "SCAN_INTERVAL_SECONDS",
]


def _now_str() -> str:
    return datetime.now(_EASTERN).strftime("%Y%m%dT%H%M%S")


# ── Single-instance guard ─────────────────────────────────────────────────────

def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def acquire_instance_lock() -> tuple:
    """(ok, reason). Refuses if another live bot process holds the lock."""
    try:
        os.makedirs(_ops_dir(), exist_ok=True)
        if os.path.exists(_lock_path()):
            try:
                with open(_lock_path(), encoding="utf-8") as f:
                    holder = json.load(f)
                old_pid = int(holder.get("pid", -1))
            except (OSError, ValueError, json.JSONDecodeError):
                old_pid = -1
            if old_pid > 0 and old_pid != os.getpid() and _pid_alive(old_pid):
                return False, f"another bot instance is alive (pid {old_pid})"
            # stale lock — previous process is dead; reclaim
        with open(_lock_path(), "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "acquired": _now_str()}, f)
        return True, f"lock acquired (pid {os.getpid()})"
    except OSError as exc:
        return False, f"lock unavailable: {exc}"


def release_instance_lock() -> None:
    try:
        if os.path.exists(_lock_path()):
            with open(_lock_path(), encoding="utf-8") as f:
                holder = json.load(f)
            if int(holder.get("pid", -1)) == os.getpid():
                os.remove(_lock_path())
    except (OSError, ValueError, json.JSONDecodeError):
        pass


# ── Config attestation ────────────────────────────────────────────────────────

def attest_config() -> dict:
    """Capture effective config; verify protected values. Never raises."""
    effective = {k: os.getenv(k) for k in _ATTESTED_KEYS}
    violations = []
    for key, (kind, expected) in _PROTECTED.items():
        raw = os.getenv(key)
        if raw is None:
            violations.append(f"{key} is not set")
            continue
        if kind == "equals" and raw.lower().strip() != expected:
            violations.append(f"{key}={raw!r} (required: {expected!r})")
        elif kind == "max_int":
            try:
                if int(raw) > expected:
                    violations.append(f"{key}={raw} exceeds ceiling {expected}")
            except ValueError:
                violations.append(f"{key}={raw!r} is not an integer")
        elif kind == "max_num":
            try:
                if float(raw) > expected:
                    violations.append(f"{key}={raw} exceeds ceiling {expected}")
            except ValueError:
                violations.append(f"{key}={raw!r} is not a number")

    attestation = {
        "attested_at": _now_str(),
        "pid":         os.getpid(),
        "effective":   effective,
        "violations":  violations,
        "ok":          not violations,
    }
    try:
        os.makedirs(_ops_dir(), exist_ok=True)
        date_str = datetime.now(_EASTERN).strftime("%Y%m%d")
        with open(os.path.join(_ops_dir(), f"config_attestation_{date_str}.json"),
                  "w", encoding="utf-8") as f:
            json.dump(attestation, f, indent=2)
    except OSError:
        pass
    return attestation


# ── Heartbeat ─────────────────────────────────────────────────────────────────

def write_heartbeat(scan_count: int, status: str = "running") -> None:
    """Per-scan heartbeat for dead-man monitoring. Never raises."""
    try:
        os.makedirs(_ops_dir(), exist_ok=True)
        with open(os.path.join(_ops_dir(), "heartbeat.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"ts": _now_str(), "pid": os.getpid(),
                       "scan": scan_count, "status": status}, f)
    except OSError:
        pass


# ── Individual checks ─────────────────────────────────────────────────────────

def _check_broker_account() -> tuple:
    from paper_execution.paper_broker import is_paper_account_safe, get_account
    safe, reason = is_paper_account_safe()
    if not safe:
        return False, f"paper endpoint check failed: {reason}"
    acct = get_account()
    if "error" in acct:
        return False, f"account access failed: {acct['error']}"
    bp = float(acct.get("buying_power", 0) or 0)
    if bp <= 0:
        return False, f"buying power is {bp}"
    return True, f"paper account ok (buying_power={bp:.0f})"


def _check_data_feed(symbol: str) -> tuple:
    from data_feed import get_provider
    provider = get_provider()
    candles  = provider.fetch_1m_candles(symbol, 600)
    if not candles or len(candles) < 100:
        return False, f"insufficient warm-up history ({len(candles or [])} 1m candles)"
    return True, f"data feed ok ({len(candles)} candles)"


def _check_journal_writable() -> tuple:
    # DEPLOY-1 — probe the active instance's journal dir (PAPER_TRADES_DIR).
    from deployment.data_paths import resolve
    path = resolve("PAPER_TRADES_DIR", "data", "paper_trades", anchored=True)
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".ops_probe")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return True, "journal directory writable"
    except OSError as exc:
        return False, f"journal not writable: {exc}"


def _check_risk_config() -> tuple:
    problems = []
    for key in ("RISK_PER_TRADE_DOLLARS", "DAILY_LOSS_LIMIT_DOLLARS"):
        try:
            if float(os.getenv(key, "0")) <= 0:
                problems.append(f"{key} <= 0")
        except ValueError:
            problems.append(f"{key} invalid")
    try:
        if int(os.getenv("MAX_TRADES_PER_DAY", "0")) < 1:
            problems.append("MAX_TRADES_PER_DAY < 1")
    except ValueError:
        problems.append("MAX_TRADES_PER_DAY invalid")
    if os.getenv("PAPER_EXIT_ON_STOP", "").lower().strip() != "true":
        problems.append("PAPER_EXIT_ON_STOP != true (stop enforcement off)")
    if problems:
        return False, "; ".join(problems)
    return True, "risk configuration sane"


def _smoke_intelligence() -> tuple:
    """One synthetic evaluation per enforcement-path engine. Crash = DENIED."""
    try:
        from regime_classification.regime_classifier import classify_regime
        from regime_authority.regime_permission_matrix import evaluate_regime_permissions
        from execution_gate.execution_gate import evaluate_gate
        from paper_execution.management_policies import get_policy
        classify_regime({}, None)
        evaluate_regime_permissions({})
        evaluate_gate({})
        get_policy("defensive")
        return True, "enforcement-path engines smoke-checked"
    except Exception as exc:  # noqa: BLE001
        return False, f"enforcement engine crashed on smoke check: {exc}"


def _stale_state_hygiene(symbol: str) -> tuple:
    """
    Reconcile orphans BEFORE scan #1:
      - journal trades healed via reconcile_trade
      - broker entry orders submitted on a PREVIOUS day -> cancelled
    Returns (ok, detail). Conservative: protective stops for live positions
    are never touched here.
    """
    from paper_execution.trade_reconciliation import reconcile_trade
    from paper_execution.paper_broker import (
        get_open_orders, get_open_positions, cancel_order,
    )

    recon = reconcile_trade(symbol)

    today     = datetime.now(_EASTERN).strftime("%Y-%m-%d")
    positions = {p.get("symbol") for p in get_open_positions()}
    cancelled = []
    for order in get_open_orders(symbol):
        submitted = str(order.get("submitted_at") or "")[:10]
        otype     = (order.get("order_type") or "").lower()
        # Stale = entry order from a prior day. Stops protecting a live
        # position are left alone.
        is_stop = "stop" in otype
        if submitted and submitted < today and not (is_stop and symbol in positions):
            result = cancel_order(order.get("order_id") or order.get("id"))
            cancelled.append({
                "order_id": order.get("order_id") or order.get("id"),
                "type": otype, "submitted": submitted,
                "cancelled": bool(result.get("canceled")),
            })
    detail = (
        f"reconciliation={recon.get('status', 'n/a')}"
        + (f"; stale orders cancelled: {len(cancelled)}" if cancelled else "; no stale orders")
    )
    return True, detail


def _detect_restart_position(symbol: str) -> tuple:
    """(management_only: bool, detail). Open position + active journal trade
    at startup -> MANAGEMENT_ONLY mode."""
    from paper_execution.paper_broker import get_position
    from paper_execution.trade_journal import find_any_active_trade

    pos = get_position(symbol)
    if pos is None:
        return False, "no open position at startup"
    trade, _ = find_any_active_trade(symbol)
    if trade is not None:
        return True, (
            f"open position found at startup (qty={pos.get('qty')}) with active "
            f"journal trade {trade.get('trade_id')} — MANAGEMENT_ONLY until flat"
        )
    return True, (
        f"open position found at startup (qty={pos.get('qty')}) with NO journal "
        "trade — MANAGEMENT_ONLY; manual review recommended"
    )


# ── Optional (observe-only plane — fail OPEN, loud) ──────────────────────────

def _check_governance_plane() -> tuple:
    from rule_governance.rule_registry import load_registry
    reg = load_registry()
    if not reg["loaded"]:
        return False, "rule registry unreadable"
    if reg["quarantined"]:
        return False, f"registry quarantined records: {reg['quarantined'][:2]}"
    return True, f"registry ok ({len(reg['rules'])} rules)"


def _check_observe_plane() -> tuple:
    try:
        from shared_context.shared_market_context import build_shared_market_context
        from shared_context.council import run_council
        from rule_governance.shadow_evaluator import evaluate_shadow_rules
        ctx = build_shared_market_context({}, "OPS")
        run_council(ctx)
        evaluate_shadow_rules({}, "OPS")
        ledger_dir = os.path.join(
            os.getenv("RULE_GOVERNANCE_DIR", os.path.join("data", "rule_governance")),
            "ledger",
        )
        os.makedirs(ledger_dir, exist_ok=True)
        return True, "observe-only plane ok (context/council/shadow/ledger)"
    except Exception as exc:  # noqa: BLE001
        return False, f"observe-only plane impaired: {exc}"


# ── Public entry point ────────────────────────────────────────────────────────

def run_startup_authority(symbol: str, skip_network: bool = False) -> dict:
    """
    OPS-1 — the single startup decision.
    Returns {"verdict": GRANTED|DENIED|DEGRADED, "mode": NORMAL|MANAGEMENT_ONLY,
             "mandatory_failures": [...], "degraded_reasons": [...],
             "checks": {...}, "attestation": {...}}
    Never raises.
    """
    checks: dict = {}
    mandatory_failures: list = []
    degraded_reasons: list = []
    mode = "NORMAL"

    def _mandatory(name, fn, *args):
        try:
            ok, detail = fn(*args)
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"{name} crashed: {exc}"
        checks[name] = {"ok": ok, "detail": detail, "class": "mandatory"}
        if not ok:
            mandatory_failures.append(f"{name}: {detail}")
        return ok

    def _optional(name, fn, *args):
        try:
            ok, detail = fn(*args)
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"{name} crashed: {exc}"
        checks[name] = {"ok": ok, "detail": detail, "class": "optional"}
        if not ok:
            degraded_reasons.append(f"{name}: {detail}")
        return ok

    # ── Mandatory: fail closed ────────────────────────────────────────────────
    lock_ok, lock_detail = acquire_instance_lock()
    checks["single_instance"] = {"ok": lock_ok, "detail": lock_detail,
                                 "class": "mandatory"}
    if not lock_ok:
        mandatory_failures.append(f"single_instance: {lock_detail}")

    attestation = attest_config()
    checks["config_attestation"] = {
        "ok": attestation["ok"],
        "detail": "; ".join(attestation["violations"]) or "protected values verified",
        "class": "mandatory",
    }
    if not attestation["ok"]:
        mandatory_failures.append(
            "config_attestation: " + "; ".join(attestation["violations"]))

    _mandatory("risk_config", _check_risk_config)
    _mandatory("journal_writable", _check_journal_writable)
    _mandatory("intelligence_smoke", _smoke_intelligence)

    if not skip_network:
        _mandatory("broker_account", _check_broker_account)
        _mandatory("data_feed", _check_data_feed, symbol)
        if not mandatory_failures:
            _mandatory("stale_state_hygiene", _stale_state_hygiene, symbol)
            try:
                management_only, detail = _detect_restart_position(symbol)
            except Exception as exc:  # noqa: BLE001
                management_only, detail = True, f"restart detection failed: {exc}"
            checks["restart_semantics"] = {"ok": True, "detail": detail,
                                           "class": "mandatory"}
            if management_only:
                mode = "MANAGEMENT_ONLY"

    # ── Optional: observe-only plane — fail open, loud ───────────────────────
    _optional("governance_registry", _check_governance_plane)
    _optional("observe_plane", _check_observe_plane)

    if mandatory_failures:
        verdict = "DENIED"
    elif degraded_reasons:
        verdict = "DEGRADED"
    else:
        verdict = "GRANTED"

    result = {
        "verdict":            verdict,
        "mode":               mode,
        "mandatory_failures": mandatory_failures,
        "degraded_reasons":   degraded_reasons,
        "checks":             checks,
        "attestation":        attestation,
        "decided_at":         _now_str(),
    }

    # Persist the decision beside the attestation
    try:
        os.makedirs(_ops_dir(), exist_ok=True)
        date_str = datetime.now(_EASTERN).strftime("%Y%m%d")
        with open(os.path.join(_ops_dir(), f"startup_authority_{date_str}.json"),
                  "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, default=str)
    except OSError:
        pass

    return result
