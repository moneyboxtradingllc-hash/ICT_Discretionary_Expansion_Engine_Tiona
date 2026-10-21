"""Stage 5 M00: the engineering ledger is verified from git objects, not prose.

Each negative builds a small synthetic repository and proves the verifier
names the exact failure (wrong source, altered protected source, copied
digest, stale ledger) rather than an incidental error. The last case verifies
this repository's own ledger, including canonical fingerprints at each parent.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import verify_engineering_ledger as L  # noqa: E402

GIT_ENV = {
    "GIT_AUTHOR_NAME": "ledger-test", "GIT_AUTHOR_EMAIL": "ledger-test@invalid",
    "GIT_COMMITTER_NAME": "ledger-test", "GIT_COMMITTER_EMAIL": "ledger-test@invalid",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
}

PRODUCTION_MODEL = '''_CONTRACT_SOURCES = (
    ("prompt", "ai_brain/brain_prompt.py"),
)
_CONTRACT_SOURCES_REPO = (
    ("production_entrypoint", "tools/entry.py"),
)
'''


def git(root: Path, *args: str) -> str:
    env = {**os.environ, **GIT_ENV}
    return subprocess.run(["git", *args], cwd=root, env=env, check=True,
                          capture_output=True).stdout.decode().strip()


def write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def commit(root: Path, message: str) -> str:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD")


def make_entry(root: Path, mission: str, parent: str, scope, **extra) -> dict:
    repo = L.Repo(root)
    pins = json.loads((root / L.PINS_PATH).read_text())
    protected = L.protected_at(repo, parent, pins["protected_sources"])
    closure = L.closure_at(repo, parent)
    ledger = root / L.LEDGER_PATH
    previous = L.parse_entries(ledger.read_text()) if ledger.exists() else []
    entry = {
        "schema": L.ENTRY_SCHEMA, "mission_id": mission, "parent_sha": parent,
        "parent_tree": repo.git("rev-parse", parent + "^{tree}").strip(),
        "parent_tracked_status": "",
        "brain_fingerprint": "brain:synthetic", "retrieval_fingerprint": "retr:synthetic",
        "closure_count": len(closure), "closure_digest": L.sha256(L.canonical(closure)),
        "protected_count": len(protected), "protected_digest": L.sha256(L.canonical(protected)),
        "policy_refs": ["test"], "scoped_files": list(scope), "proof_ids": [mission + "-test"],
        "predecessor_receipt_digest": previous[-1]["receipt_digest"] if previous else None,
    }
    entry.update(extra)
    entry["receipt_digest"] = L.receipt_digest(entry)
    return entry


def append_entry(root: Path, entry: dict, *, reseal: bool = True) -> None:
    if reseal:
        entry["receipt_digest"] = L.receipt_digest(entry)
    ledger = root / L.LEDGER_PATH
    text = ledger.read_text() if ledger.exists() else "# ledger\n"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(text + "\n```json ledger-entry\n" + json.dumps(entry, indent=2) + "\n```\n")


def rewrite_last(root: Path, entry: dict, *, reseal: bool = True) -> None:
    ledger = root / L.LEDGER_PATH
    entries = L.parse_entries(ledger.read_text())[:-1]
    ledger.write_text("# ledger\n")
    for kept in entries:
        append_entry(root, kept, reseal=False)
    append_entry(root, entry, reseal=reseal)


def failure(root: Path) -> str:
    with pytest.raises(L.LedgerError) as exc:
        L.verify(root, check_fingerprints=False)
    return exc.value.code


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "symbolic-ref", "HEAD", "refs/heads/review")   # `init -b` needs git >= 2.28
    write(root, "src/ai_brain/production_model.py", PRODUCTION_MODEL)
    write(root, "src/ai_brain/brain_prompt.py", "PROMPT = 'v1'\n")
    write(root, "tools/entry.py", "ENTRY = 1\n")
    write(root, "src/broker/guard.py", "LIMIT = 1\n")
    write(root, "src/other.py", "X = 1\n")
    baseline = commit(root, "baseline")
    pins = {"schema": "source_pins/v1", "baseline_sha": baseline,
            "protected_sources": {"src/broker/guard.py": L.lf_hash(b"LIMIT = 1\n")}}
    write(root, L.PINS_PATH, json.dumps(pins))
    append_entry(root, make_entry(root, "M00", baseline,
                                  ["docs/recognition_validation/*", "src/work.py"]))
    commit(root, "M00 ledger")
    return root, baseline


def test_healthy_two_mission_chain_verifies(repo):
    root, baseline = repo
    write(root, "src/work.py", "W = 1\n")
    m00_child = commit(root, "M00 work")
    append_entry(root, make_entry(root, "M01", m00_child, ["src/next.py"]))
    commit(root, "M01 ledger")
    write(root, "src/next.py", "N = 1\n")
    commit(root, "M01 work")
    result = L.verify(root, check_fingerprints=False)
    assert result["status"] == "LEDGER_VERIFIED"
    assert result["entries"] == ["M00", "M01"]
    assert result["latest_parent"] == m00_child


def test_wrong_source_parent_outside_lineage_is_rejected(repo):
    root, baseline = repo
    git(root, "checkout", "-q", "-b", "side", baseline)
    write(root, "src/other.py", "X = 2\n")
    foreign = commit(root, "foreign")
    git(root, "checkout", "-q", "review")
    write(root, "src/work.py", "W = 1\n")
    child = commit(root, "M00 work")
    healthy = make_entry(root, "M01", child, ["src/next.py"])
    forged = make_entry(root, "M01", foreign, ["src/next.py"])
    append_entry(root, forged)
    assert failure(root) == "PARENT_NOT_IN_LINEAGE"
    rewrite_last(root, {**healthy, "parent_tree": forged["parent_tree"]})
    assert failure(root) == "PARENT_TREE_MISMATCH"
    rewrite_last(root, healthy)
    assert L.verify(root, check_fingerprints=False)["status"] == "LEDGER_VERIFIED"


def test_first_entry_must_bind_the_frozen_baseline(repo):
    root, baseline = repo
    ledger = root / L.LEDGER_PATH
    first = L.parse_entries(ledger.read_text())[0]
    later = git(root, "rev-parse", "HEAD")
    ledger.write_text("# ledger\n")
    append_entry(root, make_entry(root, "M00", later, first["scoped_files"]))
    assert failure(root) == "FIRST_PARENT_NOT_BASELINE"


def test_symbolic_parent_is_rejected(repo):
    root, _ = repo
    ledger = root / L.LEDGER_PATH
    first = L.parse_entries(ledger.read_text())[0]
    rewrite_last(root, {**first, "parent_sha": "HEAD"})
    assert failure(root) == "PARENT_NOT_FULL_SHA"


def test_altered_protected_source_is_rejected_at_worktree_and_parent(repo):
    root, _ = repo
    ledger = root / L.LEDGER_PATH
    first = L.parse_entries(ledger.read_text())[0]
    rewrite_last(root, {**first, "scoped_files": first["scoped_files"] + ["src/broker/*"]})
    commit(root, "widen scope")
    write(root, "src/broker/guard.py", "LIMIT = 2\n")
    assert failure(root) == "PROTECTED_SOURCE_ALTERED"
    child = commit(root, "alter protected")
    write(root, "src/broker/guard.py", "LIMIT = 1\n")  # worktree restored; parent still altered
    append_entry(root, make_entry(root, "M01", child, ["src/broker/*"]))
    with pytest.raises(L.LedgerError) as exc:
        L.verify(root, check_fingerprints=False)
    assert exc.value.code == "PROTECTED_SOURCE_ALTERED"
    assert "M01" in str(exc.value) and "src/broker/guard.py" in str(exc.value)


def test_copied_or_tampered_digests_are_rejected(repo):
    root, _ = repo
    ledger = root / L.LEDGER_PATH
    first = L.parse_entries(ledger.read_text())[0]
    # A digest copied from another field, resealed so the receipt itself is valid.
    rewrite_last(root, {**first, "closure_digest": first["protected_digest"]})
    assert failure(root) == "CLOSURE_DIGEST_MISMATCH"
    rewrite_last(root, {**first, "protected_digest": first["closure_digest"]})
    assert failure(root) == "PROTECTED_DIGEST_MISMATCH"
    # An edited field without resealing.
    rewrite_last(root, {**first, "proof_ids": ["forged"]}, reseal=False)
    assert failure(root) == "RECEIPT_DIGEST_MISMATCH"
    rewrite_last(root, first, reseal=False)
    write(root, "src/work.py", "W = 1\n")
    child = commit(root, "M00 work")
    append_entry(root, make_entry(root, "M01", child, ["src/next.py"],
                                  predecessor_receipt_digest=first["closure_digest"]))
    assert failure(root) == "PREDECESSOR_MISMATCH"


def test_stale_ledger_out_of_scope_commit_is_rejected(repo):
    root, _ = repo
    write(root, "src/other.py", "X = 99\n")
    commit(root, "unrecorded change")
    assert failure(root) == "STALE_LEDGER_OUT_OF_SCOPE_CHANGE"


def test_stale_ledger_uncommitted_tracked_change_is_rejected(repo):
    root, _ = repo
    write(root, "src/other.py", "X = 99\n")
    assert failure(root) == "STALE_LEDGER_OUT_OF_SCOPE_CHANGE"


def test_successor_entry_requires_predecessor_committed_at_its_parent(repo):
    root, baseline = repo
    # M01 claims the baseline-era M00 work commit as parent, but its own
    # predecessor entry was rewritten afterwards (never committed there).
    write(root, "src/work.py", "W = 1\n")
    child = commit(root, "M00 work")
    ledger = root / L.LEDGER_PATH
    first = L.parse_entries(ledger.read_text())[0]
    rewrite_last(root, {**first, "proof_ids": ["rewritten-later"]})
    append_entry(root, make_entry(root, "M01", child, ["src/next.py"]))
    assert failure(root) == "PREDECESSOR_NOT_COMMITTED_AT_PARENT"


def test_closure_change_requires_declared_rationale(repo):
    root, _ = repo
    ledger = root / L.LEDGER_PATH
    first = L.parse_entries(ledger.read_text())[0]
    rewrite_last(root, {**first, "scoped_files": first["scoped_files"] + ["src/ai_brain/brain_prompt.py"]})
    commit(root, "widen scope")
    write(root, "src/ai_brain/brain_prompt.py", "PROMPT = 'v2'\n")
    assert failure(root) == "UNDECLARED_CLOSURE_CHANGE"
    first = L.parse_entries(ledger.read_text())[0]
    rewrite_last(root, {**first, "closure_change_rationale": "test: prompt repair evidenced"})
    assert L.verify(root, check_fingerprints=False)["closure_changed_since_latest_parent"] is True


def _repository_ledger_available() -> bool:
    if not (ROOT / ".git").exists() or not (ROOT / L.LEDGER_PATH).is_file():
        return False
    pins = json.loads((ROOT / L.PINS_PATH).read_text())
    return L.Repo(ROOT).commit_exists(pins["baseline_sha"])


@pytest.mark.skipif(not _repository_ledger_available(),
                    reason="needs a git checkout containing the frozen Stage 5 baseline commit")
def test_this_repository_ledger_verifies_with_canonical_fingerprints():
    result = L.verify(ROOT, check_fingerprints=True)
    assert result["status"] == "LEDGER_VERIFIED"
    assert result["entries"][0] == "M00"
    assert result["protected_verified"] == 32
