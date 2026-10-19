"""Verify the Stage 5 engineering ledger against git objects (offline, read-only).

docs/recognition_validation/ENGINEERING_LEDGER.md is the substitute for a
commit SHA that cannot be precomputed: each mission writes an entry binding
its exact parent commit BEFORE editing. This tool recomputes every bound
digest from git objects instead of trusting the recorded text, so a wrong
parent, an altered protected source, a copied digest or a ledger left stale
by out-of-scope commits fails.

No network, provider, model, account or credential access. Production code is
only imported (optionally) inside a throwaway subprocess over an extracted
parent tree, to recompute the canonical Brain/retrieval fingerprints.

Exit 0 when every check passes, 1 on any verification failure, 2 on usage or
repository errors.
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

LEDGER_PATH = "docs/recognition_validation/ENGINEERING_LEDGER.md"
PINS_PATH = "docs/recognition_validation/baseline/SOURCE_PINS.json"
ENTRY_SCHEMA = "engineering_ledger_entry/v1"
PRODUCTION_MODEL = "src/ai_brain/production_model.py"
_ENTRY_RE = re.compile(r"```json ledger-entry\r?\n(.*?)\r?\n```", re.S)
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_REQUIRED = (
    "schema", "mission_id", "parent_sha", "parent_tree", "parent_tracked_status",
    "brain_fingerprint", "retrieval_fingerprint", "closure_count", "closure_digest",
    "protected_count", "protected_digest", "policy_refs", "scoped_files",
    "proof_ids", "predecessor_receipt_digest", "receipt_digest",
)


class LedgerError(Exception):
    """A verification failure with a stable code."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def receipt_digest(entry: dict) -> str:
    return sha256(canonical({k: v for k, v in entry.items() if k != "receipt_digest"}))


class Repo:
    def __init__(self, root: Path):
        self.root = root

    def git(self, *args: str, check: bool = True) -> str:
        proc = subprocess.run(["git", *args], cwd=self.root, capture_output=True)
        if check and proc.returncode != 0:
            raise LedgerError("GIT_ERROR", f"git {' '.join(args)}: {proc.stderr.decode().strip()}")
        return proc.stdout.decode()

    def show(self, rev: str, path: str) -> bytes | None:
        proc = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=self.root, capture_output=True)
        return proc.stdout if proc.returncode == 0 else None

    def is_ancestor(self, older: str, newer: str) -> bool:
        return subprocess.run(["git", "merge-base", "--is-ancestor", older, newer],
                              cwd=self.root, capture_output=True).returncode == 0

    def commit_exists(self, rev: str) -> bool:
        return subprocess.run(["git", "cat-file", "-e", f"{rev}^{{commit}}"],
                              cwd=self.root, capture_output=True).returncode == 0


def parse_entries(text: str) -> list[dict]:
    entries = []
    for block in _ENTRY_RE.findall(text):
        def pairs(rows):
            out = {}
            for key, value in rows:
                if key in out:
                    raise LedgerError("DUPLICATE_KEY", key)
                out[key] = value
            return out
        try:
            entries.append(json.loads(block, object_pairs_hook=pairs))
        except json.JSONDecodeError as exc:
            raise LedgerError("ENTRY_NOT_JSON", str(exc)) from exc
    return entries


def contract_sources(source: bytes) -> list[tuple[str, str]]:
    """(label, repo-relative path) in fingerprint order, read from the AST."""
    tree = ast.parse(source)
    found: dict[str, list[tuple[str, str]]] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ("_CONTRACT_SOURCES", "_CONTRACT_SOURCES_REPO"):
                found[name] = [tuple(ast.literal_eval(elt)) for elt in node.value.elts]
    if set(found) != {"_CONTRACT_SOURCES", "_CONTRACT_SOURCES_REPO"}:
        raise LedgerError("CLOSURE_UNPARSEABLE", "contract source tuples not found")
    return ([(label, "src/" + rel) for label, rel in found["_CONTRACT_SOURCES"]]
            + list(found["_CONTRACT_SOURCES_REPO"]))


def lf_hash(data: bytes | None) -> str | None:
    return None if data is None else sha256(data.replace(b"\r\n", b"\n"))


def closure_at(repo: Repo, rev: str) -> list[list]:
    source = repo.show(rev, PRODUCTION_MODEL)
    if source is None:
        raise LedgerError("CLOSURE_UNPARSEABLE", f"{PRODUCTION_MODEL} missing at {rev}")
    return [[label, path, lf_hash(repo.show(rev, path))] for label, path in contract_sources(source)]


