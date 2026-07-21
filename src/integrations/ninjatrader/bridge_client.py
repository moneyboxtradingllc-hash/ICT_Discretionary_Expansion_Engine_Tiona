"""Loopback bridge client — Python side of the NinjaScript IPC.

Connects to the MNQBridge AddOn on 127.0.0.1 (loopback only) and exchanges
newline-delimited IPC envelopes. It is deliberately thin and fail-closed: if no
bridge is present (the foundation state, since NT8 has not been launched), every
read reports "unknown" and `is_connected()` returns False, which upstream gates
translate into DENY-fresh-entry.

Forensics: every inbound/outbound envelope is appended to a JSONL journal so the
full conversation is auditable.
"""
from __future__ import annotations

import json
import os
import socket
import time
from typing import Optional

from integrations.ninjatrader import ipc_protocol as P

LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 36901
JOURNAL_PATH = os.path.join("data", "integration", "ninjatrader", "ipc_journal.jsonl")


class NinjaTraderBridgeClient:
    def __init__(self, host: str = LOOPBACK_HOST, port: int = DEFAULT_PORT,
                 timeout: float = 2.0, account: str = "DEMO8458533",
                 instrument: str = "", journal_path: str = JOURNAL_PATH):
        # Refuse any non-loopback host: this client never speaks to a network.
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError(f"bridge host must be loopback, got {host!r}")
        self.host, self.port, self.timeout = host, port, timeout
        self.account, self.instrument = account, instrument
        self.journal_path = journal_path
        self._sock: Optional[socket.socket] = None
        self._seq = 0

    # ── connection ───────────────────────────────────────────────────────────
    def connect(self) -> bool:
        try:
            s = socket.create_connection((self.host, self.port), timeout=self.timeout)
            s.settimeout(self.timeout)
            self._sock = s
            return True
        except OSError:
            self._sock = None
            return False

    def is_connected(self) -> bool:
        return self._sock is not None

    def close(self):
        try:
            if self._sock:
                self._sock.close()
        finally:
            self._sock = None

    # ── forensics ──────────────────────────────────────────────────────────--
    def _journal(self, direction: str, env: dict):
        try:
            os.makedirs(os.path.dirname(self.journal_path), exist_ok=True)
            with open(self.journal_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"dir": direction, "at": time.time(), "env": env}) + "\n")
        except OSError:
            pass

    # ── request/response ─────────────────────────────────────────────────────
    def _request(self, message_type: str, payload: dict) -> Optional[dict]:
        if not self._sock:
            return None
        self._seq += 1
        env = P.build_envelope(message_type, payload, message_id=f"py-{self._seq}",
                               sequence=self._seq, account=self.account,
                               instrument=self.instrument)
        self._journal("out", env)
        try:
            self._sock.sendall((json.dumps(env) + "\n").encode("utf-8"))
            data = self._read_line()
        except OSError:
            self.close()
            return None
        if data is None:
            return None
        try:
            resp = P.parse_envelope(data)
        except P.ProtocolError:
            return None
        self._journal("in", resp)
        vr = P.validate_envelope(resp)
        if not vr:
            return {"message_type": "ERROR", "payload": {"reason": vr.reason}}
        return resp

    def _read_line(self) -> Optional[str]:
        buf = b""
        while b"\n" not in buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                return None
            buf += chunk
        return buf.split(b"\n", 1)[0].decode("utf-8")

    # ── read surface (fail-closed when no bridge) ────────────────────────────
    def connection_state(self) -> dict:
        r = self._request("HELLO", {})
        return (r or {}).get("payload", {}) if r else {"connected": False, "known": False}

    def instrument_metadata(self, instrument_name: str) -> dict:
        self.instrument = instrument_name
        r = self._request("INSTRUMENT_METADATA", {})
        return (r or {}).get("payload", {}) if r else {"known": False}

    def account_state(self) -> dict:
        r = self._request("ACCOUNT_STATE", {})
        return (r or {}).get("payload", {}) if r else {"account": None, "known": False}

    def position(self, instrument_name: str) -> dict:
        r = self._request("POSITION_UPDATE", {"instrument": instrument_name})
        return (r or {}).get("payload", {}) if r else {"qty": 0, "known": False}

    def working_orders(self) -> list:
        r = self._request("ORDER_UPDATE", {})
        return (r or {}).get("payload", {}).get("orders", []) if r else []

    # ── write surface — never reachable in the disarmed foundation ───────────
    def submit(self, order: dict):  # pragma: no cover - orders disarmed
        raise RuntimeError("order submission is disarmed in the foundation mission")

    def protective_stop(self, position_ref, stop_definition):  # pragma: no cover
        raise RuntimeError("protective-stop wire not active in the foundation mission")
