"""Stage 5 M02: immutable corpus, release availability and deny-by-default ports.

The CONSTRUCTED distinct-anchor tape (test_po3_distinct_anchor_premise) is
ingested as a sealed ENGINEERING_ONLY corpus; every negative is a minimal
change to that healthy twin.
"""
import copy
import json
import os
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import test_po3_distinct_anchor_premise as W  # noqa: E402
from recognition_validation import contracts as C  # noqa: E402
from recognition_validation import corpus as K  # noqa: E402
from recognition_validation import ports as P  # noqa: E402

CONTRACT = "CON.F.US.MNQ.Z26"
SESSION = "DAW-CONSTRUCTED-20260819"


def _tape():
    return W._tape(W._HEALTHY)


def _build(root):
    return K.build_constructed_corpus(root, session_id=SESSION, contract_id=CONTRACT, market_date="2026-08-19",
                                      tape=_tape(), warmup_end="2026-08-19T15:30:00+00:00",
                                      notes="CONSTRUCTED distinct-anchor tape; mechanics only.",
                                      sealed_at="2026-10-17T00:00:00Z")


def _utc(hhmm, second=0):
    return datetime(2026, 8, 19, int(hhmm[:2]), int(hhmm[3:]), second, tzinfo=timezone.utc)


def test_constructed_corpus_round_trips_with_verified_artifacts_and_honest_layers(tmp_path):
    corpus = K.load_corpus(_build(tmp_path))
    assert corpus.document["selection_state"] == "ENGINEERING_ONLY"
    assert corpus.document["seal"]["sha256"] == corpus.digest
    session = corpus.sessions[SESSION]
    assert session.artifacts_verified and len(session.stream.releases) == len(_tape())
    assert session.layers["chart"][0] == "ELIGIBLE"
    assert session.layers["quotes"][0] == "UNPROVEN"
    assert session.layers["cognition_archive"][0] == "UNPROVEN"
    assert session.layers["recognition_benchmark"] == ("UNPROVEN", ["owner_selection_D01_absent"])
    assert session.entry["eligibility"] == "PARTIAL" and session.entry["exclusion_reasons"]


def test_release_is_visible_only_once_its_minute_settles(tmp_path):
    stream = K.load_corpus(_build(tmp_path)).sessions[SESSION].stream
    before = stream.candles_at(_utc("16:15", 59))
    at = stream.candles_at(_utc("16:16"))
    assert before[-1]["timestamp"] == "2026-08-19T16:14:00+00:00"
    assert at[-1]["timestamp"] == "2026-08-19T16:15:00+00:00"
    assert len(stream.candles_at(_utc("16:16"), lookback=300)) == len(at) <= 300
    copy_a, copy_b = stream.candles_at(_utc("16:16")), stream.candles_at(_utc("16:16"))
    copy_a[-1]["high"] = -1
    assert copy_b[-1]["high"] != -1


def _releases(root):
    corpus = json.loads((Path(root) / "corpus.json").read_text())
    ref = corpus["sessions"][0]["availability_events"]
    return json.loads((Path(root) / ref["path"]).read_text())


def _restatement(docs, hhmm, *, high, available, supersedes=1, version=2):
    target = next(d for d in docs if d["bar_open_utc"] == f"2026-08-19T{hhmm}:00Z")
    revised = copy.deepcopy(target)
    revised.update(document_id=target["document_id"] + ":v2", version=version, supersedes_version=supersedes,
                   available_at_utc=available, sequence=max(d["sequence"] for d in docs) + 1)
    revised["bar"]["high"] = high
    return revised


def test_provider_restatement_appears_only_from_its_own_availability(tmp_path):
    _build(tmp_path)
    docs = _releases(tmp_path)
    docs.append(_restatement(docs, "16:15", high=29518.25, available="2026-08-19T16:45:00Z"))
    stream = K.ReleaseStream.from_documents(docs, session_id=SESSION, contract_id=CONTRACT)
    assert stream.has_revisions()
    raid = lambda t: next(c for c in stream.candles_at(t) if c["timestamp"].startswith("2026-08-19T16:15"))
    assert raid(_utc("16:44"))["high"] == W.BASE + 19.0           # original version, never backfilled
    assert raid(_utc("16:45"))["high"] == 29518.25                # corrected from its availability on


