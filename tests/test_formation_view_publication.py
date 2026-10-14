"""PO3 formation authority is bound to the exact snapshot its producer published.

S4L O4. Two genuine ProductionScanCycles share contract, market session, settled
cutoff and numeric history revision 0. Producer B (tape p2h) retains the bearish
5m PO3 formation EXPECTED_ID. Producer A retires the same formation through a
genuine matching-direction release of its own:

  * "r2"   -- B's tape with one changed close: the 14:46 1m bar closes
              29519.5 above the 1m load-bearing high 29519.25 (B closes 29517.0;
              high and low are identical). A releases at 14:46, inside the
              raid (14:45) .. validation (14:55) interval, while every 5m witness
              bar is identical to B's: the difference lies outside the witness
              digests.
  * "post" -- B's tape through 15:01, then a 3m release of the 15:00 bucket
              observed at 15:02, i.e. after validation, before the 5m bucket
              settles.

Before this repair current_block authenticated only the view's own seal,
custody, scope and release history, so B's genuine view placed on A's snapshot
made A's catalog, exact named tool gate and sealed-plan participation binding
accept an object A's own custody had retired. Production attaches exactly one
view per scan snapshot (ProductionScanCycle._attach_reversal_formation), so the
foreign placement is a DEFENSE-ONLY consumer probe; the contract it checks is
"only the producer's own retained formation may execute".

Bars are lawful synthetic OHLC appended to Codex's fixed natural W5 seed (see
test_po3_execution_identity). The Brain transport is mocked.
"""
import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

import test_campaign_scope as T
import test_campaign_scope_binding as B
import test_po3_execution_identity as X
import test_reversal_foundation_proof_closure as RF
from broker.conditional_plan_authority import _current_po3_binding
from broker.luna_candidate_producer import CandidateProducer, NoCandidate
from market_data.reversal_formation import current_block

FORMATION_ID = X.EXPECTED_ID
UNAVAILABLE = X.UNAVAILABLE

# B's tape through 15:01; then the 15:02 bar closes the 3m 15:00 bucket above
# its load-bearing high (a same-direction release after validation).
_POST = [row for row in X._P2H if row[0] <= "15:01"] + [
    ("15:02", 29539.5, 29510.0, 29539.0), ("15:03", 29539.0, 29505.0, 29506.0),
    ("15:04", 29507.0, 29504.0, 29505.0)]
_R2 = [("14:46", 29521.0, 29516.75, 29519.5)] + X._P2
PAIRS = {"r2": ["15:01", "15:02"], "post": ["15:02", "15:03"]}


def _tape(key):
    if key in ("post", "r2"):
        head = T._tape()[:106]
        return head + X._bars(_POST if key == "post" else _R2, head[-1]["close"])
    return X._tape(key)


def _producer(root, monkeypatch, key, *, ecu, minutes, on_scan=None):
    """REAL ProductionScanCycle over one tape, stopped at the last minute.

    The Brain (mocked) is invoked from 14:59 in both lanes: under ECU the view
    is attached by the pre-cognition hook before the one canonical call, in the
    non-ECU lane by the ordinary post-build path."""
    from live_scan.production_scan_cycle import ProductionScanCycle
    from broker.topstepx_slippage import QuoteCapture
    root.mkdir()
    X._isolate(root, monkeypatch)
    tape = _tape(key)
    price = [tape[0]["close"]]

    def quote():
        return QuoteCapture(captured_at=datetime.now(timezone.utc), best_bid=price[0],
                            best_ask=price[0] + .25, last_trade=price[0],
                            contract_id=T.CONTRACT, market_data_age_seconds=.25)

    cycle = ProductionScanCycle(symbol="MNQ", contract_id=T.CONTRACT,
                                session_id="S4L-O4", quote_provider=quote)
    calls, armed, seen, last = [], False, {}, max(minutes)
    for end in range(20, len(tape) + 1):
        bars = tape[:end]
        price[0] = bars[-1]["close"]
        hm = bars[-1]["timestamp"][11:16]
        brain = hm >= "14:59"
        if brain and not armed:
            RF._mock_current_brain(monkeypatch, calls,
                                   output_mutator=X._adversarial("family", price))
            monkeypatch.setenv("BRAIN_ECU_MODE", "true" if ecu else "false")
            armed = True
        scan = cycle.scan(bars, now=datetime.fromisoformat(bars[-1]["timestamp"]) + timedelta(minutes=1),
                          invoke_brain=brain)
        if hm in minutes:
            seen[hm] = scan
        if on_scan is not None:
            on_scan(hm, scan["snapshot"])
        if hm == last:
            break
    assert calls, "the mocked Brain was never invoked"
    return cycle, seen


