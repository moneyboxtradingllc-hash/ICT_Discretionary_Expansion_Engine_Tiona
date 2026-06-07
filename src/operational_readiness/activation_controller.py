"""
Phase 2C — Activation Controller.

Determines whether the paper trading system may be considered certified
for activation based on the readiness report and env configuration.

IMPORTANT: This module does NOT submit orders, does NOT change execution
behaviour, and does NOT modify any state. It is a pure certification
layer. actual order submission is still gated by EXECUTION_ENABLED,
ALLOW_PAPER_ORDERS, and the full 10-layer execution_engine guard chain.

Statuses:
  not_ready            — one or more readiness checks failed
  safe_but_disabled    — infrastructure ok, EXECUTION_ENABLED=false
  activation_blocked   — EXECUTION_ENABLED=true but ALLOW_PAPER_ORDERS=false,
                         or a non-critical infrastructure gap
  ready_for_activation — all checks pass and both execution flags are on
"""
import os

# Readiness check keys that must all pass before activation can be certified.
_INFRA_REQUIRED = (
    "paper_endpoint_verified",
    "paper_only_mode",
    "execution_gate_present",
    "position_monitor_present",
    "stop_enforcer_present",
    "journal_writable",
)


def determine_activation(readiness: dict) -> dict:
    """
    Phase 2C — derive the activation status from a readiness_checklist result.
    Never raises.
    """
    try:
        return _evaluate(readiness)
    except Exception as exc:
        return {
            "activation_allowed":     False,
            "status":                 "not_ready",
            "reason":                 f"activation controller error: {exc}",
            "requirements_remaining": [],
            "warnings":               [str(exc)],
        }


def _evaluate(readiness: dict) -> dict:

    # ── Readiness must pass first ─────────────────────────────────────────────
    if not readiness.get("ready", False):
        issues = readiness.get("blocking_issues", ["unknown failure"])
        return {
            "activation_allowed":     False,
            "status":                 "not_ready",
            "reason":                 issues[0] if issues else "readiness check failed",
            "requirements_remaining": list(issues),
            "warnings":               readiness.get("warnings", []),
        }

    # ── Infrastructure keys must individually pass ────────────────────────────
    checks   = readiness.get("checks", {})
    missing  = [k for k in _INFRA_REQUIRED if not checks.get(k, False)]
    if missing:
        return {
            "activation_allowed":     False,
            "status":                 "activation_blocked",
            "reason":                 "infrastructure checks incomplete",
            "requirements_remaining": missing,
            "warnings":               [],
        }

    # ── Master execution switch ───────────────────────────────────────────────
    execution_enabled = os.getenv("EXECUTION_ENABLED", "false").lower().strip() == "true"
    if not execution_enabled:
        return {
            "activation_allowed":     False,
            "status":                 "safe_but_disabled",
            "reason":                 "EXECUTION_ENABLED=false",
            "requirements_remaining": [],
            "warnings":               [],
        }

    # ── Paper orders switch ───────────────────────────────────────────────────
    paper_orders = os.getenv("ALLOW_PAPER_ORDERS", "false").lower().strip() == "true"
    if not paper_orders:
        return {
            "activation_allowed":     False,
            "status":                 "activation_blocked",
            "reason":                 "ALLOW_PAPER_ORDERS=false",
            "requirements_remaining": ["set ALLOW_PAPER_ORDERS=true to enable paper orders"],
            "warnings":               [],
        }

    # ── All checks pass — system certified ───────────────────────────────────
    return {
        "activation_allowed":     True,
        "status":                 "ready_for_activation",
        "reason":                 "all operational checks passed",
        "requirements_remaining": [],
        "warnings":               [],
    }
