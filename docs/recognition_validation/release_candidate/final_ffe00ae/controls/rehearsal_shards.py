"""rehearsal_shards.py <S> <clone> <shard_dir> <worker> <workers>: the full-suite shards under rehearsal_guard."""
import json, subprocess, sys
from pathlib import Path
S, clone, out, worker, workers = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
tools = Path(__file__).resolve().parent
plan = json.loads((out / "shards.json").read_text())
for i, shard in enumerate(plan["shards"]):
    if i % workers != worker or (out / f"shard_{i:02d}.done").exists():
        continue
    log, xml, trace = out / f"shard_{i:02d}.log", out / f"shard_{i:02d}.xml", out / f"shard_{i:02d}.trace.json"
    launcher = ("import sys; sys.path.insert(0, sys.argv[1]); import pytest, rehearsal_guard as R; "
                "R.OUT = sys.argv[2]; sys.exit(pytest.main(sys.argv[3:], plugins=[R]))")
    rc = subprocess.run([str(S / "g5/run.sh"), clone, str(log), "python3", "-c", launcher, str(tools), str(trace),
                         "-q", "-rfE", "-p", "no:cacheprovider", f"--junitxml={xml}", *shard["files"]]).returncode
    (out / f"shard_{i:02d}.done").write_text(json.dumps({"rc": rc, "files": len(shard["files"])}))