def _gate(snapshot):
    try:
        row = CandidateProducer._assert_tool_detected(
            ["po3_reversal_order_block"], "bearish", snapshot, occurrence_id=FORMATION_ID)
    except NoCandidate as exc:
        return ("NoCandidate", exc.reason)
    return ("DETECTED", row.get("occurrence_id"), row.get("execution_eligible"))


def _candidate(scan, cycle):
    try:
        candidate = B._candidate(scan, cycle)
    except NoCandidate as exc:
        return ("NoCandidate", exc.reason)
    return ("CANDIDATE", candidate.extras.get("selected_tool_occurrence_id"))


def _authority(snapshot):
    block = current_block(snapshot, "bearish")
    return {
        "block": ((block or {}).get("formation_authority") or {}).get("occurrence_id"),
        "catalog": [(r["execution_eligible"], r["occurrence_id"], r["execution_ineligible_reason"])
                    for r in X._po3(snapshot)],
        "gate": _gate(snapshot),
        "binding": (_current_po3_binding(snapshot, "bearish", FORMATION_ID) or {}).get("occurrence_id"),
    }


EXECUTABLE = {"block": FORMATION_ID, "catalog": [(True, FORMATION_ID, None)],
              "gate": ("DETECTED", FORMATION_ID, True), "binding": FORMATION_ID}


def _refused(authority):
    return (authority["block"] is None and authority["binding"] is None
            and authority["catalog"] and all(row == (False, None, UNAVAILABLE)
                                             for row in authority["catalog"])
            and authority["gate"][0] == "NoCandidate")


def _swap(snapshot, view):
    own = snapshot["reversal_formation_view"]
    snapshot["reversal_formation_view"] = view
    return own


@pytest.mark.parametrize("pair", sorted(PAIRS))
@pytest.mark.parametrize("ecu", [False, True], ids=["non-ecu", "ecu"])
def test_foreign_genuine_view_cannot_revive_an_object_the_consumer_retired(
        tmp_path, monkeypatch, ecu, pair):
    minutes = PAIRS[pair]
    b_cycle, b = _producer(tmp_path / "B", monkeypatch, "p2h", ecu=ecu, minutes=minutes)
    a_cycle, a = _producer(tmp_path / "A", monkeypatch, pair, ecu=ecu, minutes=minutes)
    for minute in minutes:
        bsnap, asnap = b[minute]["snapshot"], a[minute]["snapshot"]
        # Same identity coordinates: contract, session, cutoff, revision.
        assert bsnap["timestamp"] == asnap["timestamp"]
        assert bsnap["contract_id"] == asnap["contract_id"] == T.CONTRACT
        assert (bsnap["derived_state"]["history_revision"]
                == asnap["derived_state"]["history_revision"] == 0)
        # Controls: B's own publication executes; A's own custody retired it.
        assert _authority(bsnap) == EXECUTABLE, minute
        a_own = _authority(asnap)
        assert _refused(a_own), (minute, a_own)
        # The retirement is A's own genuine release, absent from B's history.
        def releases(cycle):
            return {(r.get("owner"), r.get("source_tf"), r.get("source_bar_time"))
                    for r in cycle._active_path.releases}
        only_a = releases(a_cycle) - releases(b_cycle)
        assert any(owner == "bearish" for owner, _, _ in only_a), only_a

        # B's genuine view on A's snapshot. Before the repair this made A's
        # full CandidateProducer author a CANDIDATE from the retired object
        # (r2 at 15:02, both lanes); A's own outcome is a refusal.
        a_outcome = _candidate(a[minute], a_cycle)
        own = _swap(asnap, bsnap["reversal_formation_view"])
        try:
            mixed = _authority(asnap)
            outcome = _candidate(a[minute], a_cycle)
        finally:
            _swap(asnap, own)
        assert _refused(mixed), (minute, mixed)
        assert a_outcome[0] == "NoCandidate", (minute, a_outcome)
        assert outcome == a_outcome, (minute, outcome, a_outcome)
        # And the reverse: A's view never vouches for B's snapshot either,
        # although B's own producer still retains the object.
        own = _swap(bsnap, a[minute]["snapshot"]["reversal_formation_view"])
        try:
            reverse = _authority(bsnap)
        finally:
            _swap(bsnap, own)
        assert reverse["block"] is None and reverse["binding"] is None, (minute, reverse)
        assert not any(row[0] for row in reverse["catalog"]), (minute, reverse)
        # Restores are exact.
        assert _authority(asnap) == a_own and _authority(bsnap) == EXECUTABLE