@pytest.mark.parametrize("case,code", [
    ("hidden_revision", "HIDDEN_OR_UNORDERED_REVISION"),
    ("duplicate_version", "DUPLICATE_BAR_VERSION"),
    ("mixed_contract", "MIXED_CONTRACT"),
    ("sequence_reused", "RELEASE_SEQUENCE_NOT_INCREASING"),
    ("arrival_out_of_order", "RELEASE_ARRIVAL_OUT_OF_ORDER"),
    ("foreign_session", "RELEASE_SESSION_MISMATCH"),
    ("future_bar", "FUTURE_BAR_LEAK"),
])
def test_release_stream_negatives(tmp_path, case, code):
    _build(tmp_path)
    docs = _releases(tmp_path)
    K.ReleaseStream.from_documents(docs, session_id=SESSION, contract_id=CONTRACT)   # healthy twin
    if case == "hidden_revision":
        docs.append(_restatement(docs, "16:15", high=29518.25, available="2026-08-19T16:45:00Z", supersedes=None))
    elif case == "duplicate_version":
        docs.append(_restatement(docs, "16:15", high=29518.25, available="2026-08-19T16:45:00Z", version=1,
                                 supersedes=None))
    elif case == "mixed_contract":
        docs[5]["contract_id"] = docs[5]["bar"]["contract"] = "CON.F.US.MNQ.H27"
    elif case == "sequence_reused":
        docs[6]["sequence"] = docs[5]["sequence"]
    elif case == "arrival_out_of_order":
        docs[5]["available_at_utc"] = docs[7]["available_at_utc"]
    elif case == "foreign_session":
        docs[3]["session_id"] = "OTHER"
    elif case == "future_bar":
        docs[7]["available_at_utc"] = "2026-08-19T12:00:00Z"
    with pytest.raises(C.ContractError) as exc:
        K.ReleaseStream.from_documents(docs, session_id=SESSION, contract_id=CONTRACT)
    assert exc.value.code == code


def test_tampered_missing_or_escaping_artifacts_refuse(tmp_path):
    path = _build(tmp_path / "ok")
    K.load_corpus(path)
    corpus = json.loads(path.read_text())
    tape = tmp_path / "ok" / corpus["sessions"][0]["original"]["path"]
    tape.write_bytes(tape.read_bytes().replace(b"29539.0", b"29540.0"))
    with pytest.raises(C.ContractError) as exc:
        K.load_corpus(path)
    assert exc.value.code in ("ARTIFACT_DIGEST_MISMATCH", "ARTIFACT_BYTES_MISMATCH")
    path2 = _build(tmp_path / "gone")
    corpus2 = json.loads(path2.read_text())
    (tmp_path / "gone" / corpus2["sessions"][0]["original"]["path"]).unlink()
    with pytest.raises(C.ContractError) as exc:
        K.load_corpus(path2)
    assert exc.value.code == "ARTIFACT_MISSING"


def test_symlink_artifact_refuses_when_platform_can_create_links(tmp_path):
    path3 = _build(tmp_path / "link")
    corpus3 = json.loads(path3.read_text())
    original = tmp_path / "link" / corpus3["sessions"][0]["original"]["path"]
    data = original.read_bytes()
    original.unlink()
    outside = tmp_path / "outside.json"
    outside.write_bytes(data)
    try:
        os.symlink(outside, original)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows account lacks symlink creation privilege; tamper/missing tests run separately")
        raise
    with pytest.raises(C.ContractError) as exc:
        K.load_corpus(path3)
    assert exc.value.code == "SYMLINK_ARTIFACT"


def test_output_root_reuse_and_overwrite_refuse(tmp_path):
    _build(tmp_path)
    with pytest.raises(C.ContractError) as exc:
        _build(tmp_path)
    assert exc.value.code == "OUTPUT_ROOT_REUSE"
    with pytest.raises(C.ContractError) as exc:
        K.write_artifact(tmp_path, "corpus.json", b"{}", "CONSTRUCTED")
    assert exc.value.code == "ARTIFACT_OVERWRITE_REFUSED"


def test_final_history_only_cannot_hide_revisions(tmp_path):
    path = _build(tmp_path)
    corpus = json.loads(path.read_text())
    docs = _releases(tmp_path)
    docs.append(_restatement(docs, "16:15", high=29518.25, available="2026-08-19T16:45:00Z"))
    ref = corpus["sessions"][0]["availability_events"]
    data = json.dumps(docs).encode("utf-8")
    (tmp_path / ref["path"]).write_bytes(data)
    corpus["sessions"][0]["availability_events"].update(sha256=C.sha256_hex(data), bytes=len(data))
    corpus["sessions"][0]["history_track"] = "FINAL_HISTORY_ONLY"
    corpus["seal"]["sha256"] = C.seal_digest(corpus)
    path.write_text(json.dumps(corpus))
    with pytest.raises(C.ContractError) as exc:
        K.load_corpus(path)
    assert exc.value.code == "FINAL_HISTORY_WITH_REVISIONS"


def test_decision_clock_is_aware_and_monotonic():
    clock = P.DecisionClock(_utc("16:00"))
    clock.set(_utc("16:01"))
    assert clock() == clock.now() == _utc("16:01")
    with pytest.raises(C.ContractError) as exc:
        clock.set(_utc("16:00"))
    assert exc.value.code == "CLOCK_MOVED_BACKWARDS"
    with pytest.raises(C.ContractError) as exc:
        P.DecisionClock(datetime(2026, 8, 19, 16, 0))
    assert exc.value.code == "TIMEZONE_REQUIRED"
    assert P.real_utc_now().year >= 2026 and P.real_utc_now() > _utc("16:01")


