"""Source guards must retain their scope and filters without a shell or PATH."""
import subprocess

import pytest

from _repo_source_scan import matching_python_lines


@pytest.fixture
def tree(tmp_path):
    for directory in ("src", "tools", "tests"):
        (tmp_path / directory).mkdir()
    return tmp_path


def test_scan_is_sorted_recursive_case_sensitive_and_path_independent(tree, monkeypatch):
    (tree / "src" / "nested").mkdir()
    for relative in ("src/z.py", "src/a.py", "src/nested/b.py", "tools/c.py",
                     "tests/outside.py", "src/ignored.PY", "tools/ignored.txt"):
        (tree / relative).write_bytes("# café\r\nAI_RETRIEVAL_ENABLED\r\n".encode("utf-8"))
    monkeypatch.setenv("PATH", "")

    def refuse_subprocess(*args, **kwargs):
        raise AssertionError("the source guard must not invoke an external program")

    monkeypatch.setattr(subprocess, "run", refuse_subprocess)
    expected = [f"{path}:2:AI_RETRIEVAL_ENABLED" for path in
                ("src/a.py", "src/z.py", "src/nested/b.py", "tools/c.py")]
    assert matching_python_lines("AI_RETRIEVAL_ENABLED", root=tree) == expected
    assert matching_python_lines("AI_RETRIEVAL_ENABLED", root=tree) == expected


def test_quarantine_filter_still_distinguishes_naming_from_loading(tree):
    (tree / "src" / "guard.py").write_text(
        'open("replay_sessions/_quarantine/x")\n'
        'json.load(replay_sessions_retired_instrument)\n'
        'print("replay_sessions/_quarantine")\n'
        'open("replay_sessions/allowed")\n'
        'open("_quarantine/unrelated")\n', encoding="utf-8")
    offenders = [line for line in matching_python_lines("replay_sessions", root=tree)
                 if "_quarantine" in line or "retired_instrument" in line]
    forbidden = [line for line in offenders if "open(" in line or "json.load" in line]
    assert [line.split(":", 2)[1] for line in forbidden] == ["1", "2"]


def test_retrieval_parser_filter_preserves_full_line_exclusion(tree):
    (tree / "src" / "retrieval.py").write_text(
        'getenv("AI_RETRIEVAL_ENABLED")\n', encoding="utf-8")
    (tree / "tools" / "other.py").write_text(
        'getenv("AI_RETRIEVAL_ENABLED")\n'
        'print("AI_RETRIEVAL_ENABLED")\n'
        'getenv("AI_RETRIEVAL_ENABLED") # retrieval.py reference\n'
        'getenv("SOMETHING_ELSE")\n', encoding="utf-8")
    parsers = [line for line in matching_python_lines("AI_RETRIEVAL_ENABLED", root=tree)
               if "getenv" in line and "retrieval.py" not in line]
    assert parsers == ['tools/other.py:1:getenv("AI_RETRIEVAL_ENABLED")']


def test_missing_source_root_cannot_silently_pass(tmp_path):
    with pytest.raises(FileNotFoundError):
        matching_python_lines("replay_sessions", root=tmp_path)
