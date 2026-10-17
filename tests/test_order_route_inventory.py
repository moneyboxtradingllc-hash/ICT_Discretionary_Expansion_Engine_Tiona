"""S4-10: every source route that can send a NEW order is indexed and bounded.

`gated_submit` itself checks ledger, freshness, final quote and token binding
but not campaign Lifecycle; that authority is owned by
`CandidateProducer.produce(require_campaign_lifecycle=True)`. So the safety
claim is about routes, not one method docstring:

* the exact set of entry-capable venue-write call sites in src/ and tools/ is
  pinned here (a new route fails until it is reviewed and indexed);
* every candidate-producing caller on a gated_submit route passes the literal
  `require_campaign_lifecycle=True`;
* the legacy smoke main reaches `attempt_trade` only with the candidate its
  own Lifecycle-gated `one_scan` returned (behavior proven separately by
  test_legacy_smoke_route_fail_closed.py);
* the production entrypoint's static import closure contains no manual smoke
  tool and no caller of a legacy paper-order writer.

Exit-only writes (cancel/modify/close for protection and flatten) are
intentionally outside this index. Each check is a pure function over source
text so the activated controls below can feed it mutated sources.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENTRY_WRITE_METHODS = {"place_order", "submit_order", "gated_submit"}
PAPER_WRITERS = {"submit_paper_order", "submit_paper_exit_order",
                 "submit_protective_stop_order"}
PRODUCTION_ENTRYPOINT = "tools/topstepx_production_session.py"

# (file, enclosing qualified function, method) -> route classification.
ENTRY_ROUTE_INDEX = {
    ("src/broker/topstepx_production_loop.py", "ProductionLoop._execute", "submit"):
        "PRODUCTION: loop -> ProductionSession.submit",
    ("src/broker/topstepx_production_session.py", "ProductionSession.submit", "gated_submit"):
        "PRODUCTION: session -> runner.gated_submit with live quote provider",
    ("src/broker/topstepx_execution_runner.py", "ExecutionRunner.gated_submit", "submit"):
        "RUNNER: all gates passed, token minted -> submit",
    ("src/broker/topstepx_execution_runner.py", "ExecutionRunner.submit", "place_order"):
        "RUNNER: token burn + flight record -> venue",
    ("tools/topstepx_smoke_wait.py", "attempt_trade", "gated_submit"):
        "LEGACY SMOKE DIAGNOSTIC: candidate only from Lifecycle-gated one_scan",
    ("tools/topstepx_release_smoke.py", "phase_b", "submit"):
        "MANUAL RELEASE CANARY: explicit operator flag, smoke geometry, not a thesis",
    ("tools/topstepx_execution_smoke.py", "main", "place_order"):
        "MANUAL LIFECYCLE SMOKE: no candidate, own payload, not production",
    ("src/paper_execution/paper_broker.py", "submit_paper_order", "submit_order"):
        "LEGACY PAPER (Alpaca): env-flag gated, outside production closure",
    ("src/paper_execution/paper_broker.py", "submit_paper_exit_order", "submit_order"):
        "LEGACY PAPER (Alpaca): exit order, outside production closure",
    ("src/paper_execution/paper_broker.py", "submit_protective_stop_order", "submit_order"):
        "LEGACY PAPER (Alpaca): protective stop, outside production closure",
}
GATED_ROUTE_PRODUCERS = ("src/broker/topstepx_production_loop.py", "tools/topstepx_smoke_wait.py")
FORBIDDEN_IN_PRODUCTION_CLOSURE = ("tools/topstepx_execution_smoke.py",
                                   "tools/topstepx_release_smoke.py",
                                   "tools/topstepx_smoke_wait.py")


def _sources() -> dict[str, str]:
    files = sorted(list((ROOT / "src").rglob("*.py")) + list((ROOT / "tools").rglob("*.py")))
    return {p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8-sig") for p in files}


def _calls(tree):
    """(qualified enclosing function, ast.Call) for every call in a module."""
    def walk(node, scope):
        for child in ast.iter_child_nodes(node):
            inner = scope
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                inner = f"{scope}.{child.name}" if scope else child.name
            if isinstance(child, ast.Call):
                yield scope, child
            yield from walk(child, inner)
    yield from walk(tree, "")


def entry_write_sites(sources: dict[str, str]) -> set[tuple[str, str, str]]:
    sites = set()
    for path, text in sources.items():
        for scope, call in _calls(ast.parse(text)):
            if not isinstance(call.func, ast.Attribute):
                continue
            method = call.func.attr
            keywords = {k.arg for k in call.keywords}
            if method in ENTRY_WRITE_METHODS or (
                    method == "submit" and keywords & {"account_id", "candidate"}):
                sites.add((path, scope, method))
    return sites


def produce_calls_without_lifecycle(sources: dict[str, str], paths) -> list[str]:
    bad = []
    for path in paths:
        found = 0
        for scope, call in _calls(ast.parse(sources[path])):
            if isinstance(call.func, ast.Attribute) and call.func.attr == "produce":
                found += 1
                flag = next((k.value for k in call.keywords if k.arg == "require_campaign_lifecycle"), None)
                if not (isinstance(flag, ast.Constant) and flag.value is True):
                    bad.append(f"{path}:{call.lineno} {scope}")
        if not found:
            bad.append(f"{path}: no produce call found")
    return bad


def smoke_attempt_candidate_sources(sources: dict[str, str]) -> list[str]:
    """Source expressions of the candidate argument at every attempt_trade call."""
    out = []
    for scope, call in _calls(ast.parse(sources["tools/topstepx_smoke_wait.py"])):
        if isinstance(call.func, ast.Name) and call.func.id == "attempt_trade":
            out.append((scope, ast.unparse(call.args[4]) if len(call.args) > 4 else None))
    return out


def smoke_candidate_origin(sources: dict[str, str]) -> set[str]:
    """Calls assigned to `verdict` inside the smoke main loop."""
    origins = set()
    for node in ast.walk(ast.parse(sources["tools/topstepx_smoke_wait.py"])):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "verdict" for t in node.targets):
            if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
                origins.add(node.value.func.id)
    return origins


def _module_file(sources, name: str) -> str | None:
    for base in ("src/", ""):
        stem = base + name.replace(".", "/")
        for candidate in (stem + ".py", stem + "/__init__.py"):
            if candidate in sources:
                return candidate
    return None


def import_closure(sources: dict[str, str], start: str) -> set[str]:
    """Static transitive repository import closure (module and function level)."""
    seen, stack = set(), [start]
    while stack:
        path = stack.pop()
        if path in seen:
            continue
        seen.add(path)
        package = Path(path.removeprefix("src/")).with_suffix("").parts
        if package[-1] == "__init__":
            package = package[:-1]
            depth_base = package
        else:
            depth_base = package[:-1]
        for node in ast.walk(ast.parse(sources[path])):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = list(depth_base[:len(depth_base) - node.level + 1])
                    module = ".".join(base + ([node.module] if node.module else []))
                else:
                    module = node.module or ""
                names = [module] + [f"{module}.{a.name}" for a in node.names]
            for name in names:
                parts = name.split(".")
                for i in range(1, len(parts) + 1):
                    found = _module_file(sources, ".".join(parts[:i]))
                    if found and found not in seen:
                        stack.append(found)
    return seen


def paper_writer_callers(sources: dict[str, str], files) -> list[str]:
    hits = []
    for path in files:
        for scope, call in _calls(ast.parse(sources[path])):
            name = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", None)
            if name in PAPER_WRITERS and path != "src/paper_execution/paper_broker.py":
                hits.append(f"{path}:{call.lineno} {scope} -> {name}")
    return hits


@pytest.fixture(scope="module")
def sources():
    return _sources()


def test_entry_capable_write_routes_are_exactly_the_indexed_set(sources):
    assert entry_write_sites(sources) == set(ENTRY_ROUTE_INDEX)


def test_gated_routes_produce_candidates_only_under_campaign_lifecycle(sources):
    assert produce_calls_without_lifecycle(sources, GATED_ROUTE_PRODUCERS) == []


def test_legacy_smoke_main_submits_only_its_one_scan_candidate(sources):
    assert smoke_attempt_candidate_sources(sources) == [("main", "verdict['candidate']")]
    assert smoke_candidate_origin(sources) == {"one_scan"}


def test_production_closure_has_no_manual_smoke_or_paper_order_route(sources):
    closure = import_closure(sources, PRODUCTION_ENTRYPOINT)
    assert "src/broker/topstepx_execution_runner.py" in closure  # non-vacuous
    assert "src/broker/luna_candidate_producer.py" in closure
    assert not closure & set(FORBIDDEN_IN_PRODUCTION_CLOSURE)
    assert paper_writer_callers(sources, closure) == []


# Activated controls: each mutation of real source text must be caught by the
# exact check above, so a green run is not vacuous.

def _mutate(sources, path, old, new):
    assert old in sources[path], (path, old)
    return {**sources, path: sources[path].replace(old, new, 1)}


def test_control_new_direct_order_route_is_detected(sources):
    mutated = _mutate(sources, "src/broker/topstepx_production_loop.py",
                      "def _execute(", "def _sneak(self):\n        self.ps.session.place_order({})\n\n    def _execute(")
    assert entry_write_sites(mutated) - set(ENTRY_ROUTE_INDEX) == {
        ("src/broker/topstepx_production_loop.py", "ProductionLoop._sneak", "place_order")}


def test_control_dropped_lifecycle_requirement_is_detected(sources):
    for path in GATED_ROUTE_PRODUCERS:
        text = sources[path]
        mutated = {**sources, path: text.replace("require_campaign_lifecycle=True", "require_campaign_lifecycle=False", 1)}
        assert produce_calls_without_lifecycle(mutated, [path]), path


def test_control_smoke_candidate_from_another_source_is_detected(sources):
    mutated = _mutate(sources, "tools/topstepx_smoke_wait.py",
                      "verdict = one_scan(", "verdict = forged_scan(")
    assert smoke_candidate_origin(mutated) == {"forged_scan"}


def test_control_smoke_tool_import_into_production_is_detected(sources):
    mutated = _mutate(sources, "src/broker/topstepx_production_loop.py",
                      "from __future__ import annotations",
                      "from __future__ import annotations\nimport tools.topstepx_execution_smoke")
    closure = import_closure(mutated, PRODUCTION_ENTRYPOINT)
    assert "tools/topstepx_execution_smoke.py" in closure


def test_control_paper_writer_call_in_production_closure_is_detected(sources):
    mutated = _mutate(sources, "src/broker/topstepx_production_loop.py",
                      "def _execute(", "def _paper(self):\n        from paper_execution.paper_broker import submit_paper_order\n        submit_paper_order()\n\n    def _execute(")
    closure = import_closure(mutated, PRODUCTION_ENTRYPOINT)
    assert paper_writer_callers(mutated, closure)