def test_local_candle_port_serves_only_what_is_available_for_its_symbol(tmp_path):
    stream = K.load_corpus(_build(tmp_path)).sessions[SESSION].stream
    clock = P.DecisionClock(_utc("16:16"))
    port = P.LocalCandlePort(stream, clock)
    rows = port.fetch_1m_candles("MNQ", lookback_bars=5)
    assert [r["timestamp"][11:16] for r in rows] == ["16:11", "16:12", "16:13", "16:14", "16:15"]
    with pytest.raises(C.ContractError) as exc:
        port.fetch_1m_candles("ES")
    assert exc.value.code == "SYMBOL_MISMATCH"


def test_local_quote_port_never_invents_or_borrows_a_quote():
    clock = P.DecisionClock(_utc("16:39"))
    quotes = [{"captured_at_utc": "2026-08-19T16:40:00Z", "contract_id": CONTRACT, "bid": 29513.5, "ask": 29513.75}]
    port = P.LocalQuotePort(quotes, clock, contract_id=CONTRACT, origin="CONSTRUCTED")
    assert port.capture() == P.MissingQuote("no_quote_available_by_decision_time")
    clock.set(_utc("16:40", 1))
    capture = port.capture()
    assert (capture.best_bid, capture.best_ask, capture.contract_id) == (29513.5, 29513.75, CONTRACT)
    assert capture.market_data_age_seconds == 1.0
    foreign = P.LocalQuotePort([{**quotes[0], "contract_id": "OTHER"}], clock, contract_id=CONTRACT,
                               origin="CONSTRUCTED")
    assert foreign.capture() == P.MissingQuote("quote_contract_mismatch")
    with pytest.raises(C.ContractError):
        P.LocalQuotePort(quotes, clock, contract_id=CONTRACT, origin="CANDLE_CLOSE")


def test_network_guard_refuses_and_records_every_attempt():
    originals = (socket.socket.connect, socket.create_connection, socket.getaddrinfo)
    guard = P.NetworkGuard()
    with guard.deny():
        with pytest.raises(P.NetworkRefused):
            socket.create_connection(("example.invalid", 443), timeout=1)
        with pytest.raises(P.NetworkRefused):
            socket.getaddrinfo("example.invalid", 443)
        sock = socket.socket()
        try:
            with pytest.raises(P.NetworkRefused):
                sock.connect(("127.0.0.1", 9))
        finally:
            sock.close()
    assert [kind for kind, _ in guard.attempts] == ["create_connection", "getaddrinfo", "connect"]
    assert (socket.socket.connect, socket.create_connection, socket.getaddrinfo) == originals


def test_refusing_venue_records_and_raises_on_every_write():
    venue = P.RefusingVenueSession()
    assert venue.open_positions() == [] and venue.open_orders() == [] and venue.recent_trades() == []
    for call in (lambda: venue.place_order({"size": 1}), lambda: venue.cancel_order(1),
                 lambda: venue.modify_order(1, size=2), lambda: venue.close_position(CONTRACT)):
        with pytest.raises(P.VenueWriteRefused):
            call()
    assert [name for name, _ in venue.writes] == ["place_order", "cancel_order", "modify_order", "close_position"]


def test_repository_fixture_inventory_binds_checkout_bytes_and_reconciles_the_contract_evidence():
    """The contract's REPOSITORY_FIXTURE_INVENTORY digests (9019/2853 bytes)
    are the CRLF rendition of these LF blobs; the inventory binds the bytes
    actually present and the reconciliation is exact, not assumed."""
    rows = {row["path"]: row for row in K.repository_fixture_inventory(ROOT)}
    contract = {"tests/fixtures/mnq_20260811_1420Z_1510Z_1m.json":
                ("ca9d022e51c7f9b7ab8619ce2271bb86399596a2328170ad69da57bd3b082c04", 9019),
                "tests/fixtures/prod20260811_103207_protected_swings.json":
                ("4b9dab659aab7185e88253bc9e9bbc3753a3d70222dc9336e702c497af64a3e4", 2853)}
    for path, (crlf_digest, crlf_bytes) in contract.items():
        data = (ROOT / path).read_bytes()
        assert rows[path]["sha256"] == C.sha256_hex(data) and rows[path]["bytes"] == len(data)
        lf = data.replace(b"\r\n", b"\n")
        crlf = lf.replace(b"\n", b"\r\n")
        assert (C.sha256_hex(crlf), len(crlf)) == (crlf_digest, crlf_bytes)
    assert all(row["classification"] == K.REPOSITORY_FIXTURE_CLASSIFICATION for row in rows.values())
