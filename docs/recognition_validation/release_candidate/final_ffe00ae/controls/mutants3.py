import json, subprocess, sys
from pathlib import Path
wt, out = Path(sys.argv[1]), Path(sys.argv[2])
src = wt / "src/broker/topstepx_production_loop.py"; orig = src.read_text()
M = {"memory_latch_not_set": ("        self._terminal_cognition = lock\n        self.active_candidate = None\n        if self.active_conditional_plan is not None:\n            self._clear_conditional_plan()\n        return self._terminal_cognition_result(lock, persistence_error)",
                              "        self.active_candidate = None\n        if self.active_conditional_plan is not None:\n            self._clear_conditional_plan()\n        return self._terminal_cognition_result(lock, persistence_error)"),
     "persistence_error_hidden": ("        return self._terminal_cognition_result(lock, persistence_error)", "        return self._terminal_cognition_result(lock, None)"),
     "plan_not_cleared_on_latch": ("        self._terminal_cognition = lock\n        self.active_candidate = None\n        if self.active_conditional_plan is not None:",
                                   "        self._terminal_cognition = lock\n        self.active_candidate = None\n        if False:")}
res = {}
try:
    for name, (a, b) in M.items():
        assert orig.count(a) == 1, name
        src.write_text(orig.replace(a, b))
        r = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "tests/test_terminal_latch_persistence_failure.py"],
                           cwd=wt, capture_output=True, text=True)
        res[name] = {"killed": r.returncode != 0, "summary": r.stdout.strip().splitlines()[-1]}
finally:
    src.write_text(orig)
out.write_text(json.dumps(res, indent=1)); print({k: v["killed"] for k, v in res.items()})
