"""One fresh, allowlisted child process per trajectory (contract 09; gap mission 2).

Redirecting directories and environment inside one Python process does not
isolate a trajectory: module globals such as narrative_brain's provider
circuit, call context and caches survive it. The CLI therefore never drives a
trajectory in its own interpreter. `run_in_child` writes a sealed request,
then starts a NEW interpreter (`-I`: no user site, no PYTHON* variables) with
an environment built from nothing but an allowlist and scratch roots. Inside
the child, `child_main` checks, before importing any runtime authority module:

- the environment holds only allowlisted names and no credential-like name;
- no production runtime module is loaded yet;
- the loaded checkout and fingerprints equal the request's expected identity.

It then installs the network deny for its whole lifetime, refuses dotenv
loading, builds the responder from verified bytes, records the cold provider
state, and runs the actual driver. The receipt is sealed into the run
manifest. The parent records the child's exit, timeout and stderr digest in
CHILD_STATUS.json. A child that crashed, timed out or left no manifest is
INCOMPLETE and can never produce a complete result.
"""
from __future__ import annotations

import json
import ntpath
import os
import posixpath
import re
import shutil
import subprocess
import sys
from pathlib import Path

from recognition_validation import contracts as C

SRC_ROOT = Path(__file__).resolve().parents[1]
REQUEST_SCHEMA = "trajectory_child_request/v1"
STATUS_FILE = "CHILD_STATUS.json"
EXIT_FILE = "CHILD_EXIT.json"
RUNTIME_ROOTS = ("AI_BRAIN_DIR", "AI_RETRIEVAL_DIR", "OCCURRENCE_LEDGER_DIR", "REPLAY_SESSIONS_DIR",
                 "PERFORMANCE_TABLES_DIR", "HTF_MEMORY_DIR", "GLOBAL_MEMORY_DIR")
_POSIX_ENV_NAMES = frozenset(("PATH", "LANG", "TZ", "HOME", "TMPDIR", "XDG_CACHE_HOME", "PYTHONIOENCODING",
                              "PYTHONDONTWRITEBYTECODE", "PYTHONHASHSEED", "EXECUTION_ENABLED", "ALLOW_PAPER_ORDERS",
                              "AI_BRAIN_LLM", "TWO_BRAIN_MODE", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY",
                              "STAGE5_TRAJECTORY_CHILD") + RUNTIME_ROOTS)
#: Names Windows itself needs in an environment built from nothing. Without SYSTEMROOT, Winsock (and so
#: asyncio's _overlapped) fails to initialise with WinError 10106; TEMP/TMP and USERPROFILE are the Windows
#: spellings of the scratch TMPDIR and HOME. Values are scratch roots or the OS directory, never inherited secrets.
WINDOWS_ENV_NAMES = ("SYSTEMROOT", "TEMP", "TMP", "USERPROFILE")


def env_allowlist(platform: str = os.name) -> frozenset:
    """The complete set of environment names a trajectory child may see on `platform` (an os.name value)."""
    return _POSIX_ENV_NAMES | frozenset(WINDOWS_ENV_NAMES) if platform == "nt" else _POSIX_ENV_NAMES


#: The complete set of environment names a trajectory child may see on this host.
ENV_ALLOWLIST = env_allowlist()
#: Names the interpreter or the OS adds to a child started from an emptied environment, admitted only with these
#: exact non-secret values: Python's PEP 538 locale coercion sets LC_CTYPE when LANG's C.UTF-8 does not exist
#: (macOS), and macOS CoreFoundation sets __CF_USER_TEXT_ENCODING (uid:encoding:region) in every process.
INJECTED_ENV = {"LC_CTYPE": re.compile(r"C\.UTF-8|C\.utf8|UTF-8"),
                "__CF_USER_TEXT_ENCODING": re.compile(r"0x[0-9A-Fa-f]{1,8}:0x[0-9A-Fa-f]{1,8}:0x[0-9A-Fa-f]{1,8}")}


