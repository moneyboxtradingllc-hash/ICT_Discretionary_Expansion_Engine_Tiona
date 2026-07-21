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


def _resolve_user_data_dir() -> str:
    """NT8's user-data dir lives under the *real* Documents folder, which on this
    machine is OneDrive-redirected. Probe the likely locations and return the
    first that exists (populated), else the classic path as the reported target."""
    onedrive = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer") or ""
    candidates = [
        os.path.join(USERPROFILE, "Documents", "NinjaTrader 8"),
        os.path.join(onedrive, "Documents", "NinjaTrader 8") if onedrive else "",
        os.path.join(USERPROFILE, "OneDrive", "Documents", "NinjaTrader 8"),
    ]
    for c in candidates:
        if c and os.path.isdir(c) and os.listdir(c):
            return c
    return candidates[0]


DOC_DIR = _resolve_user_data_dir()

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


def _ninjatrader_running() -> bool:
    try:
        import subprocess
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq NinjaTrader.exe"],
                             capture_output=True, text=True, timeout=10)
        return "NinjaTrader.exe" in (out.stdout or "")
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
                 "creates user-data + DEMO8458533") if not doc_children else "initialized",
    }
    checks["ati_file_interface_folders"] = {
        "status": "verified" if _exists(os.path.join(DOC_DIR, "incoming")) else "unavailable",
        "incoming": os.path.join(DOC_DIR, "incoming"),
        "outgoing": os.path.join(DOC_DIR, "outgoing"),
    }
    checks["pythonnet_installed"] = {
        "status": "verified" if _pythonnet_available() else "unavailable",
    }
    # NinjaTrader process is detectable without the GUI.
    checks["ninjatrader_running"] = {
        "status": "verified" if _ninjatrader_running() else "unavailable",
        "note": "detected via process table",
    }
    # Account/connection/GUI facts still require the bridge or Maurice's eyes.
    for k in ("sim_account_exists",
              "market_data_connection_available", "ati_enabled_in_ninjatrader",
              "global_simulation_mode"):
        checks[k] = {"status": "user-action-required",
                     "note": "GUI/account/connection fact — read via the bridge "
                             "(when compiled) or confirm in NinjaTrader"}

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
