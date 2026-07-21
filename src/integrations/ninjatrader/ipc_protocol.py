"""Phase 10 — Local IPC protocol between the NinjaScript bridge and Python.

Transport (defined elsewhere) MUST bind only to 127.0.0.1 loopback or a local
named pipe; it MUST NOT expose an unauthenticated network service.

This module defines the message envelope, its validation, and an idempotency /
sequence tracker. It is transport-agnostic and dependency-free so it can be
unit-tested without any socket or NinjaTrader present.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Optional

PROTOCOL_VERSION = "1.0.0"

# Message types (superset; not all used in the read-only foundation).
MESSAGE_TYPES = frozenset({
    "HELLO", "HELLO_ACK", "HEARTBEAT", "CONNECTION_STATE", "INSTRUMENT_METADATA",
    "HISTORICAL_BARS_REQUEST", "HISTORICAL_BARS_RESPONSE", "BAR_CLOSED",
    "QUOTE_UPDATE", "ACCOUNT_STATE", "POSITION_UPDATE",
    "ORDER_SUBMIT_REQUEST", "ORDER_ACK", "ORDER_UPDATE", "EXECUTION_UPDATE",
    "ORDER_CANCEL_REQUEST", "ERROR", "SHUTDOWN",
})

# Types that carry an order/command intent and therefore require strict
# account+instrument binding.
COMMAND_TYPES = frozenset({"ORDER_SUBMIT_REQUEST", "ORDER_CANCEL_REQUEST"})

DEFAULT_STALE_SECONDS = 5.0


class ProtocolError(ValueError):
    pass


def _checksum(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def build_envelope(message_type: str, payload: dict, *,
                   message_id: str, correlation_id: str = "",
                   sequence: int = 0, instrument: str = "", expiry: str = "",
                   account: str = "", sent_at: Optional[float] = None) -> dict:
    if message_type not in MESSAGE_TYPES:
        raise ProtocolError(f"unknown message_type {message_type!r}")
    payload = payload or {}
    env = {
        "protocol_version": PROTOCOL_VERSION,
        "message_type": message_type,
        "message_id": message_id,
        "correlation_id": correlation_id,
        "sequence": int(sequence),
        "sent_at": float(sent_at if sent_at is not None else time.time()),
        "instrument": instrument,
        "expiry": expiry,
        "account": account,
        "payload": payload,
    }
    env["checksum"] = _checksum(payload)
    return env


def parse_envelope(raw) -> dict:
    """Parse raw JSON text/bytes into an envelope dict. Malformed -> ProtocolError."""
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="strict")
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise ProtocolError(f"cannot parse envelope of type {type(raw).__name__}")
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ProtocolError(f"malformed JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise ProtocolError("envelope must be a JSON object")
    return obj


@dataclass
class ValidationContext:
    """What the local endpoint expects. Any mismatch fails closed."""
    expected_account: Optional[str] = None        # e.g. "DEMO8458533" for command types
    expected_instrument: Optional[str] = None     # exact resolved MNQ expiry name
    now: Optional[float] = None
    stale_seconds: float = DEFAULT_STALE_SECONDS


@dataclass
class ValidationResult:
    ok: bool
    reason: str
    envelope: Optional[dict] = None

    def __bool__(self):
        return self.ok


_REQUIRED_FIELDS = ("protocol_version", "message_type", "message_id",
                    "sequence", "sent_at", "payload")


def validate_envelope(env: dict, ctx: Optional[ValidationContext] = None) -> ValidationResult:
    ctx = ctx or ValidationContext()
    now = ctx.now if ctx.now is not None else time.time()

    if not isinstance(env, dict):
        return ValidationResult(False, "envelope is not an object")
    for f in _REQUIRED_FIELDS:
        if f not in env:
            return ValidationResult(False, f"missing required field {f!r}")

    if env.get("protocol_version") != PROTOCOL_VERSION:
        return ValidationResult(False,
                                f"protocol_version {env.get('protocol_version')!r} != "
                                f"{PROTOCOL_VERSION!r}")

    mtype = env.get("message_type")
    if mtype not in MESSAGE_TYPES:
        return ValidationResult(False, f"unknown message_type {mtype!r}")

    payload = env.get("payload")
    if not isinstance(payload, dict):
        return ValidationResult(False, "payload must be an object")

    # Integrity check when a checksum is present.
    if "checksum" in env:
        if env["checksum"] != _checksum(payload):
            return ValidationResult(False, "checksum mismatch (payload tampered/corrupted)")

    # Staleness — reject commands built too far in the past/future.
    try:
        sent_at = float(env["sent_at"])
    except (TypeError, ValueError):
        return ValidationResult(False, "sent_at is not numeric")
    age = now - sent_at
    if age > ctx.stale_seconds:
        return ValidationResult(False, f"stale message: age {age:.2f}s > {ctx.stale_seconds}s")
    if age < -ctx.stale_seconds:
        return ValidationResult(False, f"future-dated message: {-age:.2f}s ahead")

    # Command types must bind exactly to the expected account + instrument.
    if mtype in COMMAND_TYPES:
        if ctx.expected_account is not None:
            if str(env.get("account", "")).strip() != ctx.expected_account:
                return ValidationResult(False,
                                        f"command account {env.get('account')!r} != expected "
                                        f"{ctx.expected_account!r}")
        if ctx.expected_instrument is not None:
            if str(env.get("instrument", "")).strip() != ctx.expected_instrument:
                return ValidationResult(False,
                                        f"command instrument {env.get('instrument')!r} != "
                                        f"expected {ctx.expected_instrument!r}")

    return ValidationResult(True, "valid", env)


class SequenceTracker:
    """Tracks sequence numbers and command idempotency per correlation stream.

    * Duplicate message_id for a command -> idempotent (returns the first result
      marker instead of re-processing).
    * Out-of-sequence bars/updates are SURFACED (not silently accepted).
    """

    def __init__(self):
        self._last_seq = None
        self._seen_ids = {}   # message_id -> stored result marker

    def seen(self, message_id: str) -> bool:
        return message_id in self._seen_ids

    def record(self, message_id: str, result_marker=True):
        self._seen_ids[message_id] = result_marker
        return result_marker

    def note_idempotent(self, message_id: str):
        """Return (is_duplicate, stored_marker)."""
        if message_id in self._seen_ids:
            return True, self._seen_ids[message_id]
        return False, None

    def check_sequence(self, sequence: int) -> Optional[str]:
        """Return None if in-order; a human message if out-of-order (surfaced)."""
        seq = int(sequence)
        prev = self._last_seq
        self._last_seq = seq if prev is None else max(prev, seq)
        if prev is None:
            return None
        if seq <= prev:
            return f"out-of-sequence: got {seq} after {prev}"
        if seq > prev + 1:
            return f"sequence gap: jumped {prev} -> {seq}"
        return None