def protected_at(repo: Repo, rev: str, paths) -> dict[str, str | None]:
    return {path: lf_hash(repo.show(rev, path)) for path in sorted(paths)}


def fingerprints_at(repo: Repo, rev: str) -> tuple[str, str]:
    """Canonical fingerprints over an extracted copy of `rev` in a subprocess."""
    with tempfile.TemporaryDirectory(prefix="ledger-fp-") as temp:
        archive = Path(temp) / "tree.tar"
        with open(archive, "wb") as fh:
            subprocess.run(["git", "archive", "--format=tar", rev, "src", "tools/topstepx_production_session.py"],
                           cwd=repo.root, stdout=fh, check=True)
        out = Path(temp) / "tree"
        with tarfile.open(archive) as tar:
            tar.extractall(out, filter="data")
        script = (
            "import sys,json;sys.dont_write_bytecode=True;sys.path.insert(0,sys.argv[1]);"
            "from ai_brain.production_model import brain_contract_fingerprint as b;"
            "from ai_retrieval.retrieval_contract import retrieval_contract_fingerprint as r;"
            "print(json.dumps([b(),r()]))"
        )
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8",
               "HOME": temp, "AI_BRAIN_LLM": "false", "TWO_BRAIN_MODE": "off",
               "EXECUTION_ENABLED": "false", "ALLOW_PAPER_ORDERS": "false"}
        proc = subprocess.run([sys.executable, "-I", "-c", script, str(out / "src")],
                              cwd=temp, env=env, capture_output=True)
        if proc.returncode != 0:
            raise LedgerError("FINGERPRINT_ERROR", proc.stderr.decode().strip()[-400:])
        brain, retr = json.loads(proc.stdout.decode().strip().splitlines()[-1])
        return brain, retr


def changed_files(repo: Repo, older: str, newer: str | None) -> set[str]:
    """Paths changed from `older` to `newer`, or to the tracked working tree."""
    args = ["diff", "--name-only", "-z", older] + ([newer] if newer else [])
    return {name for name in repo.git(*args).split("\0") if name}


def in_scope(path: str, patterns) -> bool:
    return path == LEDGER_PATH or any(fnmatch.fnmatchcase(path, pat) for pat in patterns)


