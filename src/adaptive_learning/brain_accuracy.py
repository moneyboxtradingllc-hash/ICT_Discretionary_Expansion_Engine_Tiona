"""
ADAPT-LOOP-3 — Brain Accuracy reader + gated payload feed (pipeline side,
2026-07-10).

Reads the table the replay engine builds (replay_validation.brain_accuracy →
data/performance/<SYM>/brain_accuracy.json) and, when BRAIN_ACCURACY_CONTEXT=on,
attaches a COMPACT self-track-record block inside the Brain payload's
adaptive_learning_context — so the Brain reasons knowing how its own directional
calls have actually resolved (by direction / family-present / confidence).

DESCRIPTIVE ONLY. It inherits the ADAPTIVE_LEARNING_ADDENDUM cognitive boundary
(advisory; may never author direction or alter qualification). No module may
veto on this table. Default off = payload byte-identical. Never raises.
"""
import json
import os

from deployment.data_paths import resolve

_FILE = "brain_accuracy.json"


def accuracy_path(symbol: str, base_dir: "str | None" = None) -> str:
    root = base_dir or resolve("PERFORMANCE_TABLES_DIR", "data", "performance",
                               anchored=True)
    return os.path.join(root, str(symbol).upper(), _FILE)


def accuracy_feed_enabled() -> bool:
    return os.getenv("BRAIN_ACCURACY_CONTEXT", "off").lower().strip() == "on"


def load_brain_accuracy(symbol: str, base_dir=None) -> dict:
    try:
        with open(accuracy_path(symbol, base_dir), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def compact_accuracy_context(symbol: str, base_dir=None) -> "dict | None":
    """Small, prompt-safe summary for the Brain payload (None when no table)."""
    t = load_brain_accuracy(symbol, base_dir)
    if not t or not (t.get("overall") or {}).get("n"):
        return None
    return {
        "authority": "descriptive_only",
        "note": ("your own directional track record on this symbol — "
                 "context, never a directional input"),
        "graded_scans": t.get("graded_scans"),
        "horizon_bars": t.get("horizon_bars"),
        "overall": t.get("overall"),
        "by_direction": t.get("by_direction"),
        "by_family_present": t.get("by_family_present"),
        "by_confidence": t.get("by_confidence"),
    }


def attach_accuracy_context(brain_input: dict, symbol: str, base_dir=None) -> bool:
    """Gated attach into adaptive_learning_context. Returns True when attached.
    Never raises; failure leaves the payload untouched."""
    try:
        if not accuracy_feed_enabled() or not isinstance(brain_input, dict):
            return False
        ctx = compact_accuracy_context(symbol, base_dir)
        if ctx is None:
            return False
        alc = brain_input.get("adaptive_learning_context")
        if not isinstance(alc, dict):
            alc = {}
            brain_input["adaptive_learning_context"] = alc
        alc["brain_self_accuracy"] = ctx
        return True
    except Exception:  # noqa: BLE001
        return False
