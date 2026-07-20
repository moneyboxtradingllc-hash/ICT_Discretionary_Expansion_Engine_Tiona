"""Phase 1 — Local NinjaTrader preflight audit.

Probes the machine for the real NinjaTrader installation and writes a
machine-readable artifact. It NEVER claims GUI/account/data state from
filesystem presence alone — those are reported as user-action-required.

Run:  python -m integrations.ninjatrader.preflight
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys

PROGRAM_FILES = os.environ.get("ProgramFiles", r"C:\Program Files")
USERPROFILE = os.environ.get("USERPROFILE", os.path.expanduser("~"))

INSTALL_DIR = os.path.join(PROGRAM_FILES, "NinjaTrader 8")
BIN_DIR = os.path.join(INSTALL_DIR, "bin")
DOC_DIR = os.path.join(USERPROFILE, "Documents", "NinjaTrader 8")

ARTIFACT_PATH = os.path.join("data", "integration", "ninjatrader", "preflight.json")


def _exists(p):
    try:
        return os.path.exists(p)
    except OSError:
        return False


def _pythonnet_available():
    try:
        import clr  # noqa: F401
        return True
    except Exception:
        return False


def run_preflight() -> dict:
    checks = {}

    exe = os.path.join(BIN_DIR, "NinjaTrader.exe")
    client_dll = os.path.join(BIN_DIR, "NinjaTrader.Client.dll")

    checks["ninjatrader_installed"] = {
        "status": "verified" if _exists(exe) else "unavailable",
        "install_dir": INSTALL_DIR, "executable": exe,
    }
    checks["ninjatrader_client_dll"] = {
        "status": "verified" if _exists(client_dll) else "unavailable",
        "path": client_dll,
    }
    doc_exists = _exists(DOC_DIR)
    doc_children = sorted(os.listdir(DOC_DIR)) if doc_exists else []
    checks["ninjatrader_user_data_initialized"] = {
        "status": "user-action-required" if not doc_children else "verified",
        "path": DOC_DIR,
        "children": doc_children,
        "note": ("Documents\\NinjaTrader 8 empty -> never launched; first launch "
                 "creates user-data + Sim101") if not doc_children else "initialized",
    }
    checks["ati_file_interface_folders"] = {
        "status": "verified" if _exists(os.path.join(DOC_DIR, "incoming")) else "unavailable",
        "incoming": os.path.join(DOC_DIR, "incoming"),
        "outgoing": os.path.join(DOC_DIR, "outgoing"),
    }
    checks["pythonnet_installed"] = {
        "status": "verified" if _pythonnet_available() else "unavailable",
    }
    # GUI/account/data facts we cannot see from the filesystem.
    for k in ("ninjatrader_running", "sim101_exists",
              "market_data_connection_available", "ati_enabled_in_ninjatrader",
              "global_simulation_mode"):
        checks[k] = {"status": "user-action-required",
                     "note": "GUI/account/connection fact — confirm in NinjaTrader"}

    return {
        "artifact": "ninjatrader_preflight",
        "schema_version": 1,
        "integration_era": "MNQ_NINJATRADER_FOUNDATION",
        "generated_at": _dt.datetime.now().astimezone().isoformat(),
        "machine": {"python_version": sys.version.split()[0]},
        "checks": checks,
    }


def main():
    report = run_preflight()
    os.makedirs(os.path.dirname(ARTIFACT_PATH), exist_ok=True)
    with open(ARTIFACT_PATH, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    print(f"preflight written to {ARTIFACT_PATH}")
    return report


if __name__ == "__main__":
    main()
