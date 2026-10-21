"""Activated mutants for the OS-injected-name repair; the fast portability tests must fail on each."""
import json, subprocess, sys
from pathlib import Path
wt, out = Path(sys.argv[1]), Path(sys.argv[2])
src = wt / "src/recognition_validation/child.py"; orig = src.read_text()
M = {"prefix_match_not_fullmatch": ("INJECTED_ENV[name].fullmatch(value)", "INJECTED_ENV[name].match(value)"),
     "any_value_admitted": ("and not (name in INJECTED_ENV and INJECTED_ENV[name].fullmatch(value))", "and name not in INJECTED_ENV"),
     "injected_names_ignored": ("and not (name in INJECTED_ENV and INJECTED_ENV[name].fullmatch(value))", ""),
     "injected_names_in_posix_allowlist": ("ENV_ALLOWLIST = env_allowlist()", "ENV_ALLOWLIST = env_allowlist() | {'LC_CTYPE', '__CF_USER_TEXT_ENCODING'}")}
res = {}
try:
    for name, (a, b) in M.items():
        assert orig.count(a) == 1, name
        src.write_text(orig.replace(a, b))
        r = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q",
                            "tests/test_recognition_child_portability.py", "-k", "not run_in_child and not widen and not reach_a_complete"],
                           cwd=wt, capture_output=True, text=True)
        res[name] = {"killed": r.returncode != 0, "summary": r.stdout.strip().splitlines()[-1],
                     "failed": [l.split(" ")[1] for l in r.stdout.splitlines() if l.startswith("FAILED")]}
finally:
    src.write_text(orig)
out.write_text(json.dumps(res, indent=1)); print(json.dumps({k: (v["killed"], v["summary"]) for k, v in res.items()}, indent=1))
