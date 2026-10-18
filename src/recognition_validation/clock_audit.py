"""T32 stray-clock audit: every production wall-clock read, statically and at run time.

The static inventory names each `datetime.now/utcnow/today`, `date.today` and
`time.time/time_ns/monotonic/perf_counter` call site under `src/` (excluding
this harness) by file, enclosing function and call. It is committed as
docs/recognition_validation/STRAY_CLOCK_INVENTORY.json so a new wall-clock
read on any path is a visible diff, never a silent change.

The dynamic observer wraps `time.time` for the duration of an offline run and
records which production functions actually read it. Inside the gateway seam
narrative_brain reads the decision clock instead (brain_gateway._ClockTime).
`datetime.now` cannot be intercepted on the C type, so it is covered by the
static inventory only.
"""
from __future__ import annotations

import ast
import contextlib
import sys
import time
from pathlib import Path

CLOCK_CALLS = {("datetime", "now"), ("datetime", "utcnow"), ("datetime", "today"), ("date", "today"),
               ("time", "time"), ("time", "time_ns"), ("time", "monotonic"), ("time", "perf_counter")}
HARNESS = "recognition_validation"


def _calls(tree: ast.AST):
    stack = []

    def visit(node):
        named = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        if named:
            stack.append(node.name)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            value = node.func.value
            owner = value.id if isinstance(value, ast.Name) else value.attr if isinstance(value, ast.Attribute) else ""
            if (owner, node.func.attr) in CLOCK_CALLS:
                yield ".".join(stack) or "<module>", f"{owner}.{node.func.attr}"
        for child in ast.iter_child_nodes(node):
            yield from visit(child)
        if named:
            stack.pop()
    yield from visit(tree)


def inventory(src_root) -> list:
    """Sorted [{path, function, call, count}] over production source."""
    src_root = Path(src_root)
    counts: dict = {}
    for path in sorted(src_root.rglob("*.py")):
        rel = path.relative_to(src_root.parent).as_posix()
        if HARNESS in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=rel)
        for function, call in _calls(tree):
            key = (rel, function, call)
            counts[key] = counts.get(key, 0) + 1
    return [{"path": p, "function": f, "call": c, "count": n} for (p, f, c), n in sorted(counts.items())]


@contextlib.contextmanager
def observe_time_reads(src_root):
    """Record (path, function) of production frames that call `time.time()`."""
    src_root = Path(src_root).resolve()
    real = time.time
    seen: set = set()

    def observed():
        frame = sys._getframe(1)
        try:
            path = Path(frame.f_code.co_filename).resolve()
            if path.is_relative_to(src_root) and HARNESS not in path.parts:
                seen.add((path.relative_to(src_root.parent).as_posix(), frame.f_code.co_name))
        finally:
            del frame
        return real()
    time.time = observed
    try:
        yield seen
    finally:
        time.time = real
