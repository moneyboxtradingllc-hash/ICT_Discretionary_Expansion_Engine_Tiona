"""Access to the frozen production source, verified before anything runs.

The harness does not re-implement the decision logic. It imports the frozen
modules from ``src/`` of this checkout and calls them. Before doing so it
proves the checkout's ``src/`` is byte-identical to the frozen commit by
recomputing every file's git blob hash against the pinned manifest.

Two small static helpers live in a module whose import pulls in the model
client stack. Rather than import that stack, or copy the helpers by hand, their
exact source text is lifted from the frozen file and executed unchanged.
"""
from __future__ import annotations

import ast
import hashlib
import importlib
import json
import os
import sys
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SRC = os.path.join(REPO, "src")


def _blob_sha1(path: str) -> str:
    with open(path, "rb") as fh:
        data = fh.read()
    return hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()


def verify_source() -> dict:
    manifest = json.load(open(os.path.join(HERE, "frozen_src_manifest.json"),
                              encoding="utf-8"))
    expected = manifest["files"]
    mismatched, missing = [], []
    for rel, sha in sorted(expected.items()):
        path = os.path.join(REPO, rel)
        if not os.path.isfile(path):
            missing.append(rel)
        elif _blob_sha1(path) != sha:
            mismatched.append(rel)
    extra = []
    for dirpath, dirnames, filenames in os.walk(SRC):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for f in sorted(filenames):
            rel = os.path.relpath(os.path.join(dirpath, f), REPO).replace(os.sep, "/")
            if rel not in expected and not f.endswith(".pyc"):
                extra.append(rel)
    return {"frozen_commit": manifest["frozen_commit"],
            "frozen_tree": manifest["frozen_tree"],
            "files_in_manifest": len(expected), "mismatched": mismatched,
            "missing": missing, "untracked_extra": extra,
            "ok": not (mismatched or missing or extra)}


def _lift(path: str, class_name: str, names: tuple, constants: tuple) -> dict:
    """Execute named static methods of one class exactly as written."""
    source = open(path, encoding="utf-8").read()
    tree = ast.parse(source)
    ns = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in constants:
            ns[node.targets[0].id] = ast.literal_eval(node.value)
    found = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name in names:
                    lines = source.splitlines()[item.lineno - 1:item.end_lineno]
                    exec(compile(textwrap.dedent("\n".join(lines)), path, "exec"), ns)
                    found[item.name] = ns[item.name]
    absent = [n for n in names if n not in found] + [c for c in constants if c not in ns]
    if absent:
        raise RuntimeError(f"could not lift {absent} from {path}")
    return found


def _lazy_imports(path: str) -> list:
    """Every module imported inside a function body of ``path``."""
    tree = ast.parse(open(path, encoding="utf-8").read())
    mods = set()
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in ast.walk(fn):
                if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    mods.add(node.module)
                elif isinstance(node, ast.Import):
                    mods.update(a.name for a in node.names)
    return sorted(mods)


class Frozen:
    """The frozen callables the replay needs, and proof they loaded."""

    def __init__(self) -> None:
        if SRC not in sys.path:
            sys.path.insert(0, SRC)
        sys.dont_write_bytecode = True
        producer_mod = importlib.import_module("broker.luna_candidate_producer")
        self.CandidateProducer = producer_mod.CandidateProducer
        self.NoCandidate = producer_mod.NoCandidate
        self.TopstepXContract = importlib.import_module(
            "broker.topstepx_client").TopstepXContract
        cdr = importlib.import_module("broker.candidate_decision_record")
        self.build_record = cdr.build_record
        self.terminal_disposition = cdr.terminal_disposition
        self.CONDITIONAL_PLAN_PUBLISHED = cdr.CONDITIONAL_PLAN_PUBLISHED
        self.session_authorization = importlib.import_module(
            "broker.topstepx_session_authorization")
        self.mission_state = importlib.import_module("broker.topstepx_mission_state")
        lifted = _lift(os.path.join(SRC, "live_scan", "production_scan_cycle.py"),
                       "ProductionScanCycle",
                       ("to_brain_result", "is_sovereign", "engine_inventory"),
                       ("SOURCE_LLM",))
        self.to_brain_result = lifted["to_brain_result"]
        self.is_sovereign = lifted["is_sovereign"]
        self.engine_inventory = lifted["engine_inventory"]
        # A lazy import that fails inside the producer is swallowed there and
        # turns into a refusal. Import each one now so that cannot happen.
        self.preflight = {}
        for mod in _lazy_imports(os.path.join(SRC, "broker", "luna_candidate_producer.py")):
            importlib.import_module(mod)
            self.preflight[mod] = "imported"