def unallowlisted_env(environ) -> list:
    """Names a child may not see: outside the allowlist and not an exact interpreter/OS-injected value."""
    return sorted(name for name, value in environ.items() if name not in ENV_ALLOWLIST
                  and not (name in INJECTED_ENV and INJECTED_ENV[name].fullmatch(value)))
_CREDENTIAL = re.compile(r"(KEY|TOKEN|SECRET|PASSW|CREDENTIAL|AUTH|COOKIE|BEARER)", re.I)
#: Packages that make up the runtime authority stack; none may be loaded before isolation is proven.
RUNTIME_PACKAGES = ("ai_brain", "ai_retrieval", "ai_layer", "broker", "live_scan", "market_data", "integrations",
                    "data_feed", "main", "tools")
LAUNCHER_MODULES = ("tools.topstepx_production_session", "main")
_SECRET_VALUE = re.compile(r"(sk-[A-Za-z0-9_-]{8,}|Bearer\s+\S+|api[_-]?key\S*\s*[:=]\s*\S+)", re.I)
BOOTSTRAP = ("import sys; sys.path.insert(0, sys.argv[1]); "
             "from recognition_validation.child import child_main; sys.exit(child_main(sys.argv[2]))")


def _runtime_modules() -> list:
    return sorted(name for name in sys.modules
                  if name.split(".")[0] in RUNTIME_PACKAGES)


def _child_path(platform: str, environ, which) -> str:
    """The interpreter's directory, the OS tool directories and the directory of the Git the parent resolves
    (source identity runs git); Git is appended only when the OS directories do not already hold it."""
    paths = ntpath if platform == "nt" else posixpath
    dirs = [str(Path(sys.executable).parent)]
    if platform == "nt":
        dirs += [paths.join(environ["SYSTEMROOT"], "System32")] if environ.get("SYSTEMROOT") else []
    else:
        dirs += ["/usr/local/bin", "/usr/bin", "/bin"]
    git = which("git")
    if git and paths.dirname(git) not in dirs:
        dirs.append(paths.dirname(git))
    return paths.pathsep.join(dirs)


def child_environment(child_root: Path, *, ecu: bool, platform: str = os.name, environ=None,
                      which=None) -> dict:
    """Built from nothing: scratch home/tmp/cache, disarmed flags, refused proxy, runtime roots. On Windows it
    also carries the OS directory (SYSTEMROOT) and the Windows names of the scratch home and temp roots."""
    environ = os.environ if environ is None else environ
    env = {"PATH": _child_path(platform, environ, which or shutil.which),
           "LANG": "C.UTF-8", "TZ": "UTC", "HOME": str(child_root / "home"), "TMPDIR": str(child_root / "tmp"),
           "XDG_CACHE_HOME": str(child_root / "cache"), "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONHASHSEED": "0", "EXECUTION_ENABLED": "false", "ALLOW_PAPER_ORDERS": "false",
           "AI_BRAIN_LLM": "false", "TWO_BRAIN_MODE": "off", "HTTPS_PROXY": "http://127.0.0.1:9",
           "HTTP_PROXY": "http://127.0.0.1:9", "NO_PROXY": "", "STAGE5_TRAJECTORY_CHILD": "1"}
    for key in RUNTIME_ROOTS:
        env[key] = str(child_root.parent / "runtime" / key.lower())
    if platform == "nt":
        env.update(TEMP=env["TMPDIR"], TMP=env["TMPDIR"], USERPROFILE=env["HOME"])
        if environ.get("SYSTEMROOT"):
            env["SYSTEMROOT"] = environ["SYSTEMROOT"]
    for name in ("home", "tmp", "cache"):
        (child_root / name).mkdir(parents=True, exist_ok=True)
    return env


def _redact(text: str) -> str:
    return _SECRET_VALUE.sub("[REDACTED]", text)


