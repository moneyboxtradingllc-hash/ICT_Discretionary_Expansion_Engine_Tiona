"""TOPSTEPX-V2-QUERY-WIRE-CONTRACT-1.

CANONICAL DISCOVERY HAD NEVER SUCCEEDED AGAINST THE REAL VENUE.

`TopstepXClient.query_orders` posted the filter fields at the request ROOT:

    {"accountId": N, "contractId": "..."}
    -> HTTP 400  "SearchOrdersQueryRequest was missing required properties
                  including: 'filter'"

So every live call raised, fell back to `searchOpen`, and was labelled
INCOMPLETE. The Suspended-child repair was inert in production, and once the
completeness law landed, emergency convergence would have refused to act at all
on a live account.

NO FIXTURE COULD HAVE CAUGHT IT. Every fixture in the suite implements
`query_orders` and returns rows. The contract was wrong at the wire, not in the
logic -- which is why the live read-only proof in this unit is load-bearing and
the mocked tests alone are not.

TWO MEASURED TRAPS, both of which look like success:

    pageOffset IS A ROW OFFSET, NOT A PAGE INDEX. With pageSize=5, offset 1
    returns rows[1:6], not rows[5:10]. Advancing it per-page would re-read
    almost the same window forever while appearing to make progress.

    THE VENUE CAPS A RESPONSE AT 100 ROWS. The live Combine held 193. A
    first-page read is a partial view -- the exact thing this endpoint exists
    to stop being consumed as complete truth.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from broker.topstepx_client import TopstepXClient, TopstepXError   # noqa: E402

ACCT = 22222222
MNQ = "CON.F.US.MNQ.U26"


def _venue_configured() -> bool:
    """Credentials come from `.env`, which production loads at import time --
    but this predicate is evaluated at COLLECTION, before that happens. Reading
    the file the way the lane itself does is what stops the one test that can
    certify the WIRE from silently skipping."""
    cfg = _venue_config()
    return bool(cfg.get("TOPSTEPX_API_KEY") and cfg.get("TOPSTEPX_ACCOUNT_ID"))


def _venue_config() -> dict:
    """Credentials as the LANE resolves them: environment first, then `.env`.

    Neighbouring suites clear `TOPSTEPX_*` from `os.environ` for isolation, so
    `os.environ[...]` here fails depending on test ORDER -- the same
    harness-ordering class already recorded as debt. Reading the file the way
    production does makes the one test that can certify the WIRE independent of
    who ran before it.
    """
    out = {}
    try:
        from dotenv import dotenv_values, find_dotenv
        out.update({k: v for k, v in dotenv_values(find_dotenv(usecwd=True)).items()
                    if v})
    except Exception:                                   # noqa: BLE001
        pass
    out.update({k: v for k, v in os.environ.items()
                if k.startswith("TOPSTEPX_") and v})
    return out


def row(oid, *, status=1, contract=MNQ):
    return {"id": oid, "contractId": contract, "status": status, "type": 4,
            "side": 1, "size": 15}


class FakeVenue:
    """Records the exact body posted, and pages like the real Gateway."""

    def __init__(self, rows, *, page_cap=100, success=True, short_total=None):
        self.rows = list(rows)
        self.page_cap = page_cap
        self.success = success
        self.short_total = short_total
        self.bodies = []

    def post(self, path, payload):
        assert path == "/api/Order/v2/query", path
        self.bodies.append(payload)
        if not self.success:
            return {"success": False, "errorCode": 3,
                    "errorMessage": "refused", "orders": []}
        size = min(int(payload.get("pageSize") or 100), self.page_cap)
        off = int(payload.get("pageOffset") or 0)      # ROW offset
        page = self.rows[off:off + size]
        total = self.short_total if self.short_total is not None else len(self.rows)
        return {"success": True, "errorCode": 0, "errorMessage": None,
                "orders": page, "totalCount": total}


def client(venue):
    c = TopstepXClient.__new__(TopstepXClient)
    c._post = venue.post
    return c


# ══ W1-W5  THE BODY SHAPE ═══════════════════════════════════════════════════
class TestWireShape:

    def test_W1_the_root_carries_filter(self):
        v = FakeVenue([row(1)])
        client(v).query_orders(ACCT)
        assert "filter" in v.bodies[0]

    def test_W2_accountId_is_nested_under_filter(self):
        v = FakeVenue([row(1)])
        client(v).query_orders(ACCT)
        body = v.bodies[0]
        assert body["filter"]["accountId"] == ACCT
        assert "accountId" not in body, "the root shape is what HTTP 400'd"

    def test_W3_contractId_is_nested_under_filter(self):
        v = FakeVenue([row(1)])
        client(v).query_orders(ACCT, contract_id=MNQ)
        body = v.bodies[0]
        assert body["filter"]["contractId"] == MNQ
        assert "contractId" not in body

    def test_W4_statuses_are_nested_when_explicitly_requested(self):
        v = FakeVenue([row(1)])
        client(v).query_orders(ACCT, statuses=[1, 6])
        assert v.bodies[0]["filter"]["statuses"] == [1, 6]

    def test_W5_statuses_are_omitted_entirely_when_none(self):
        """SAFETY DISCOVERY IS STATUS-UNFILTERED. A filter added merely to make
        the live call work would let the venue hide a state our enum has not
        heard of."""
        v = FakeVenue([row(1)])
        client(v).query_orders(ACCT)
        assert "statuses" not in v.bodies[0]["filter"]

    def test_no_request_wrapper_is_added(self):
        """The endpoint PARAMETER is named `request`; the BODY is the
        SearchOrdersQueryRequest itself."""
        v = FakeVenue([row(1)])
        client(v).query_orders(ACCT)
        assert "request" not in v.bodies[0]

    def test_W6_an_unknown_future_status_survives_the_round_trip(self):
        v = FakeVenue([row(1, status=99)])
        got = client(v).query_orders(ACCT)
        assert got[0]["status"] == 99
        assert got[0]["status_name"] == "UNRECOGNISED"


# ══ W7-W8  PAGINATION ═══════════════════════════════════════════════════════
class TestPagination:

    def test_W7_a_first_page_cannot_stand_for_the_whole_book(self):
        """193 rows behind a 100-row cap: the live shape exactly."""
        v = FakeVenue([row(i) for i in range(193)])
        got = client(v).query_orders(ACCT)
        assert len(got) == 193
        assert len(v.bodies) > 1, "one round trip cannot have seen 193 of them"

    def test_W8_pageOffset_is_advanced_by_ROWS_not_by_pages(self):
        """THE TRAP. Advancing by page index re-reads almost the same window
        forever while looking like progress."""
        v = FakeVenue([row(i) for i in range(250)], page_cap=100)
        got = client(v).query_orders(ACCT)
        assert [o["id"] for o in got] == list(range(250)), "rows lost or repeated"
        offsets = [b["pageOffset"] for b in v.bodies]
        assert offsets == [0, 100, 200], offsets

    def test_every_page_is_merged_without_losing_identity(self):
        v = FakeVenue([row(i) for i in range(193)])
        ids = [o["id"] for o in client(v).query_orders(ACCT)]
        assert len(set(ids)) == 193

    def test_a_short_read_against_totalCount_fails_closed(self):
        """A confident-looking prefix is the partial view this endpoint
        replaces."""
        v = FakeVenue([row(i) for i in range(50)], short_total=193)
        with pytest.raises(TopstepXError, match="cannot be proven complete"):
            client(v).query_orders(ACCT)

    def test_a_non_terminating_venue_is_bounded_and_fails_closed(self):
        class Loop(FakeVenue):
            def post(self, path, payload):
                self.bodies.append(payload)
                return {"success": True, "orders": [row(1)] * 500,
                        "totalCount": 10 ** 9}
        with pytest.raises(TopstepXError, match="did not terminate"):
            client(Loop([])).query_orders(ACCT)


# ══ W9-W11  FAIL CLOSED ═════════════════════════════════════════════════════
class TestFailClosed:

    def test_W9_an_http_error_propagates_and_never_returns_a_partial_list(self):
        class Boom(FakeVenue):
            def post(self, path, payload):
                raise TopstepXError("HTTP 400 ...")
        with pytest.raises(TopstepXError):
            client(Boom([])).query_orders(ACCT)

    def test_W9_discovery_degrades_to_INCOMPLETE_when_the_query_raises(self):
        from broker import topstepx_order_discovery as DISC

        class Session:
            def query_orders(self, **kw):
                raise TopstepXError("HTTP 400")

            def open_orders(self):
                return []
        found = DISC.discover_orders(Session())
        assert found["complete"] is False
        assert found["source"] == DISC.INCOMPLETE

    def test_W10_a_refusal_envelope_is_not_an_empty_book(self):
        v = FakeVenue([row(1)], success=False)
        with pytest.raises(TopstepXError, match="refused"):
            client(v).query_orders(ACCT)

    def test_W11_the_searchOpen_fallback_remains_INCOMPLETE(self):
        from broker import topstepx_order_discovery as DISC

        class Legacy:
            query_orders = None

            def open_orders(self):
                return [row(1)]
        found = DISC.discover_orders(Legacy())
        assert found["answered"] is True and found["complete"] is False


# ══ W12-W13  THE SEMANTICS THIS UNIT MUST NOT CHANGE ════════════════════════
class TestCertifiedSemanticsPreserved:

    def test_W12_a_suspended_child_arrives_through_the_valid_path(self):
        v = FakeVenue([row(7, status=8)])
        got = client(v).query_orders(ACCT, contract_id=MNQ)
        assert got[0]["status"] == 8 and got[0]["status_name"] == "Suspended"

    def test_contract_scoping_is_applied_client_side(self):
        """MEASURED: the server returns the same totalCount with and without
        `contractId`, so the client-side filter is the one that scopes."""
        v = FakeVenue([row(1), row(2, contract="CON.F.US.ES.U26")])
        got = client(v).query_orders(ACCT, contract_id=MNQ)
        assert [o["id"] for o in got] == [1]

    def test_W13_the_incomplete_discovery_halt_is_untouched(self):
        from broker import topstepx_emergency_liquidation as EL
        d = EL.plan(position_size=15, orders=[], owns=lambda o: False,
                    discovery_complete=False)
        assert d["action"] == EL.ACTION_HALT
        assert d["reason"] == EL.DISCOVERY_INCOMPLETE


# ══ W14  LIVE READ-ONLY PROOF ═══════════════════════════════════════════════
class TestLiveVenueContract:
    """FIXTURES CANNOT CERTIFY A WIRE CONTRACT. This unit exists because 8,070
    mocked tests reported discovery working while the venue rejected every
    request. Skipped without credentials; run by the operator's machine."""

    @pytest.mark.skipif(not _venue_configured(),
                        reason="no venue credentials configured")
    def test_W14_the_live_account_answers_and_paginates_completely(self):
        import data_feed                                    # noqa: F401
        from broker import topstepx_order_discovery as DISC
        from broker.topstepx_readonly import TopstepXReadOnlySession

        cfg = _venue_config()
        s = TopstepXReadOnlySession(cfg["TOPSTEPX_USERNAME"],
                                    cfg["TOPSTEPX_API_KEY"])
        s.authenticate()
        s.pin(account_id=cfg["TOPSTEPX_ACCOUNT_ID"],
              expected_fingerprint=cfg["TOPSTEPX_ACCOUNT_FINGERPRINT"])
        contract = s.resolve_contract(cfg.get("TOPSTEPX_CONTRACT") or "MNQ")

        found = DISC.discover_orders(s, contract_id=contract.id)
        assert found["answered"] is True
        assert found["complete"] is True, found["errors"]
        assert found["source"] == DISC.COMPLETE
        # READ-ONLY. The session has no write surface at all.
        assert s.zero_write_proof()["write_calls_made"] == 0
