"""Import helpers from `tools/` without making tools a package.

The evidence tools live in `tools/` because they are operator entry points, not
library code. Tests still need their pure functions, so this loads them by path.
"""
from __future__ import annotations

import importlib.util
import os

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "tools")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"_tools_{name}", os.path.join(_TOOLS, f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_parity = _load("fact_parity_audit")
_activity = _load("reconcile_session_activity")

FACTS = _parity.FACTS
audit_scan = _parity.audit_scan
catalog_parity = _parity.catalog_parity
dig = _parity.dig
reconcile_activity = _activity.reconcile
