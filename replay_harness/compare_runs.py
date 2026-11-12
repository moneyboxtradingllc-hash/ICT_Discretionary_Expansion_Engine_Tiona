"""Compare the output hashes of two complete runs.

    python replay_harness/compare_runs.py <out_run_1> <out_run_2>

Prints one line per file and exits 0 only if every file is byte-identical.
"""
from __future__ import annotations

import json
import os
import sys


def main() -> int:
    a, b = sys.argv[1], sys.argv[2]
    ha = json.load(open(os.path.join(a, "OUTPUT_HASHES.json"), encoding="utf-8"))
    hb = json.load(open(os.path.join(b, "OUTPUT_HASHES.json"), encoding="utf-8"))
    same = True
    for name in sorted(set(ha) | set(hb)):
        equal = ha.get(name) == hb.get(name)
        same = same and equal
        print(f"{'IDENTICAL' if equal else 'DIFFERENT'}  {name}  {ha.get(name)}")
    print("DETERMINISTIC" if same else "NOT DETERMINISTIC")
    return 0 if same else 1


if __name__ == "__main__":
    raise SystemExit(main())
