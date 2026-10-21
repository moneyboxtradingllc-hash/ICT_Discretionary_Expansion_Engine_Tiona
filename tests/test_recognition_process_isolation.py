"""Stage 5 gap mission 2: a fresh allowlisted child process per trajectory.

Owner-audit counterexample: `driver.isolation` only redirects directories and
environment inside one interpreter, so narrative_brain's provider circuit (and
every other module global) survives into the "next" trajectory. The CLI now
runs every trajectory in its own `python -I` child with an environment built
from an allowlist; these tests contaminate the parent and a prior child and
show the next child is cold and still reaches and consumes a controlled
(MOCK, CONSTRUCTED) Brain response in both ECU lanes. No model, provider,
venue or network is reached.
"""
import json
import os
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import test_recognition_scoring_cli as SCLI  # noqa: E402
from ai_brain import narrative_brain as N  # noqa: E402
from recognition_validation import __main__ as CLI  # noqa: E402
from recognition_validation import child as CH  # noqa: E402
from recognition_validation import contracts as C  # noqa: E402
from recognition_validation import driver as DR  # noqa: E402
from recognition_validation import report as RP  # noqa: E402

world = SCLI.world
ORIGINAL_CONNECT = socket.socket.connect
UNTIL = "2026-08-19T15:44:00Z"   # a short scored stretch after the 15:30 prewarm keeps each child quick


@pytest.fixture(autouse=True)
def _short_schedule(monkeypatch):
    monkeypatch.setattr(SCLI, "UNTIL", UNTIL)
    yield
    N.reset_provider_circuit_for_tests()
    N.set_call_context()


def _script(tmp_path, name, body=""):
    """A Mode B script file: the CONSTRUCTED distinct-anchor Brain, plus an optional prelude per call."""
    path = tmp_path / f"{name}_script.py"
    path.write_text("import os, socket, sys, time\n"
                    f"sys.path.insert(0, {str(ROOT / 'tests')!r})\n"
                    "import test_recognition_current_path as CP\n"
                    "from ai_brain import narrative_brain as N\n"
                    "_inner, _state = CP._script()\n"
                    "_calls = []\n"
                    "def script(request):\n"
                    "    _calls.append(1)\n"
                    + "".join(f"    {line}\n" for line in body.splitlines()) +
                    "    return _inner(request)\n")
    return path


def _cli_run(world, tmp_path, name, *, ecu, script, extra=(), trajectory=None, run=None):
    run = run or SCLI._run_doc(world, tmp_path / f"{name}.run.json", ecu=ecu,
                               trajectory_id=trajectory or f"S5-ISO-{name}")
    out = tmp_path / name
    code = CLI.main(["run", "--mode", "B", "--run", str(run), "--corpus", str(world["corpus_path"]), "--out", str(out),
                     "--script", str(script), "--prewarm-until", SCLI.PREWARM, "--ticks-until", UNTIL, *extra])
    return code, out / "evidence", run


def _status(evidence):
    return json.loads((evidence / CH.STATUS_FILE).read_text())


def _exit(evidence):
    return json.loads((evidence / CH.EXIT_FILE).read_text())


def _consumed_brain(evidence):
    """The child reached a controlled Brain response and the loop consumed it."""
    from recognition_validation import recorder as REC
    events, calls = REC.read_events(evidence), REC.read_calls(evidence)
    complete = [c for c in calls if c["purpose"] == "PRIMARY" and c["record_status"] == "COMPLETE"
                and c["post_guard_output_ref"] and c["evaluation_origin"] == "MOCK"]
    after_brain = [e for e in events if e["primary_call_count"] and e["outcome"] not in ("BRAIN_DEGRADED",
                                                                                        "BRAIN_SLEEP_HOLD")]
    return bool(complete) and bool(after_brain)


# -- the parent counterexample stays documented: env/CWD redirection is not a process --

def test_in_process_isolation_context_is_not_process_isolation(tmp_path):
    N._open_hard_quota_circuit("CONSTRUCTED_PRIOR_TRAJECTORY")
    with DR.isolation(tmp_path / "ctx", ecu=False):
        assert N.provider_circuit_state()["open"]  # the reason the CLI must use a child
    receipt = CH.verify_child_status(tmp_path, {"process_isolation": {"kind": "IN_PROCESS"}})
    assert receipt == ["CHILD_STATUS_MISSING"]


