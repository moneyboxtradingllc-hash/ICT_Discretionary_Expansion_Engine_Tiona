"""Isolation and no-lookahead guards for the offline replay harness.

Nothing in this module reads evidence. It only refuses things:

* the network (every socket connect / name lookup raises);
* reading an outcome while the decision pass is running;
* market data, quotes or a model answer requested ahead of their recorded time.

Each refusal raises and carries the name of the rule that fired, so a planted
failure can be proven to fail for the intended reason and not by accident.
"""
from __future__ import annotations

import os
import re
import socket
from datetime import datetime

RULE_T_MARKET = "T_MARKET"      # market data stamped after the snapshot time
RULE_T_QUOTE = "T_QUOTE"        # a quote captured after the recorded quote
RULE_T_ANSWER = "T_ANSWER"      # the model answer consumed before it existed
RULE_T_OUTCOME = "T_OUTCOME"    # an outcome read during the decision pass
RULE_NETWORK = "NETWORK"

PHASE_DECISION = "DECISION_PASS"
PHASE_COMPARISON = "COMPARISON_PASS"


class LookaheadViolation(RuntimeError):
    def __init__(self, rule: str, requested: str, limit: str, what: str = "") -> None:
        super().__init__(f"{rule}: requested {requested} but limit is {limit}"
                         + (f" ({what})" if what else ""))
        self.rule, self.requested, self.limit, self.what = rule, requested, limit, what


class IsolationViolation(RuntimeError):
    def __init__(self, what: str) -> None:
        super().__init__(f"{RULE_NETWORK}: {what} refused; the harness is offline")
        self.rule = RULE_NETWORK


def block_network() -> None:
    """Make every outbound connection and name lookup raise."""
    def _refuse(*_a, **_k):
        raise IsolationViolation("network access")
    socket.socket.connect = _refuse
    socket.socket.connect_ex = _refuse
    socket.socket.sendto = _refuse
    socket.create_connection = _refuse
    socket.getaddrinfo = _refuse
    socket.gethostbyname = _refuse


_SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASS|CREDENTIAL|OPENAI|TOPSTEP|PROJECTX|"
                          r"ANTHROPIC|ALPACA|ACCOUNT|USERNAME", re.I)


def scrub_environment() -> list:
    """Drop credential-looking variables so no frozen module can pick one up."""
    removed = sorted(k for k in os.environ if _SECRET_NAME.search(k))
    for k in removed:
        os.environ.pop(k, None)
    return removed


def parse_ts(value) -> datetime:
    return datetime.fromisoformat(str(value))


class Phase:
    """Which pass is running. The outcome store consults this on every read."""

    def __init__(self) -> None:
        self.current = PHASE_DECISION

    def enter_comparison(self) -> None:
        self.current = PHASE_COMPARISON


class OutcomeStore:
    """The only door to anything recorded AFTER a decision.

    Decision rows, missions and submissions are outcomes. They are opened only
    through this object, and it refuses while the decision pass is running.
    """

    def __init__(self, phase: Phase) -> None:
        self._phase = phase
        self.reads = 0

    def open(self, path: str, field: str = ""):
        if self._phase.current != PHASE_COMPARISON:
            raise LookaheadViolation(RULE_T_OUTCOME, field or os.path.basename(path),
                                     "comparison pass only",
                                     "outcome requested during the decision pass")
        self.reads += 1
        return open(path, encoding="utf-8")


#: Timestamps inside a snapshot that are not market data and may lie after the
#: snapshot time. Each one is named here so nothing is waved through silently.
NON_MARKET_STAMPS = (
    (re.compile(r"^/session_context/cme_trading_day/end$"),
     "calendar boundary of the trading day"),
    (re.compile(r"^/session_context/contexts/[A-Z_]+/window/end$"),
     "scheduled clock time at which a named session window ends"),
)


def non_market_reason(path: str):
    for pattern, reason in NON_MARKET_STAMPS:
        if pattern.match(path):
            return reason
    return None
QUOTE_STAMPS = {"/execution_price/captured_at", "/market/execution_price/captured_at"}

_ISO = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d")


def iso_stamps(obj, path=""):
    """Every value that is an ISO timestamp, with its path (list indexes dropped)."""
    if isinstance(obj, dict):
        for k in sorted(obj):
            yield from iso_stamps(obj[k], f"{path}/{k}")
    elif isinstance(obj, list):
        for v in obj:
            yield from iso_stamps(v, path)
    elif isinstance(obj, str) and _ISO.match(obj):
        yield path, obj


class ScanClock:
    """The three recorded times of one scan, and the gates that enforce them."""

    def __init__(self, *, t_market: str, t_quote, t_call_started, t_answer: str) -> None:
        self.t_market = parse_ts(t_market)
        self.t_quote = parse_ts(t_quote) if t_quote else None
        self.t_call_started = parse_ts(t_call_started) if t_call_started else None
        self.t_answer = parse_ts(t_answer)

    def request_market_data(self, stamp: str, what: str = "") -> None:
        try:
            ts = parse_ts(stamp)
            late = ts > self.t_market
        except (ValueError, TypeError):
            return                      # not a comparable timestamp
        if late:
            raise LookaheadViolation(RULE_T_MARKET, str(stamp),
                                     self.t_market.isoformat(), what)

    def request_quote(self, captured_at: str, what: str = "") -> None:
        if self.t_quote is None:
            raise LookaheadViolation(RULE_T_QUOTE, str(captured_at),
                                     "no quote recorded", what)
        if parse_ts(captured_at) > self.t_quote:
            raise LookaheadViolation(RULE_T_QUOTE, str(captured_at),
                                     self.t_quote.isoformat(), what)

    def release_answer(self, at: datetime, what: str = "") -> datetime:
        if at < self.t_answer:
            raise LookaheadViolation(RULE_T_ANSWER, at.isoformat(),
                                     self.t_answer.isoformat(), what)
        return at

    def audit(self, snapshot: dict, brain_input: dict) -> list:
        """Pass every timestamp in the recorded inputs through the gates.

        Returns the list of refusals instead of raising, so one bad stamp in
        recorded evidence is reported per scan rather than hiding the rest.
        """
        findings = []
        for label, obj in (("snapshot", snapshot), ("brain_input", brain_input)):
            for path, stamp in iso_stamps(obj):
                try:
                    if path in QUOTE_STAMPS:
                        self.request_quote(stamp, f"{label}{path}")
                        if (self.t_call_started is not None
                                and parse_ts(stamp) > self.t_call_started):
                            raise LookaheadViolation(
                                RULE_T_QUOTE, stamp, self.t_call_started.isoformat(),
                                f"{label}{path} captured after the model call started")
                    elif non_market_reason(path):
                        continue
                    else:
                        self.request_market_data(stamp, f"{label}{path}")
                except LookaheadViolation as exc:
                    findings.append({"rule": exc.rule, "path": f"{label}{path}",
                                     "stamp": stamp, "limit": exc.limit})
        return findings
