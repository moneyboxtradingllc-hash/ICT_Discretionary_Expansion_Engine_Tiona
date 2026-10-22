"""Disarmed-rehearsal pytest plugin (evidence tooling, not production code).

- Every socket connect is recorded with the running test; anything that is not
  loopback or a Unix socket is refused before it leaves the host. A loopback
  connect to the runner's dead proxy port 9 is recorded as an egress attempt.
- sys.monitoring records the first test that reaches each function defined in
  the production paths (src/broker, src/live_scan, src/integrations,
  src/recognition_validation, tools/topstepx_production_session.py, src/main.py).
- OUT (set by the launcher) receives REHEARSAL_TRACE JSON at session end.
"""
import json
import os
import socket
import sys
from pathlib import Path

ROOT = Path.cwd().resolve()
WATCH = tuple(str(ROOT / p) for p in ("src/broker", "src/live_scan", "src/integrations",
                                       "src/recognition_validation", "tools/topstepx_production_session.py",
                                       "src/main.py"))
OUT = None
_hits, _connects, _current = {}, [], ["<collection>"]
_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex
_TOOL = 4


def _classify(sock, address):
    if sock.family == getattr(socket, "AF_UNIX", -1):
        return "unix", False
    host, port = (address[0], address[1]) if isinstance(address, tuple) else (str(address), None)
    if host in ("127.0.0.1", "::1", "localhost"):
        return ("loopback_dead_proxy_port_9" if port == 9 else "loopback"), False
    return "non_loopback", True


def _guarded(original):
    def connect(self, address):
        kind, refuse = _classify(self, address)
        _connects.append({"test": _current[0], "kind": kind, "refused": refuse,
                          "address": repr(address) if not refuse else repr(address)[:80]})
        if refuse:
            raise ConnectionRefusedError("DISARMED REHEARSAL: non-loopback connect refused")
        return original(self, address)
    return connect


_ROOT_STR = str(ROOT)
_ROOT_PREFIX = _ROOT_STR + "/"
_rearmed = []
_callback_errors = []


def _start(code, offset):
    # Exception-proof and string-only: an exception or a patched helper must never switch recording off.
    try:
        # Normalise: tests import through paths such as ".../tests/../src/broker/x.py" or relative entries.
        name = os.path.normpath(os.path.join(_ROOT_STR, code.co_filename))
        if name.startswith(WATCH):
            _hits.setdefault(name[len(_ROOT_PREFIX):] + "::" + code.co_qualname, _current[0])
    except BaseException as exc:  # noqa: BLE001
        if len(_callback_errors) < 50:
            _callback_errors.append(f"{_current[0]}: {type(exc).__name__}")
    return sys.monitoring.DISABLE


def _arm():
    sys.monitoring.register_callback(_TOOL, sys.monitoring.events.PY_START, _start)
    sys.monitoring.set_events(_TOOL, sys.monitoring.events.PY_START)


def pytest_configure(config):
    socket.socket.connect = _guarded(_original_connect)
    socket.socket.connect_ex = _guarded(_original_connect_ex)
    sys.monitoring.use_tool_id(_TOOL, "stage5_rehearsal")
    _arm()


def pytest_runtest_protocol(item, nextitem):
    _current[0] = item.nodeid
    # Re-assert recording before every test and record any test after which it had been switched off.
    if sys.monitoring.get_tool(_TOOL) != "stage5_rehearsal" or sys.monitoring.get_events(_TOOL) != sys.monitoring.events.PY_START:
        _rearmed.append(item.nodeid)
        if sys.monitoring.get_tool(_TOOL) is None:
            sys.monitoring.use_tool_id(_TOOL, "stage5_rehearsal")
        _arm()


def pytest_sessionfinish(session, exitstatus):
    sys.monitoring.set_events(_TOOL, 0)
    socket.socket.connect, socket.socket.connect_ex = _original_connect, _original_connect_ex
    if OUT:
        Path(OUT).write_text(json.dumps({"exitstatus": int(exitstatus), "connects": _connects,
                                         "function_first_hit": dict(sorted(_hits.items())),
                                         "recording_rearmed_before": _rearmed, "callback_errors": _callback_errors}, indent=1))