def run_in_child(request: dict, *, out_root, timeout_seconds: float = 3600.0, extra_env: dict | None = None,
                 stdin_secret: str | None = None) -> dict:
    """Run one trajectory in a fresh interpreter; returns the parent-side status record.

    `stdin_secret` (a released CURRENT_EXTERNAL run only) reaches the child on
    its stdin, never its environment, argv or request file; the child reads it
    only after its authority admission passed."""
    C.require((stdin_secret is not None) == ((request.get("responder") or {}).get("kind") == "CURRENT_EXTERNAL"),
              "CHILD_SECRET_CHANNEL", "/responder/kind")
    out_root = Path(out_root)
    C.require(not out_root.exists() or not any(out_root.iterdir()), "OUTPUT_ROOT_REUSE", "/" + str(out_root))
    C.require(request.get("schema") == REQUEST_SCHEMA, "CHILD_REQUEST_SCHEMA", "/schema")
    child_root = out_root / "child"
    child_root.mkdir(parents=True)
    env = child_environment(child_root, ecu=bool(request["ecu"]))
    env.update(extra_env or {})  # test hook for the refusal controls; the CLI never passes it
    data = C.canonical(dict(request, out_root=str(out_root.resolve())))
    request_path = child_root / "request.json"
    request_path.write_bytes(data)
    command = [sys.executable, "-I", "-c", BOOTSTRAP, str(SRC_ROOT), str(request_path)]
    status = {"schema": "trajectory_child_status/v1", "request_sha256": C.sha256_hex(data),
              "parent_pid": os.getpid(), "executable": sys.executable, "isolation_flags": ["-I"],
              "timeout_seconds": timeout_seconds, "env_names": sorted(env)}
    try:
        stdin = ({"input": (stdin_secret + "\n").encode("utf-8")} if stdin_secret is not None
                 else {"stdin": subprocess.DEVNULL})
        completed = subprocess.run(command, cwd=child_root, env=env, capture_output=True, timeout=timeout_seconds,
                                   **stdin)
        status.update(state="EXITED", exit_code=completed.returncode, stdout=completed.stdout, stderr=completed.stderr)
    except subprocess.TimeoutExpired as expired:
        status.update(state="TIMEOUT", exit_code=None, stdout=expired.stdout or b"", stderr=expired.stderr or b"")
    stdout, stderr = status.pop("stdout"), status.pop("stderr")
    status.update(stdout_sha256=C.sha256_hex(stdout), stderr_sha256=C.sha256_hex(stderr),
                  stderr_tail=_redact(stderr[-4000:].decode("utf-8", "replace")))
    evidence = out_root / "evidence"
    evidence.mkdir(exist_ok=True)
    manifest_path, exit_path = evidence / "RUN_MANIFEST.json", evidence / EXIT_FILE
    status["manifest_sha256"] = C.sha256_hex(manifest_path.read_bytes()) if manifest_path.exists() else None
    status["child_exit"] = (C.loads_strict(exit_path.read_text(encoding="utf-8"), pointer="/" + EXIT_FILE)
                            if exit_path.exists() else None)
    status["complete"] = bool(status["state"] == "EXITED" and status["exit_code"] == 0
                              and status["manifest_sha256"]
                              and _successful_exit(status["child_exit"], status["request_sha256"]))
    with open(evidence / STATUS_FILE, "xb") as handle:
        handle.write(json.dumps(status, sort_keys=True, indent=1).encode("utf-8"))
    status["summary"] = _last_json(stdout)
    return status


def _last_json(stdout: bytes):
    for line in reversed(stdout.decode("utf-8", "replace").splitlines()):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _successful_exit(receipt, request_sha256) -> bool:
    """Completion is bound to the same request, not just a zero process exit."""
    return (isinstance(receipt, dict) and receipt.get("schema") == "trajectory_child_exit/v1"
            and receipt.get("status") == "RUN_COMPLETE" and receipt.get("exit_code") == 0
            and isinstance(request_sha256, str) and re.fullmatch(r"[0-9a-f]{64}", request_sha256) is not None
            and receipt.get("request_sha256") == request_sha256)