# -- contaminated parent -> cold child, both lanes ------------------------------

def test_contaminated_parent_never_reaches_the_child_in_either_lane(world, tmp_path, monkeypatch, capsys):
    N._open_hard_quota_circuit("CONSTRUCTED_PRIOR_TRAJECTORY")
    N.set_call_context(session_id="CONSTRUCTED-PRIOR-TRAJECTORY", scan=99)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-must-never-be-used")
    monkeypatch.setenv("TOPSTEPX_API_KEY", "must-never-be-used")
    script = _script(tmp_path, "healthy")
    for ecu in (False, True):
        code, evidence, _ = _cli_run(world, tmp_path, f"lane-{ecu}", ecu=ecu, script=script)
        assert code == 0
        manifest = RP.read_manifest(evidence)
        receipt = manifest["process_isolation"]
        assert receipt["kind"] == "FRESH_CHILD" and manifest["ecu"] is ecu
        assert receipt["pid"] != os.getpid() and receipt["ppid"] == os.getpid() and receipt["isolation_flags"] == ["-I"]
        assert receipt["cold_state"]["provider_circuit"] == {"open": False, "reason": None}
        assert receipt["cold_state"]["call_context"]["session_id"] == ""
        assert receipt["preloaded_runtime_modules"] == []
        assert set(receipt["env_names"]) <= CH.ENV_ALLOWLIST | set(CH.INJECTED_ENV)
        assert not {"OPENAI_API_KEY", "TOPSTEPX_API_KEY"} & set(receipt["env_names"])
        assert receipt["source_identity"] == C.source_identity()
        status, child_exit = _status(evidence), _exit(evidence)
        assert status["complete"] and status["state"] == "EXITED" and status["exit_code"] == 0
        # The production scan-cycle import path calls load_dotenv(); in the child it reads nothing.
        assert set(child_exit["dotenv_refused"]) <= {"load_dotenv"} and child_exit["launcher_modules_loaded"] == []
        assert child_exit["env_grew_outside_allowlist"] == []
        assert child_exit["network_attempts"] == [] and manifest["venue_writes"] == []
        assert manifest["primary_calls"] > 0 and _consumed_brain(evidence)
        assert CH.verify_child_status(evidence, manifest) == []
        report_out = tmp_path / f"report-{ecu}"
        CLI.main(["report", "--run", str(evidence.parent), "--out", str(report_out)])
        result = json.loads((report_out / "result.json").read_text())
        assert result["engineering_status"] == "COMPLETE"
        assert not any(m.startswith("PROCESS_ISOLATION_UNPROVEN") for m in result["missing_prerequisites"])
    # The parent's own contamination is untouched: nothing was shared in either direction.
    assert N.provider_circuit_state() == {"open": True, "reason": "CONSTRUCTED_PRIOR_TRAJECTORY"}
    capsys.readouterr()


def test_prior_child_contamination_does_not_reach_the_next_child(world, tmp_path, capsys):
    poison = _script(tmp_path, "poison", body=(
        "N._open_hard_quota_circuit('CONSTRUCTED_PRIOR_TRAJECTORY')\n"
        "N.set_call_context(session_id='CONSTRUCTED-PRIOR-TRAJECTORY', scan=99)"))
    code, first, _ = _cli_run(world, tmp_path, "prior", ecu=False, script=poison)
    assert code == 0 and _exit(first)["final_provider_circuit"]["open"] is True
    code, second, _ = _cli_run(world, tmp_path, "next", ecu=False, script=_script(tmp_path, "healthy"))
    assert code == 0
    receipt = RP.read_manifest(second)["process_isolation"]
    assert receipt["cold_state"]["provider_circuit"]["open"] is False
    assert receipt["pid"] != RP.read_manifest(first)["process_isolation"]["pid"]
    assert _exit(second)["final_provider_circuit"]["open"] is False and _consumed_brain(second)
    capsys.readouterr()


# -- failure, truncation, timeout: never a complete result ---------------------

