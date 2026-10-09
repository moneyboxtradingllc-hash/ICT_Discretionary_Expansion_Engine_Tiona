"""Certification is independent of checkout line endings, not source content."""
import builtins
from io import BytesIO
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ai_brain import production_model as PM


@pytest.fixture
def source_bytes(monkeypatch):
    """Exercise the actual closure hash without rewriting production files."""
    sources = {}
    for label, relative in PM._CONTRACT_SOURCES + PM._CONTRACT_SOURCES_REPO:
        base = ROOT if (label, relative) in PM._CONTRACT_SOURCES_REPO else ROOT / "src"
        path = base / relative
        sources[os.path.normcase(str(path))] = path.read_bytes().replace(b"\r\n", b"\n")
    original_open = builtins.open

    def read_source(path, mode="r", *args, **kwargs):
        key = os.path.normcase(os.path.abspath(path))
        if mode == "rb" and key in sources:
            return BytesIO(sources[key])
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(PM, "open", read_source, raising=False)
    return sources


@pytest.mark.parametrize("style", ["lf", "crlf", "mixed_files", "mixed_lines"])
def test_all_closure_sources_have_one_canonical_identity(source_bytes, style):
    assert len(source_bytes) == 47
    for index, (path, data) in enumerate(source_bytes.items()):
        if style == "crlf" or (style == "mixed_files" and index % 2):
            source_bytes[path] = data.replace(b"\n", b"\r\n")
        elif style == "mixed_lines":
            # Include a mixed-EOL single file, not only different file styles.
            source_bytes[path] = data.replace(b"\n", b"\r\n", 1)
    # Feature-branch source includes the deterministic Brain wake boundary and
    # the structural-risk evidence/coherence repair. This is a new contract
    # fingerprint, not a historical authorization migration.
    #
    # PROTECTED-SWING-TRUTH-20260924 changes the closure-bound structural
    # invalidation producer. The new identity is explicit; old authorization
    # is not migrated.
    #
    # PROVIDER-MODEL-IDENTITY-1 (2026-09-27) makes the closure-bound candidate
    # producer judge the SERVED model with model_matches(). It rotates again.
    # BRAIN-SOVEREIGNTY-SESSION-PO3-CONTEXT-1 demotes phase permission from
    # execution law to evidence; previous PROD authorization cannot be reused.
    # LATENCY-1 binds the conditional-plan contract, its no-Brain trigger path,
    # and the selected mechanical execution object into the same fingerprint.
    # NARRATIVE-AUTHORITY-1 separates the transfer state from its typed proof
    # family; the current authorization cannot be reused after this prompt change.
    # WATCHING-PARSER-FAIL-CLOSED-1 rejects verbose conditional actions at the
    # candidate boundary; the closure identity rotates with that execution law.
    # RAW-TRADE-INTERVAL-TRUTH-1A makes exact-time coverage registration
    # non-retroactive and verifies runtime epoch identity on each event.
    # 1B binds intervals to a proven raw-trade event-time frontier and
    # revalidates trade-only freshness before any interval can be read as live.
    # 1C binds transport parsing, runtime continuity, and interval truth because
    # each can change whether raw market history is represented as complete.
    # CAMPAIGN-DRAW-TRUTH-1 adds settled-chart measurement and history-revision
    # invalidation. CAMPAIGN-DRAW-TRUTH-1A directly binds its derivation source
    # because the next lifecycle layer will consume those facts. The
    # authorization identity therefore rotates again.
    # CAMPAIGN-LIFECYCLE-1 adds a stateless campaign projection and participation
    # gate; prior production authorization is stale after this contract change.
    # CAMPAIGN-LIFECYCLE-1 repair binds the public Draw contract and the
    # sealed conditional-plan authority and no-Brain trigger revalidation; old
    # authorization is stale.
    # TRADE-HORIZON-1 adds candidate-scope and protected-structure evidence;
    # prior production authorization is stale after this rotation.
    # EXPLICIT-BRAIN-ACTION-AUTHORITY binds prompt/schema/producer enforcement
    # and the safe stand_down emitted by deterministic/fallback assembly.
    # NA-1 CAUSAL CONTINUITY REPAIR binds narrative succession, transfer
    # evidence classification and cross-scan falsifier memory.
    # ICT REVERSAL ENTRY COMPOSITION binds settled reversal formation custody,
    # causal protected-anchor lifetimes and the confirmed-reversal participation
    # amendment. Previous authorization is stale after this change.
    # PROTECTED-LIFETIME-MUTATION-CLASSIFICATION closes the UNKNOWN-to-replacement
    # boundary in the producer-owned protected-swing authority.
    # CAMPAIGN-DRAW TEMPORAL-AUTHORITY CLOSURE: participation authority is
    # projected after current acceptance and requires settled evidence beyond
    # a Draw's birth anchor; authority consumers no longer fall back to truth.
    # STAGE-2 CONSUMER CLOSURE: the ordinary production consumer acts on a
    # permissive Lifecycle only together with the participation authority it
    # was computed from.
    # STAGE-2 EXACT DRAW BINDING: permissive Lifecycle, the ordinary consumer
    # and conditional plans bind the exact Draw record and its current
    # settled measurement, not matching labels.
    # STAGE-3B-1A COGNITIVE HISTORY HYGIENE: only proved stance rows supply the
    # incumbent, and ECU cognition reads the cycle-owned custody (ecu.py bound).
    # STAGE-3B-1A-R1: a malformed retained row is withheld individually and
    # can no longer suppress the healthy incumbent or revision marking.
    # STAGE-3B-1B: local active-leg evidence is published under leg names and
    # the unbound campaign premise as UNKNOWN; prompt field doctrine updated.
    # STAGE-3C-1: shadow premise facts (authority none) join the closure.
    # STAGE-3C-1-R1: shadow certificate boundaries repaired (source order,
    # chain retirement, watched-life context, duplicate canonical facts).
    assert PM.brain_contract_fingerprint() == "brain:e50a1b36594a6c26"


@pytest.mark.parametrize("addition", [
    b"\nCERTIFICATION_PROBE = 1\n",  # semantic source content
    b"\n# certification probe\n",   # comments remain bound
    b" ",                          # arbitrary whitespace remains bound
    b"\n",                         # trailing blank lines remain bound
    b"\nprobe = '\\r\\n'\n",       # escaped literal bytes are not line endings
    b"\r",                         # lone CR is not silently canonicalized
])
@pytest.mark.parametrize("relative", [
    "src/ai_brain/brain_prompt.py", "tools/topstepx_production_session.py",
    "src/broker/topstepx_realtime.py", "src/broker/topstepx_market_runtime.py",
    "src/data_feed/trade_interval_truth.py",
    "src/market_data/campaign_draw_truth.py",
    "src/market_data/campaign_lifecycle.py",
    "src/market_data/reversal_formation.py",
    "src/ai_brain/narrative_continuity.py",
    "src/ai_brain/stance_memory.py",
    "src/live_scan/production_scan_cycle.py",
    "src/broker/topstepx_production_loop.py",
    "src/market_state/active_path.py",
    "src/ai_brain/narrative_brain.py",
])
def test_other_content_changes_remain_bound_in_both_anchors(source_bytes, relative, addition):
    before = PM.brain_contract_fingerprint()
    key = os.path.normcase(str(ROOT / relative))
    source_bytes[key] += addition
    assert PM.brain_contract_fingerprint() != before
