"""Stage 5 T32: stray wall-clock audit (static inventory + run-time observation)."""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import test_po3_distinct_anchor_premise as W  # noqa: E402
import test_recognition_current_path as CP  # noqa: E402
from recognition_validation import brain_gateway as G  # noqa: E402
from recognition_validation import clock_audit as CA  # noqa: E402
from recognition_validation import contracts as C  # noqa: E402
from recognition_validation import corpus as K  # noqa: E402
from recognition_validation import driver as DR  # noqa: E402

INVENTORY = ROOT / "docs/recognition_validation/STRAY_CLOCK_INVENTORY.json"


def test_static_inventory_matches_the_committed_review_record():
    committed = json.loads(INVENTORY.read_text())["sites"]
    assert CA.inventory(ROOT / "src") == committed
    keys = {(s["path"], s["function"], s["call"]) for s in committed}
    assert ("src/ai_brain/narrative_brain.py", "_call_llm", "time.time") in keys
    assert ("src/ai_brain/thesis_lifecycle.py", "_archive_path", "datetime.utcnow") in keys


def test_a_new_wall_clock_read_is_a_visible_inventory_change(tmp_path):
    src = tmp_path / "src"
    shutil.copytree(ROOT / "src" / "market_data", src / "market_data")
    before = CA.inventory(src)
    target = src / "market_data" / "campaign_scope.py"
    target.write_text(target.read_text(encoding="utf-8")
                      + "\n\ndef _stray():\n    from datetime import datetime\n    return datetime.now()\n")
    after = CA.inventory(src)
    added = [s for s in after if s not in before]
    assert added == [{"path": "src/market_data/campaign_scope.py", "function": "_stray", "call": "datetime.now",
                      "count": 1}]


def test_runtime_wall_clock_reads_are_inventoried_and_the_brain_seam_reads_the_decision_clock(tmp_path):
    corpus = K.build_constructed_corpus(tmp_path / "corpus", session_id=CP.SESSION, contract_id=CP.CONTRACT,
                                        market_date="2026-08-19", tape=W._tape(W._HEALTHY),
                                        warmup_end="2026-08-19T15:30:00+00:00",
                                        notes="CONSTRUCTED distinct-anchor tape; mechanics only.",
                                        sealed_at="2026-10-17T00:00:00Z")
    script, _ = CP._script()
    with CA.observe_time_reads(ROOT / "src") as seen:
        DR.run_offline(corpus_path=corpus, session_id=CP.SESSION, out_root=tmp_path / "run", ecu=False,
                       trajectory_id="S5-T32", prewarm_until="2026-08-19T15:30:00Z",
                       ticks_until="2026-08-19T15:40:00Z",
                       responder=G.ScriptedResponder(script, fixture_digest=C.digest("daw-script-v1")))
    inventoried = {(s["path"], s["function"].rsplit(".", 1)[-1]) for s in CA.inventory(ROOT / "src")
                   if s["call"] == "time.time"}
    assert seen <= inventoried, sorted(seen - inventoried)
    assert ("src/ai_brain/narrative_brain.py", "_call_llm") not in seen
    print("T32 runtime time.time readers:", json.dumps(sorted(seen)))


def test_runtime_observer_positive_control_sees_a_module_attribute_time_read(tmp_path):
    import importlib.util
    module_path = tmp_path / "src" / "probe_pkg" / "probe.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("import time\n\ndef stamp():\n    return time.time()\n")
    spec = importlib.util.spec_from_file_location("stage5_t32_probe", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with CA.observe_time_reads(tmp_path / "src") as seen:
        module.stamp()
    assert seen == {("src/probe_pkg/probe.py", "stamp")}
    import time
    assert time.time is not None and time.time.__module__ == "time"  # restored
