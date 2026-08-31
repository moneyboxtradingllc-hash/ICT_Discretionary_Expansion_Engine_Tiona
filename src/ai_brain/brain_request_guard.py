"""Single-flight, binding and staleness guard for external Brain requests.

Prerequisite for raising `AI_BRAIN_TIMEOUT_SECONDS` (operator correction,
2026-08-04): a longer timeout is only safe if a slow request cannot overlap the
next scan, and a late answer cannot re-enter the authority path.

MEASURED BASELINE (live scan path, 2026-08-04):

  * `scan_loop` is a single-threaded `while True` loop; no thread, task or
    executor exists anywhere in the Brain path.
  * `SCAN_INTERVAL_SECONDS` defaults to 60; `_sleep_remainder` sleeps only the
    remainder, so a slow scan delays the next one instead of overlapping it.
  * PIPE-1/ECU collapsed the duplicate call, so there is ONE canonical Brain
    call per scan.

Sequential-by-construction is a good property to have; it is a bad property to
DEPEND on silently, because a future scheduler change would remove it without
any test noticing. This module makes it explicit and enforced.

WHY BINDING MATTERS MORE THAN TIMEOUT. A slow response is not merely late — it
answers a question about a market that has moved on. A 44-second-old read of a
snapshot whose price has since travelled is not a valid basis for exposure even
though it arrived inside the timeout. So every request is bound to the snapshot
it evaluated, and the binding is re-checked when the answer comes back.

THE TIMEOUT: 45 seconds. Measured full-payload Luna latency was 12.9-15.5s on a
1.8k-token probe; the live payload is ~6-8k tokens. 45s leaves 15s of headroom
inside the 60s cadence, so a worst-case slow call still lands before the next
scan is due. 60s was rejected: it consumes the whole interval and turns one slow
call into permanent cadence slip.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

DEFAULT_TIMEOUT_SECONDS = 45.0

# Terminal telemetry states. A timeout is a NAMED outcome, never a silent
# no-trade — an operator must be able to tell "the Brain timed out" from
# "the Brain saw nothing worth taking".
AI_OK = "AI_OK"
AI_TIMEOUT = "AI_TIMEOUT"
AI_FALLBACK = "AI_FALLBACK"
AI_STALE = "AI_STALE"
AI_SUPERSEDED = "AI_SUPERSEDED"
AI_BUSY = "AI_BUSY"


class BrainBusyError(RuntimeError):
    """A Brain request is already in flight. Overlap is refused, never queued."""


class StaleResponseError(RuntimeError):
    """The answer no longer describes an operationally valid market state."""


@dataclass(frozen=True)
class RequestBinding:
    """What a Brain request was asked ABOUT. Re-checked on the way back."""
    request_id: str
    snapshot_id: str
    snapshot_timestamp: str
    market_data_timestamp: str
    contract_id: str
    account_fingerprint: str
    issued_at: datetime

    def matches(self, *, snapshot_id: str, contract_id: str,
                account_fingerprint: str) -> tuple:
        """Returns (ok, reason). Any drift invalidates the answer."""
        if snapshot_id != self.snapshot_id:
            return False, "snapshot_superseded"
        if contract_id != self.contract_id:
            return False, "contract_mismatch"
        if account_fingerprint != self.account_fingerprint:
            return False, "account_mismatch"
        return True, None

    def evidence(self) -> dict:
        return {"request_id": self.request_id, "snapshot_id": self.snapshot_id,
                "snapshot_timestamp": self.snapshot_timestamp,
                "market_data_timestamp": self.market_data_timestamp,
                "contract_id": self.contract_id,
                "account_fingerprint": self.account_fingerprint,
                "issued_at": self.issued_at.isoformat()}


@dataclass
class BrainRequestGuard:
    """Enforces one in-flight request, binding, staleness and telemetry."""

    max_response_age_seconds: float = 90.0
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _in_flight: Optional[RequestBinding] = None
    _abandoned: set = field(default_factory=set)
    telemetry: list = field(default_factory=list)

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def begin(self, *, request_id: str, snapshot_id: str, snapshot_timestamp: str,
              market_data_timestamp: str, contract_id: str,
              account_fingerprint: str, now: Optional[datetime] = None) -> RequestBinding:
        """Claim the single flight slot. Raises BrainBusyError if occupied.

        Refusing rather than queueing is deliberate: a queued request would be
        answered against an even older snapshot, which is the exact failure the
        binding exists to prevent.
        """
        with self._lock:
            if self._in_flight is not None:
                self._record(AI_BUSY, request_id, "a Brain request is already in flight")
                raise BrainBusyError(
                    f"Brain request {self._in_flight.request_id} is already in flight; "
                    f"{request_id} refused (overlap is not permitted)")
            binding = RequestBinding(
                request_id=request_id, snapshot_id=snapshot_id,
                snapshot_timestamp=snapshot_timestamp,
                market_data_timestamp=market_data_timestamp,
                contract_id=contract_id, account_fingerprint=account_fingerprint,
                issued_at=now or datetime.now(timezone.utc))
            self._in_flight = binding
            return binding

    def abandon(self, binding: RequestBinding, reason: str = AI_TIMEOUT) -> dict:
        """Give up on an in-flight request and POISON its id permanently.

        The slot is released so scanning continues, and the request id joins the
        abandoned set so that if the answer arrives later it can never be
        accepted. A timed-out request that is merely 'released' is a request
        that can still come back and authorize exposure.
        """
        with self._lock:
            if self._in_flight is not None and self._in_flight.request_id == binding.request_id:
                self._in_flight = None
            self._abandoned.add(binding.request_id)
        return self._record(reason, binding.request_id, "request abandoned; id poisoned")

    def complete(self, binding: RequestBinding, *, snapshot_id: str, contract_id: str,
                 account_fingerprint: str, latency_seconds: float,
                 now: Optional[datetime] = None) -> dict:
        """Accept an answer only if it is still valid. Always releases the slot."""
        now = now or datetime.now(timezone.utc)
        with self._lock:
            if self._in_flight is not None and self._in_flight.request_id == binding.request_id:
                self._in_flight = None
            poisoned = binding.request_id in self._abandoned

        if poisoned:
            return self._record(AI_SUPERSEDED, binding.request_id,
                                "answer arrived after the request was abandoned")
        if latency_seconds > self.timeout_seconds:
            self._abandoned.add(binding.request_id)
            return self._record(AI_TIMEOUT, binding.request_id,
                                f"latency {latency_seconds:.1f}s exceeded "
                                f"{self.timeout_seconds:.0f}s")
        ok, why = binding.matches(snapshot_id=snapshot_id, contract_id=contract_id,
                                  account_fingerprint=account_fingerprint)
        if not ok:
            self._abandoned.add(binding.request_id)
            return self._record(AI_STALE, binding.request_id, why)
        age = (now - binding.issued_at).total_seconds()
        if age > self.max_response_age_seconds:
            self._abandoned.add(binding.request_id)
            return self._record(AI_STALE, binding.request_id,
                                f"answer describes a snapshot {age:.0f}s old")
        return self._record(AI_OK, binding.request_id, "accepted")

    # ── queries ───────────────────────────────────────────────────────────────
    def is_busy(self) -> bool:
        with self._lock:
            return self._in_flight is not None

    def is_abandoned(self, request_id: str) -> bool:
        return request_id in self._abandoned

    def _record(self, state: str, request_id: str, detail: str) -> dict:
        entry = {"state": state, "request_id": request_id, "detail": detail,
                 "at": datetime.now(timezone.utc).isoformat()}
        self.telemetry.append(entry)
        return entry


def configured_timeout() -> float:
    """`AI_BRAIN_TIMEOUT_SECONDS`, defaulting to the audited 45s.

    Refuses to exceed the scan interval: a Brain timeout longer than the cadence
    guarantees the next scan is late, which is a cadence bug wearing a
    configuration hat.
    """
    try:
        value = float(os.getenv("AI_BRAIN_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS
    try:
        interval = float(os.getenv("SCAN_INTERVAL_SECONDS", "60"))
    except (TypeError, ValueError):
        interval = 60.0
    return min(value, max(interval - 5.0, 5.0))
