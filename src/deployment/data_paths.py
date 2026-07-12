"""DEPLOY-1 — central data-path resolver for instance isolation.

Every stateful subsystem resolves its directory through `resolve()` so a single
`InstanceContext.activate()` can redirect ALL state into one instance folder by
setting environment variables. When the env var is NOT set, the LEGACY default
is returned unchanged — so the single-instance project behaves bit-for-bit as
before (regression-safe). Nothing here writes; it only resolves paths.
"""
import os

# repo root = three levels up from src/deployment/data_paths.py
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Canonical per-subsystem environment variables. InstanceContext.activate()
# sets these to point inside the active instance directory. Listed here so the
# audit/test layer has one authoritative inventory of isolatable state.
SUBSYSTEM_ENV = {
    "brain":              "AI_BRAIN_DIR",          # stance + brain calls + divergence (instance memory)
    "vector_store":       "AI_RETRIEVAL_DIR",      # per-instance vector analogs
    "journal":            "PAPER_TRADES_DIR",      # per-instance trade journal
    "snapshots":          "LIVE_SNAPSHOTS_DIR",    # per-instance scan snapshots/logs
    "intent_archive":     "INTENT_ARCHIVE_DIR",    # per-instance intent records
    "activation_reports": "ACTIVATION_REPORTS_DIR",
    "rule_governance":    "RULE_GOVERNANCE_DIR",   # per-instance governance ledger
    # "shadow" removed — shadow AI evaluator retired (TIER-2A 2026-07-10)
    "news_memory":        "NEWS_MEMORY_DIR",       # per-instance news reaction history
    "ops":                "OPS_DIR",               # per-instance lock/heartbeat/state
}


def resolve(env_var: str, *legacy_parts: str, anchored: bool = False) -> str:
    """Return the env override if set, else the legacy default path.

    anchored=True anchors the legacy default at PROJECT_ROOT (matches modules
    that historically used an absolute project-root path); otherwise the legacy
    default is the relative join (matches modules that used a relative path).
    """
    override = os.getenv(env_var)
    if override:
        return override
    if anchored:
        return os.path.join(PROJECT_ROOT, *legacy_parts)
    return os.path.join(*legacy_parts)