def verify_child_status(evidence_root, manifest: dict) -> list:
    """Problems that keep a child-recorded run INCOMPLETE (empty list: the child finished)."""
    root = Path(evidence_root)
    path = root / STATUS_FILE
    if not path.exists():
        return ["CHILD_STATUS_MISSING"]
    try:
        status = C.loads_strict(path.read_text(encoding="utf-8"), pointer="/" + STATUS_FILE)
    except (OSError, ValueError, C.ContractError):
        return ["CHILD_STATUS_INVALID"]
    if not isinstance(status, dict) or status.get("schema") != "trajectory_child_status/v1":
        return ["CHILD_STATUS_INVALID"]
    problems = []
    if status.get("state") != "EXITED" or status.get("exit_code") != 0:
        problems.append(f"CHILD_PROCESS_{status.get('state')}_{status.get('exit_code')}")
    if status.get("complete") is not True:
        problems.append("CHILD_RUN_NOT_COMPLETE")
    # Self-seals detect accidental edits, but can be recomputed. Reauthenticate
    # current bytes against what the parent actually observed after child exit.
    try:
        data = (root / "RUN_MANIFEST.json").read_bytes()
        if C.sha256_hex(data) != status.get("manifest_sha256"):
            problems.append("CHILD_MANIFEST_DIGEST_MISMATCH")
        if C.canonical(C.loads_strict(data.decode("utf-8"), pointer="/RUN_MANIFEST.json")) != C.canonical(manifest):
            problems.append("CHILD_MANIFEST_ARGUMENT_MISMATCH")
    except (OSError, ValueError, C.ContractError):
        problems.append("CHILD_MANIFEST_MISSING_OR_INVALID")
    try:
        child_exit = C.loads_strict((root / EXIT_FILE).read_text(encoding="utf-8"), pointer="/" + EXIT_FILE)
    except (OSError, ValueError, C.ContractError):
        problems.append("CHILD_EXIT_MISSING_OR_INVALID")
    else:
        if C.canonical(child_exit) != C.canonical(status.get("child_exit")):
            problems.append("CHILD_EXIT_RECEIPT_MISMATCH")
        if not _successful_exit(child_exit, status.get("request_sha256")):
            problems.append("CHILD_EXIT_NOT_COMPLETE")
    receipt = manifest.get("process_isolation") or {}
    if receipt.get("request_sha256") != status.get("request_sha256"):
        problems.append("CHILD_REQUEST_BINDING_MISMATCH")
    if receipt.get("pid") is None or receipt.get("pid") == status.get("parent_pid"):
        problems.append("CHILD_PID_NOT_DISTINCT")
    if receipt.get("ppid") != status.get("parent_pid"):
        problems.append("CHILD_PARENT_PID_MISMATCH")
    return problems


# -- inside the child ----------------------------------------------------------

def _refuse_dotenv(attempts: list) -> None:
    """Production `data_feed/__init__` calls `load_dotenv()` at import, on the scan-cycle
    import path, and python-dotenv walks up from that module to find an operator `.env`.
    In a trajectory child every such load is a recorded no-op: nothing is read, and the
    environment is re-checked against the allowlist after the run."""
    try:
        import dotenv
        import dotenv.main
    except ImportError:
        return
    results = {"load_dotenv": False, "dotenv_values": {}, "find_dotenv": ""}
    for name, value in results.items():
        def refused(*args, _name=name, _value=value, **kwargs):
            attempts.append(_name)
            return type(_value)(_value)
        setattr(dotenv, name, refused)
        setattr(dotenv.main, name, refused)