def test_sealed_participation_object_does_not_survive_a_foreign_view(tmp_path, monkeypatch):
    # A captures the PO3 participation object at 15:01 while its own custody
    # still retains the formation; at 15:02 A's own release retires it.
    # Custody is live state: the participation object is read at capture time.
    captured = {}

    def capture(hm, snapshot):
        if hm == "15:01":
            captured["sealed"] = _current_po3_binding(snapshot, "bearish", FORMATION_ID)

    _, b = _producer(tmp_path / "B", monkeypatch, "p2h", ecu=False, minutes=["15:02"])
    _, a = _producer(tmp_path / "A", monkeypatch, "post", ecu=False, minutes=["15:02"],
                     on_scan=capture)
    sealed = captured["sealed"]
    assert sealed and sealed["occurrence_id"] == FORMATION_ID
    trigger = a["15:02"]["snapshot"]
    assert _current_po3_binding(trigger, "bearish", FORMATION_ID) is None
    own = _swap(trigger, b["15:02"]["snapshot"]["reversal_formation_view"])
    try:
        # The sealed-plan recheck compares this against the sealed object.
        mixed = _current_po3_binding(trigger, "bearish", FORMATION_ID)
    finally:
        _swap(trigger, own)
    assert mixed is None and mixed != sealed
    # B's own trigger-time object is still the producer's exact binding.
    assert _current_po3_binding(b["15:02"]["snapshot"], "bearish", FORMATION_ID)["occurrence_id"] \
        == FORMATION_ID


def test_view_authority_is_limited_to_its_own_publication(tmp_path, monkeypatch):
    _, scans = X._brainless(tmp_path, monkeypatch, "p2h", stop="15:03")
    earlier, later = scans["15:01"]["snapshot"], scans["15:03"]["snapshot"]
    # Both publications are live: custody still retains the formation, so the
    # earlier snapshot keeps its own (revalidated) authority.
    assert _authority(earlier) == EXECUTABLE
    assert _authority(later) == EXECUTABLE
    # An earlier view moved onto a later snapshot is not that snapshot's
    # publication, and a later view does not vouch for an earlier snapshot.
    own = _swap(later, earlier["reversal_formation_view"])
    try:
        assert _refused(_authority(later))
    finally:
        _swap(later, own)
    own = _swap(earlier, later["reversal_formation_view"])
    try:
        assert _refused(_authority(earlier))
    finally:
        _swap(earlier, own)
    # Shallow copies, deep copies and JSON restores are not the publication.
    assert _refused(_authority(dict(later)))
    assert _refused(_authority(copy.copy(later)))
    assert _refused(_authority(copy.deepcopy(later)))
    assert _refused(_authority(json.loads(json.dumps(later, default=str))))
    # The publication itself is untouched.
    assert _authority(later) == EXECUTABLE and _authority(earlier) == EXECUTABLE