def test_failing_or_truncated_child_is_incomplete_never_a_pass(world, tmp_path, capsys):
    crash = _script(tmp_path, "crash", body="if len(_calls) == 3:\n    os._exit(9)")
    code, evidence, _ = _cli_run(world, tmp_path, "crash", ecu=False, script=crash)
    assert code == CLI.EXIT_INFRA
    status = _status(evidence)
    assert status["state"] == "EXITED" and status["exit_code"] == 9 and status["complete"] is False
    assert not (evidence / "RUN_MANIFEST.json").exists() and (evidence / "events.jsonl").exists()
    assert CLI.main(["report", "--run", str(evidence.parent), "--out", str(tmp_path / "crash-report")]) == \
        CLI.EXIT_INFRA
    result_path = tmp_path / "crash-report" / "result.json"
    if result_path.exists():
        result = json.loads(result_path.read_text())
        assert result["engineering_status"] != "COMPLETE" and result["final_status"] != "READY_FOR_OWNER_REVIEW"
    capsys.readouterr()


def test_timed_out_child_is_killed_and_incomplete(world, tmp_path, capsys):
    hang = _script(tmp_path, "hang", body="time.sleep(120)")
    code, evidence, _ = _cli_run(world, tmp_path, "hang", ecu=True, script=hang, extra=("--child-timeout", "8"))
    assert code == CLI.EXIT_INFRA
    status = _status(evidence)
    assert status["state"] == "TIMEOUT" and status["complete"] is False and status["manifest_sha256"] is None
    capsys.readouterr()


# -- refusals before any runtime import, each beside a reachable healthy control ---

def _request(world, tmp_path, name):
    run = SCLI._run_doc(world, tmp_path / f"{name}.run.json", trajectory_id=f"S5-ISO-{name}")
    script = _script(tmp_path, name)
    return CLI.trajectory_request(C.loads_strict(run.read_text()), run, world["corpus_path"], session=None,
                                  mode="B", script=str(script), records=None, prewarm_until=SCLI.PREWARM,
                                  ticks_until=UNTIL)


def test_child_refuses_unallowlisted_env_source_mismatch_seed_and_altered_responder(world, tmp_path):
    healthy = CH.run_in_child(_request(world, tmp_path, "control"), out_root=tmp_path / "control")
    assert healthy["complete"] is True
    cases = {
        "credential": (dict(), {"OPENAI_API_KEY": "sk-must-never-be-used"}, "CHILD_ENV_NOT_ALLOWLISTED"),
        "source": ({"expected_source_identity": "MUTATE"}, None, "RUN_SOURCE_MISMATCH"),
        "seed": ({"memory_policy": "SEALED_SEED"}, None, "MEMORY_SEED_ADAPTER_UNAVAILABLE"),
        "responder": ({"responder": "MUTATE"}, None, "CHILD_RESPONDER_DIGEST_MISMATCH"),
    }
    for name, (override, env, code) in cases.items():
        request = _request(world, tmp_path, name)
        if override.get("expected_source_identity") == "MUTATE":
            override = {"expected_source_identity": dict(request["expected_source_identity"], source_sha="0" * 40)}
        if override.get("responder") == "MUTATE":
            override = {"responder": dict(request["responder"], sha256="0" * 64)}
        status = CH.run_in_child(dict(request, **override), out_root=tmp_path / name, extra_env=env)
        assert status["complete"] is False and status["manifest_sha256"] is None, name
        assert status["child_exit"]["status"] == "REFUSED" and status["child_exit"]["code"] == code, name
        assert status["exit_code"] in (2, 3)


def test_network_attempt_inside_the_child_is_refused_and_recorded(world, tmp_path, capsys):
    reach = _script(tmp_path, "reach", body=(
        "if len(_calls) == 1:\n"
        "    try:\n"
        "        socket.create_connection(('provider.invalid', 443), timeout=1)\n"
        "    except OSError:\n"
        "        pass"))
    code, evidence, _ = _cli_run(world, tmp_path, "reach", ecu=False, script=reach)
    assert code == CLI.EXIT_INVARIANT
    manifest = RP.read_manifest(evidence)
    assert any("provider.invalid" in a for a in manifest["network_attempts"])
    CLI.main(["report", "--run", str(evidence.parent), "--out", str(tmp_path / "reach-report")])
    result = json.loads((tmp_path / "reach-report" / "result.json").read_text())
    assert "NETWORK_ATTEMPTED_OFFLINE" in result["invariant_failures"] and result["engineering_status"] == "FAIL"
    capsys.readouterr()