def _current_external(spec: dict, trajectory_id: str, receipt: dict):
    """A released Mode C responder: plan, authority and ledger first; the credential last.

    Every refusal here happens before stdin is read, so a DISABLED, unsealed,
    expired, mismatched or unpriced authorization never sees a credential."""
    import openai
    from recognition_validation import eval_plan as EP
    from recognition_validation import model_authority as MA
    from recognition_validation import provider_transport as PT
    plan = EP.load_plan(spec["plan_path"])
    C.require(plan["seal"]["sha256"] == spec["plan_seal"], "PLAN_SEAL_MISMATCH", "/responder/plan_seal")
    authorization = C.loads_strict(Path(spec["authorization_path"]).read_text(encoding="utf-8"),
                                   pointer="/authorization")
    pricing = C.loads_strict(Path(spec["pricing_path"]).read_text(encoding="utf-8"), pointer="/pricing")
    authority = EP.admit_release(plan, authorization, pricing, receipt_root=spec["receipt_root"])
    ledger = MA.BudgetLedger(spec["ledger_path"], authority.authorization, authority.per_request_bound,
                             binding=authorization["seal"]["sha256"])
    C.require(not ledger.halted, "RUN_HALTED", "/ledger", str(ledger.halted))
    secret = sys.stdin.readline().strip()
    C.require(bool(secret), "CREDENTIAL_MISSING", "/stdin")
    transport = PT.OpenAIChatTransport(openai, lambda: secret, timeout=float(spec["client_timeout_seconds"]))
    receipt["current_external"] = {"plan_seal": plan["seal"]["sha256"], "ledger_binding": ledger.binding,
                                   "sdk_version": transport.sdk_version, "endpoint": PT.ENDPOINT,
                                   "credential_channel": "STDIN_AFTER_ADMISSION"}
    return PT.CurrentExternalResponder(authority, ledger, transport, trajectory_id=trajectory_id)


def _responder(spec: dict, contract_id: str):
    from recognition_validation import brain_gateway as G
    data = Path(spec["path"]).read_bytes()
    C.require(C.sha256_hex(data) == spec["sha256"], "CHILD_RESPONDER_DIGEST_MISMATCH", "/responder/sha256")
    if spec["kind"] == "SCRIPT":
        import importlib.util
        module_spec = importlib.util.spec_from_file_location("stage5_mode_b_script", spec["path"])
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        C.require(callable(getattr(module, "script", None)), "MOCK_SCRIPT_MISSING", "/script")
        return G.ScriptedResponder(module.script, fixture_digest=spec["sha256"])
    C.require(spec["kind"] == "HISTORICAL", "CHILD_RESPONDER_KIND", "/responder/kind")
    records = C.loads_strict(data.decode("utf-8"), pointer="/records")
    return G.HistoricalResponder(records, contract_id=contract_id)


def _requested_kind(request_path: str):
    try:
        return (json.loads(Path(request_path).read_bytes()).get("responder") or {}).get("kind")
    except (OSError, ValueError, AttributeError):
        return None


