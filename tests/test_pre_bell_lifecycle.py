"""PRE-BELL LIFECYCLE — the window changes state at 09:30; the PROCESS does not.

2026-08-20. Arming at 09:02 exited with ZERO scans. `should_continue` asked only
`production_window_open()` and then, if flat, stopped -- a rule written for the
state AFTER the close. Before the open it read identically:

    "the window is not open and I am flat"

is `session complete` at 14:30 and `not started yet` at 09:02, and the controller
could not tell them apart. So the operating requirement -- armed, alive, flat and
waiting BEFORE the bell -- was impossible to satisfy.

THE REPAIR IS ONLY: pre-window flat must not terminate the process.

It is emphatically NOT "skip intelligence before the window". A first version
did suppress pre-open scans to save Brain tokens; that defeats the reason for
being up early, which is that Luna ORIENTS on the developing premarket instead
of forming her first read cold at the bell.

    LUNA THINKS BEFORE THE BELL.  EXECUTION WAITS FOR IT.

`in_window` downstream of the scan is what keeps that safe.
"""
from __future__ import annotations

import importlib.util
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

_spec = importlib.util.spec_from_file_location(
    "prod_session_cli", os.path.join(ROOT, "tools", "topstepx_production_session.py"))
PS = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(PS)


def _et(hh, mm):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime(2026, 8, 20, hh, mm, tzinfo=ZoneInfo("America/New_York"))


class TestTheMissingPredicate:
    # PRE-NY-EXECUTION-WINDOW-1 (2026-08-23). The window now opens at 09:00, so
    # the "before" state ends there. The PREDICATE under test is unchanged --
    # "is the window still ahead of us" -- only the boundary moved, and the
    # specimen times move with it rather than the assertions being relaxed.
    @pytest.mark.parametrize("hh,mm,expected", [
        (8, 30, True),      # pre-bell
        (8, 45, True),
        (8, 59, True),
        (9, 0, False),      # the window opens
        (9, 15, False),
        (11, 0, False),
        (14, 0, False),     # closed, but AFTER -- not "before"
        (16, 7, False),
    ])
    def test_before_the_window_is_its_own_state(self, hh, mm, expected):
        assert PS.before_production_window(_et(hh, mm)) is expected

    def test_before_and_open_are_mutually_exclusive(self):
        for hh, mm in ((8, 45), (8, 59), (9, 0), (9, 15), (12, 0), (14, 30)):
            t = _et(hh, mm)
            assert not (PS.before_production_window(t) and PS.production_window_open(t))

    def test_the_gap_this_closes(self):
        """A pre-bell time and 14:30 are both 'window closed + flat'. They are
        NOT the same.

        PRE-NY-EXECUTION-WINDOW-1: the original specimen was 09:02, which is now
        lawfully INSIDE the window -- that is the repair, not a broken test. The
        theorem is untouched: `before` and `after` must remain distinguishable,
        so the specimen moves to 08:45 and still proves it.
        """
        pre, post = _et(8, 45), _et(14, 30)
        assert PS.production_window_open(pre) is False
        assert PS.production_window_open(post) is False
        assert PS.before_production_window(pre) is True
        assert PS.before_production_window(post) is False


class TestTheControllerStaysAlive:
    """`should_continue` is a closure inside `run_production_scans`, so the
    branch order is verified structurally rather than by re-implementing it."""

    @staticmethod
    def _branches():
        import ast
        import inspect
        src = inspect.getsource(PS.run_production_scans)
        tree = ast.parse(src.lstrip())
        fn = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "should_continue"][0]
        return ast.unparse(fn)

    def test_pre_window_returns_true(self):
        body = self._branches()
        assert "before_production_window()" in body
        i_pre = body.index("before_production_window()")
        i_flat = body.index("open_positions()")
        assert i_pre < i_flat, "the flat check must not decide before-window"

    def test_the_post_window_rule_is_unchanged(self):
        body = self._branches()
        assert "return not flat" in body

    def test_scans_mode_is_untouched(self):
        assert "return i < scans" in self._branches()


class TestLunaThinksBeforeTheBell:
    """The repair must NOT become "skip intelligence before the window".

    An earlier version held the loop and skipped `scan_once` pre-open to save
    Brain tokens. That defeats the reason for being up early: the bot runs
    before the bell so the Brain ORIENTS on the developing premarket rather than
    forming its first read cold at 09:30. Execution is what waits, not thinking.
    """

    @staticmethod
    def _loop_body():
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(PS.run_production_scans).lstrip())
        return ast.unparse([n for n in ast.walk(tree) if isinstance(n, ast.While)][0])

    def test_the_loop_scans_unconditionally(self):
        """No pre-window branch may skip the scan."""
        body = self._loop_body()
        assert "loop.scan_once()" in body
        assert "before_production_window()" not in body,             "the loop body must not special-case the pre-window state"

    def test_no_continue_guards_the_scan(self):
        """No `continue` may skip `scan_once()`.

        EVENT-WAKE-ACTIONABLE-STRUCTURE-1 — BINDING, not textual containment.
        This used `ast.walk`, which descends through NESTED loops, so it failed
        on a `continue` inside the interruptible wait loop that sits AFTER the
        scan. That `continue` binds to the inner `while`, returns to the inner
        header, and cannot reach the scan-loop header at all; the only exit from
        the wait is the immutable deadline or an interaction, after which the
        scan loop proceeds to `scan_once()` normally.

        The proposition is unchanged and is NOT relaxed: a `continue` whose
        NEAREST ENCLOSING LOOP is the scan loop is still an outright failure.
        Only the reach of the search is corrected.
        """
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(PS.run_production_scans).lstrip())
        loop = [n for n in ast.walk(tree) if isinstance(n, ast.While)][0]

        found = []

        def scan(nodes):
            for n in nodes:
                if isinstance(n, (ast.While, ast.For, ast.AsyncFor)):
                    continue          # binds to THAT loop, not the scan loop
                if isinstance(n, ast.Continue):
                    found.append(n)
                else:
                    scan(list(ast.iter_child_nodes(n)))

        scan(list(ast.iter_child_nodes(loop)))
        if found:
            pytest.fail("a `continue` in the scan loop can suppress intelligence")

    def test_execution_is_gated_by_the_window_not_by_scanning(self):
        """`in_window` is the ROUTING boundary and lives downstream of the scan.

        This is why a pre-window scan is safe: the Brain may think, narrate and
        analyse, and the candidate path still refuses to create exposure.
        """
        import inspect
        from broker import luna_candidate_producer as CP
        from broker import topstepx_candidate_freshness as FR
        assert "if not in_window:" in inspect.getsource(CP)
        assert "if not in_window:" in inspect.getsource(FR)


class TestHardFlattenStillOwnsTheClose:
    def test_hard_flatten_is_still_checked_in_the_loop(self):
        import ast
        import inspect
        src = ast.unparse(ast.parse(inspect.getsource(PS.run_production_scans).lstrip()))
        assert "hard_flatten_due()" in src

    def test_a_date_without_hard_flatten_keeps_the_old_behaviour(self):
        assert PS.hard_flatten_due(_et(15, 59)) is False   # none configured today