def verify(root: Path, *, check_fingerprints: bool = True, require_clean: bool = False) -> dict:
    repo = Repo(root)
    if not (root / LEDGER_PATH).is_file():
        raise LedgerError("LEDGER_MISSING", LEDGER_PATH)
    pins = json.loads((root / PINS_PATH).read_text(encoding="utf-8"))
    baseline = pins["baseline_sha"]
    protected = pins["protected_sources"]
    entries = parse_entries((root / LEDGER_PATH).read_text(encoding="utf-8"))
    if not entries:
        raise LedgerError("LEDGER_EMPTY")
    head = repo.git("rev-parse", "HEAD").strip()
    status = repo.git("status", "--short", "--untracked-files=no").strip()
    if require_clean and status:
        raise LedgerError("TRACKED_WORKTREE_DIRTY", status)

    seen = set()
    for index, entry in enumerate(entries):
        mission = entry.get("mission_id", f"#{index}")
        missing = [k for k in _REQUIRED if k not in entry]
        if missing:
            raise LedgerError("ENTRY_FIELDS_MISSING", f"{mission}: {missing}")
        if entry["schema"] != ENTRY_SCHEMA:
            raise LedgerError("ENTRY_SCHEMA", mission)
        if mission in seen:
            raise LedgerError("DUPLICATE_MISSION", mission)
        seen.add(mission)
        if entry["receipt_digest"] != receipt_digest(entry):
            raise LedgerError("RECEIPT_DIGEST_MISMATCH", mission)
        expected_pred = None if index == 0 else entries[index - 1]["receipt_digest"]
        if entry["predecessor_receipt_digest"] != expected_pred:
            raise LedgerError("PREDECESSOR_MISMATCH", mission)
        parent = entry["parent_sha"]
        if not isinstance(parent, str) or not _HEX40.match(parent):
            raise LedgerError("PARENT_NOT_FULL_SHA", f"{mission}: {parent!r}")
        if not repo.commit_exists(parent):
            raise LedgerError("PARENT_UNKNOWN", f"{mission}: {parent}")
        if index == 0 and parent != baseline:
            raise LedgerError("FIRST_PARENT_NOT_BASELINE", f"{parent} != {baseline}")
        if not repo.is_ancestor(parent, head):
            raise LedgerError("PARENT_NOT_IN_LINEAGE", f"{mission}: {parent}")
        if index > 0:
            prev = entries[index - 1]["parent_sha"]
            if parent == prev or not repo.is_ancestor(prev, parent):
                raise LedgerError("PARENT_ORDER", f"{mission}: {prev} -> {parent}")
            committed = repo.show(parent, LEDGER_PATH)
            committed_entries = parse_entries(committed.decode("utf-8")) if committed else []
            committed_ids = [e.get("receipt_digest") for e in committed_entries]
            if committed_ids != [e["receipt_digest"] for e in entries[:index]]:
                raise LedgerError("PREDECESSOR_NOT_COMMITTED_AT_PARENT", mission)
        tree = repo.git("rev-parse", f"{parent}^{{tree}}").strip()
        if entry["parent_tree"] != tree:
            raise LedgerError("PARENT_TREE_MISMATCH", f"{mission}: {entry['parent_tree']} != {tree}")
        if entry["parent_tracked_status"] != "":
            raise LedgerError("PARENT_NOT_CLEAN", mission)
        actual_protected = protected_at(repo, parent, protected)
        if actual_protected != dict(sorted(protected.items())):
            altered = sorted(p for p, h in actual_protected.items() if protected[p] != h)
            raise LedgerError("PROTECTED_SOURCE_ALTERED", f"{mission}: {altered}")
        if entry["protected_count"] != len(protected) or entry["protected_digest"] != sha256(canonical(actual_protected)):
            raise LedgerError("PROTECTED_DIGEST_MISMATCH", mission)
        closure = closure_at(repo, parent)
        if entry["closure_count"] != len(closure) or entry["closure_digest"] != sha256(canonical(closure)):
            raise LedgerError("CLOSURE_DIGEST_MISMATCH", mission)
        if check_fingerprints:
            brain, retr = fingerprints_at(repo, parent)
            if (entry["brain_fingerprint"], entry["retrieval_fingerprint"]) != (brain, retr):
                raise LedgerError("FINGERPRINT_MISMATCH", f"{mission}: {brain} {retr}")

    # Only once every parent binding holds: each change between a parent and
    # the next one (or HEAD plus the tracked working tree for the latest
    # entry) must be inside the scope that entry declared before editing;
    # otherwise the ledger is stale.
    for index, entry in enumerate(entries):
        nxt = entries[index + 1]["parent_sha"] if index + 1 < len(entries) else None
        delta = changed_files(repo, entry["parent_sha"], nxt)
        stray = sorted(p for p in delta if not in_scope(p, entry["scoped_files"]))
        if stray:
            raise LedgerError("STALE_LEDGER_OUT_OF_SCOPE_CHANGE", f"{entry['mission_id']}: {stray}")

    last = entries[-1]
    head_protected = {p: lf_hash((root / p).read_bytes()) if (root / p).is_file() else None
                      for p in sorted(protected)}
    if head_protected != dict(sorted(protected.items())):
        altered = sorted(p for p, h in head_protected.items() if protected[p] != h)
        raise LedgerError("PROTECTED_SOURCE_ALTERED", f"worktree: {altered}")
    source = (root / PRODUCTION_MODEL).read_bytes()
    head_closure = [[label, path, lf_hash((root / path).read_bytes()) if (root / path).is_file() else None]
                    for label, path in contract_sources(source)]
    closure_changed = sha256(canonical(head_closure)) != last["closure_digest"]
    if closure_changed and not last.get("closure_change_rationale"):
        raise LedgerError("UNDECLARED_CLOSURE_CHANGE", last["mission_id"])
    return {
        "status": "LEDGER_VERIFIED",
        "head": head,
        "tracked_status_clean": not status,
        "entries": [e["mission_id"] for e in entries],
        "latest_parent": last["parent_sha"],
        "latest_receipt_digest": last["receipt_digest"],
        "protected_verified": len(protected),
        "closure_changed_since_latest_parent": closure_changed,
        "fingerprints_checked": check_fingerprints,
        "network_requests": 0,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=".")
    parser.add_argument("--skip-fingerprints", action="store_true")
    parser.add_argument("--require-clean", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = verify(Path(args.repo).resolve(), check_fingerprints=not args.skip_fingerprints,
                        require_clean=args.require_clean)
    except LedgerError as exc:
        print(json.dumps({"status": "LEDGER_INVALID", "code": exc.code, "detail": str(exc)}))
        return 1 if exc.code != "GIT_ERROR" else 2
    except (OSError, KeyError, ValueError) as exc:
        print(json.dumps({"status": "LEDGER_INVALID", "code": "INPUT_ERROR", "detail": repr(exc)}))
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