def child_main(request_path: str) -> int:
    from recognition_validation import ports as P
    external = _requested_kind(request_path) == "CURRENT_EXTERNAL"
    if external:
        # The pinned provider host only; every venue, broker and other host stays refused.
        from recognition_validation import provider_transport as PT
        guard = PT.ProviderOnlyNetworkGuard()
    else:
        guard = P.NetworkGuard()
    deny = guard.deny()
    deny.__enter__()  # for the child's whole lifetime, before any runtime import
    exit_record = {"schema": "trajectory_child_exit/v1"}
    out_root = None
    try:
        data = Path(request_path).read_bytes()
        request = C.loads_strict(data.decode("utf-8"), pointer="/request")
        out_root = Path(request["out_root"])
        exit_record["request_sha256"] = C.sha256_hex(data)
        names = sorted(os.environ)
        unlisted = unallowlisted_env(os.environ)
        C.require(not unlisted, "CHILD_ENV_NOT_ALLOWLISTED", "/env", ",".join(unlisted))
        C.require(not [n for n in names if _CREDENTIAL.search(n)], "CHILD_CREDENTIAL_PRESENT", "/env")
        C.require(os.environ.get("STAGE5_TRAJECTORY_CHILD") == "1", "CHILD_MARKER_MISSING", "/env")
        preloaded = _runtime_modules()
        C.require(not preloaded, "CHILD_RUNTIME_PRELOADED", "/sys.modules", ",".join(preloaded))
        C.require(request["memory_policy"] == "EMPTY", "MEMORY_SEED_ADAPTER_UNAVAILABLE", "/memory_policy")
        for key in RUNTIME_ROOTS:
            root = Path(os.environ[key])
            C.require(not root.exists() or not any(root.iterdir()), "CHILD_RUNTIME_ROOT_NOT_FRESH", "/" + key)
        dotenv_attempts: list = []
        _refuse_dotenv(dotenv_attempts)
        identity = C.source_identity()
        C.require(identity == request["expected_source_identity"], "RUN_SOURCE_MISMATCH", "/expected_source_identity")
        from ai_brain import narrative_brain as N
        cold = {"provider_circuit": N.provider_circuit_state(), "call_context": dict(N._CALL_CONTEXT)}
        C.require(not cold["provider_circuit"]["open"], "CHILD_NOT_COLD", "/provider_circuit")
        receipt = {"kind": "FRESH_CHILD", "pid": os.getpid(), "ppid": os.getppid(), "executable": sys.executable,
                   "isolation_flags": [f for f, on in (("-I", sys.flags.isolated),) if on],
                   "request_sha256": exit_record["request_sha256"], "env_names": names,
                   "preloaded_runtime_modules": preloaded, "cold_state": cold, "source_identity": identity,
                   "network_denied_from_start": True, "memory_policy": request["memory_policy"]}
        from recognition_validation import driver as DR
        if external:
            C.require(request.get("mode") == "C", "CHILD_RESPONDER_KIND", "/mode")
            responder = _current_external(request["responder"], request["trajectory_id"], receipt)
        else:
            responder = _responder(request["responder"], request["contract_id"])
        ticks = [DR.Tick(t["ordinal"], C.instant(t["decision_time"]), t["kind"]) for t in request["ticks"]]
        summary = DR.run_offline(corpus_path=request["corpus_path"], session_id=request["session_id"],
                                 out_root=out_root, responder=responder, ecu=request["ecu"],
                                 trajectory_id=request["trajectory_id"], ticks=ticks,
                                 quote_policy=request["quote_policy"], run_document=request["run_document"],
                                 fingerprints=request["fingerprints"], process_receipt=receipt,
                                 network_guard=guard, controlled_quotes=request.get("controlled_quotes"))
        after = sorted(os.environ)
        exit_record.update(
            final_provider_circuit=N.provider_circuit_state(), dotenv_refused=dotenv_attempts,
            env_names_after=after, env_grew_outside_allowlist=unallowlisted_env(os.environ),
            launcher_modules_loaded=[m for m in LAUNCHER_MODULES if m in sys.modules],
            network_attempts=[str(a) for a in guard.attempts], infrastructure_error=summary["infrastructure_error"],
            provider_connections=[str(a) for a in getattr(guard, "admitted", [])],
            status="RUN_COMPLETE" if not summary["infrastructure_error"] else "RUN_INCOMPLETE")
        refused_writes_expected = request["run_document"].get("venue_lane", "DISARMED") == "REFUSING_VENUE_DOUBLE"
        code = 5 if summary["infrastructure_error"] else 4 if (summary["network_attempts"]
                                                                  or (summary["venue_writes"] and not refused_writes_expected)
                                                                  or exit_record["launcher_modules_loaded"]
                                                                  or exit_record["env_grew_outside_allowlist"]) else 0
        print(json.dumps({"status": exit_record["status"], "evidence_root": summary["evidence_root"],
                          **{k: summary[k] for k in ("ticks", "events", "primary_calls", "repair_calls",
                                                     "infrastructure_error")}}, sort_keys=True))
    except C.ContractError as error:
        exit_record.update(status="REFUSED", code=error.code, pointer=error.pointer)
        print(json.dumps({"status": "REFUSED", "code": error.code, "pointer": error.pointer,
                          "detail": error.detail}), file=sys.stderr)
        code = 3 if error.code.endswith(("_MISSING", "_ABSENT", "_UNAVAILABLE")) else 2
    finally:
        deny.__exit__(None, None, None)
    if out_root is not None:
        evidence = out_root / "evidence"
        evidence.mkdir(parents=True, exist_ok=True)
        exit_record["exit_code"] = code
        with open(evidence / EXIT_FILE, "xb") as handle:
            handle.write(json.dumps(exit_record, sort_keys=True, indent=1).encode("utf-8"))
    return code
