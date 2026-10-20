"""Stage 5 owner A/B return: trajectory child environment portability.

Owner-host counterexample (Windows 11, exact parent c962a3d and audit source
201c60c): the child environment is built with a fixed Unix PATH
(`/usr/local/bin:/usr/bin:/bin` beside the interpreter), so the isolated
Windows child cannot find Git and `contracts.source_identity` raises
FileNotFoundError [WinError 2] before any trajectory body. With Git supplied,
the child then fails in asyncio/_overlapped with WinError 10106, which is what
Winsock reports when a process is started without SYSTEMROOT (Python's
subprocess documentation: on Windows an explicit env must include a valid
SystemRoot). The repair keeps the POSIX environment exactly as submitted and,
on Windows only, adds the OS directory and the Windows names of the scratch
roots. No inherited name or value other than SYSTEMROOT and the Git directory
enters the child, and every child-side refusal is unchanged.
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import test_recognition_process_isolation as ISO  # noqa: E402
import test_recognition_scoring_cli as SCLI  # noqa: E402
from recognition_validation import child as CH  # noqa: E402
from recognition_validation import report as RP  # noqa: E402

world = SCLI.world
_short_schedule = ISO._short_schedule
#: The allowlist exactly as submitted at c962a3d; POSIX must not grow.
SUBMITTED_ALLOWLIST = frozenset((
    "PATH", "LANG", "TZ", "HOME", "TMPDIR", "XDG_CACHE_HOME", "PYTHONIOENCODING", "PYTHONDONTWRITEBYTECODE",
    "PYTHONHASHSEED", "EXECUTION_ENABLED", "ALLOW_PAPER_ORDERS", "AI_BRAIN_LLM", "TWO_BRAIN_MODE", "HTTPS_PROXY",
    "HTTP_PROXY", "NO_PROXY", "STAGE5_TRAJECTORY_CHILD", "AI_BRAIN_DIR", "AI_RETRIEVAL_DIR", "OCCURRENCE_LEDGER_DIR",
    "REPLAY_SESSIONS_DIR", "PERFORMANCE_TABLES_DIR", "HTF_MEMORY_DIR", "GLOBAL_MEMORY_DIR"))
#: A constructed Windows parent environment: the OS directory plus things that must never be inherited.
WINDOWS_PARENT = {"SYSTEMROOT": r"C:\Windows", "OPENAI_API_KEY": "sk-must-never-be-used",
                  "TOPSTEPX_API_KEY": "must-never-be-used", "APPDATA": r"C:\Users\operator\AppData\Roaming",
                  "PATH": r"C:\operator\private\bin;C:\Windows\System32", "USERPROFILE": r"C:\Users\operator"}
WINDOWS_GIT = r"C:\Program Files\Git\cmd\git.exe"


def _submitted_posix_environment(child_root):
    """The c962a3d builder, transcribed, for the byte-identity control."""
    env = {"PATH": ":".join([str(Path(sys.executable).parent), "/usr/local/bin", "/usr/bin", "/bin"]),
           "LANG": "C.UTF-8", "TZ": "UTC", "HOME": str(child_root / "home"), "TMPDIR": str(child_root / "tmp"),
           "XDG_CACHE_HOME": str(child_root / "cache"), "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONHASHSEED": "0", "EXECUTION_ENABLED": "false", "ALLOW_PAPER_ORDERS": "false",
           "AI_BRAIN_LLM": "false", "TWO_BRAIN_MODE": "off", "HTTPS_PROXY": "http://127.0.0.1:9",
           "HTTP_PROXY": "http://127.0.0.1:9", "NO_PROXY": "", "STAGE5_TRAJECTORY_CHILD": "1"}
    for key in CH.RUNTIME_ROOTS:
        env[key] = str(child_root.parent / "runtime" / key.lower())
    return env


def test_posix_child_environment_and_allowlist_are_unchanged(tmp_path):
    assert CH.env_allowlist("posix") == SUBMITTED_ALLOWLIST
    if os.name != "nt":
        assert CH.ENV_ALLOWLIST == SUBMITTED_ALLOWLIST
    for ecu in (False, True):
        root = tmp_path / f"posix-{ecu}" / "child"
        env = CH.child_environment(root, ecu=ecu, platform="posix", environ=WINDOWS_PARENT,
                                   which=lambda name: "/usr/bin/git")
        assert env == _submitted_posix_environment(root)
        assert not set(env) & set(CH.WINDOWS_ENV_NAMES)


def test_posix_git_outside_the_os_directories_is_reachable(tmp_path):
    env = CH.child_environment(tmp_path / "child", ecu=False, platform="posix", environ={},
                               which=lambda name: "/opt/homebrew/bin/git")
    assert env["PATH"].split(":")[1:] == ["/usr/local/bin", "/usr/bin", "/bin", "/opt/homebrew/bin"]
    assert set(env) == SUBMITTED_ALLOWLIST


def test_windows_child_environment_carries_systemroot_git_and_scratch_roots(tmp_path):
    for ecu in (False, True):
        root = tmp_path / f"nt-{ecu}" / "child"
        env = CH.child_environment(root, ecu=ecu, platform="nt", environ=WINDOWS_PARENT,
                                   which=lambda name: WINDOWS_GIT if name == "git" else None)
        assert env["SYSTEMROOT"] == r"C:\Windows"
        assert env["PATH"].split(";") == [str(Path(sys.executable).parent), r"C:\Windows\System32",
                                          r"C:\Program Files\Git\cmd"]
        assert env["TEMP"] == env["TMP"] == env["TMPDIR"] == str(root / "tmp")
        assert env["USERPROFILE"] == env["HOME"] == str(root / "home")
        assert set(env) == CH.env_allowlist("nt") == SUBMITTED_ALLOWLIST | {"SYSTEMROOT", "TEMP", "TMP", "USERPROFILE"}
        assert not [name for name in env if CH._CREDENTIAL.search(name)]
        inherited = {value for name, value in WINDOWS_PARENT.items() if name != "SYSTEMROOT"}
        assert not inherited & set(env.values()), "only SYSTEMROOT may be inherited"
        assert r"C:\operator\private\bin" not in env["PATH"]
        assert {key: env[key] for key in ("EXECUTION_ENABLED", "ALLOW_PAPER_ORDERS", "AI_BRAIN_LLM", "HTTPS_PROXY")} \
            == {"EXECUTION_ENABLED": "false", "ALLOW_PAPER_ORDERS": "false", "AI_BRAIN_LLM": "false",
                "HTTPS_PROXY": "http://127.0.0.1:9"}


def test_windows_without_systemroot_or_git_invents_nothing(tmp_path):
    env = CH.child_environment(tmp_path / "child", ecu=True, platform="nt", environ={"APPDATA": r"C:\x"},
                               which=lambda name: None)
    assert "SYSTEMROOT" not in env and env["PATH"] == str(Path(sys.executable).parent)
    assert set(env) < CH.env_allowlist("nt")


def test_run_in_child_launches_the_built_environment_in_both_lanes(world, tmp_path, monkeypatch, capsys):
    """Reachable consumer: the CLI's child launch uses this builder, and the real child completes."""
    built = []
    original = CH.child_environment

    def recording(child_root, *, ecu, **kwargs):
        env = original(child_root, ecu=ecu, **kwargs)
        built.append((ecu, dict(env)))
        return env

    monkeypatch.setattr(CH, "child_environment", recording)
    script = ISO._script(tmp_path, "portable")
    for ecu in (False, True):
        code, evidence, _ = ISO._cli_run(world, tmp_path, f"portable-{ecu}", ecu=ecu, script=script)
        assert code == 0
        status = ISO._status(evidence)
        assert status["complete"] is True and status["env_names"] == sorted(built[-1][1])
        assert built[-1][0] is ecu and set(built[-1][1]) == CH.ENV_ALLOWLIST
        assert RP.read_manifest(evidence)["process_isolation"]["kind"] == "FRESH_CHILD"


def test_windows_names_do_not_widen_the_posix_child_allowlist(world, tmp_path):
    """Activated negative control on this host: a Windows name injected into a POSIX child is still refused."""
    if os.name == "nt":
        pytest.skip("POSIX-host control; the Windows allowlist admits SYSTEMROOT by design")
    healthy = CH.run_in_child(ISO._request(world, tmp_path, "control"), out_root=tmp_path / "control")
    assert healthy["complete"] is True
    status = CH.run_in_child(ISO._request(world, tmp_path, "systemroot"), out_root=tmp_path / "systemroot",
                             extra_env={"SYSTEMROOT": r"C:\Windows"})
    assert status["complete"] is False and status["manifest_sha256"] is None
    assert status["child_exit"]["status"] == "REFUSED"
    assert status["child_exit"]["code"] == "CHILD_ENV_NOT_ALLOWLISTED"