# -- clean restart: same semantic trace, process identities disclosed ------------

def test_clean_restart_reproduces_the_trace_and_discloses_process_identity(world, tmp_path, capsys):
    script = _script(tmp_path, "healthy")
    # The same sealed run document twice: only the process may differ.
    run = SCLI._run_doc(world, tmp_path / "restart.run.json", ecu=False, trajectory_id="S5-ISO-RESTART")
    _, left, _ = _cli_run(world, tmp_path, "left", ecu=False, script=script, run=run)
    _, right, _ = _cli_run(world, tmp_path, "right", ecu=False, script=script, run=run)
    assert CLI.main(["compare", "--left", str(left.parent), "--right", str(right.parent)]) == 0
    report = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    disclosure = report["process_identity"]
    assert disclosure["left"]["kind"] == disclosure["right"]["kind"] == "FRESH_CHILD"
    assert disclosure["left"]["pid"] != disclosure["right"]["pid"]
    assert disclosure["source_identity_equal"] is True and disclosure["run_digest_equal"] is True
    # Raw traces keep their process identities (they differ); only the semantic projection is equal.
    assert report["left"]["raw_events_sha256"] != report["right"]["raw_events_sha256"]
    assert report["left"]["semantic_events_sha256"] == report["right"]["semantic_events_sha256"]


# -- activated control: the same-process path is detected, not trusted ----------

def test_same_process_reuse_is_refused_by_the_child_guards(world, tmp_path):
    """Running the child entry inside an already-contaminated interpreter (the parent
    defect) fails its own isolation checks instead of producing a trajectory."""
    request = _request(world, tmp_path, "inproc")
    out = tmp_path / "inproc"
    (out / "child").mkdir(parents=True)
    path = out / "child" / "request.json"
    path.write_bytes(C.canonical(dict(request, out_root=str(out.resolve()))))
    N._open_hard_quota_circuit("CONSTRUCTED_PRIOR_TRAJECTORY")
    assert CH.child_main(str(path)) == 2
    record = json.loads((out / "evidence" / CH.EXIT_FILE).read_text())
    assert record["code"] in ("CHILD_ENV_NOT_ALLOWLISTED", "CHILD_RUNTIME_PRELOADED", "CHILD_NOT_COLD")
    assert not (out / "evidence" / "RUN_MANIFEST.json").exists()
    assert socket.socket.connect is ORIGINAL_CONNECT  # the child's deny is scoped, never leaked


def test_report_binds_the_child_status_of_a_complete_looking_trace(world, tmp_path, capsys):
    """A sealed manifest is not enough: the parent-side child status must show a clean exit
    bound to the same request, or the run stays INCOMPLETE."""
    import shutil
    code, evidence, _ = _cli_run(world, tmp_path, "bound", ecu=False, script=_script(tmp_path, "healthy"))
    assert code == 0
    assert CLI.main(["report", "--run", str(evidence.parent), "--out", str(tmp_path / "ok")]) == CLI.EXIT_MISSING
    assert json.loads((tmp_path / "ok" / "result.json").read_text())["engineering_status"] == "COMPLETE"

    def tampered(name, mutate):
        copy = tmp_path / name
        shutil.copytree(evidence.parent, copy)
        mutate(copy / "evidence" / CH.STATUS_FILE)
        assert CLI.main(["report", "--run", str(copy), "--out", str(tmp_path / f"{name}-r")]) == CLI.EXIT_INFRA
        result = json.loads((tmp_path / f"{name}-r" / "result.json").read_text())
        assert result["engineering_status"] == "INCOMPLETE" and result["final_status"] == "ENGINEERING_INCOMPLETE"
        return result["provenance"]["notes"]

    def crashed(path):
        status = json.loads(path.read_text())
        path.write_text(json.dumps(dict(status, exit_code=9, complete=False)))
    assert "CHILD_PROCESS_EXITED_9" in tampered("crashed", crashed)
    assert "CHILD_STATUS_MISSING" in tampered("nostatus", lambda path: path.unlink())

    def foreign(path):
        status = json.loads(path.read_text())
        path.write_text(json.dumps(dict(status, request_sha256="0" * 64)))
    assert "CHILD_REQUEST_BINDING_MISMATCH" in tampered("foreign", foreign)
    capsys.readouterr()
