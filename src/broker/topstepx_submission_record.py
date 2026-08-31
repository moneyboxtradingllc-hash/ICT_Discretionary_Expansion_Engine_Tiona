"""The production submission flight recorder, and the venue-reachability truth.

PROD-20260810. A legitimate bullish candidate was sized to 3 MNQ, minted a
correct production token, and reached Topstep. The venue refused it. The runner
asked the venue for open orders and positions, found neither, and halted -- and
the reason Topstep gave died inside an in-memory `Transition`. By the time the
process was stopped, the single most important fact of the day was gone:

    order 3385801549 · status REJECTED · fillVolume 0 · reason UNKNOWN FOREVER

Worse, the mission recorded `order_id: None`, because `place_order` raised
BEFORE `self.order_id = result["order_id"]` ever ran. So the local record said
the venue had never seen anything, while the venue held the order. Any check
reading `mission.order_id is not None` would have concluded NEVER_REACHED_VENUE
about an order Topstep had already rejected.

Two separate failures, one root: the local record was allowed to be the
authority on what the venue saw.

This module fixes both.

    DURABILITY   The outgoing payload is persisted BEFORE the socket opens, and
                 the venue's answer is persisted the instant it arrives --
                 ahead of any parsing that could throw it away. A rejection now
                 survives a crash and is readable after restart.

    REACHABILITY `never_reached_venue` becomes a claim that must be EARNED. The
                 absence of evidence is not evidence of absence: if no
                 submission ledger was consulted, or a submission started and
                 its outcome is uncertain, the answer is False. Only positive
                 proof that no request was ever sent returns True.

The vocabulary is deliberately larger than it used to be, because these are
four different facts and the old code conflated them:

    an attempt happened  !=  the venue saw the request
    the venue saw it     !=  an order was accepted
    an order existed     !=  a trade occurred
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import uuid

SUBMISSION_SCHEMA = "production_submission.v1"

# ── the submission lifecycle ──────────────────────────────────────────────────
#: No request was ever constructed for this mission.
NOT_SUBMITTED = "NOT_SUBMITTED"
#: A payload was persisted and the socket is about to open, or did open. From
#: this point the venue MAY have seen the request, whatever happens next.
SUBMISSION_STARTED = "SUBMISSION_STARTED"
#: The venue returned an order id and accepted it.
VENUE_ACKNOWLEDGED = "VENUE_ACKNOWLEDGED"
#: The venue positively refused it. Terminal, and provably zero-fill when the
#: fill evidence says so.
VENUE_REJECTED = "VENUE_REJECTED"
#: Transport failed, timed out, or the answer was unreadable. NOT a synonym for
#: "did not arrive" -- an order can fill perfectly while the response is lost.
SUBMISSION_UNKNOWN = "SUBMISSION_UNKNOWN"
PARTIALLY_FILLED = "PARTIALLY_FILLED"
FILLED = "FILLED"

#: Any of these mean the venue may have, or definitely did, see the request.
#: `never_reached_venue` can never return True while one of them is on record.
VENUE_MAY_HAVE_SEEN = frozenset({
    SUBMISSION_STARTED, VENUE_ACKNOWLEDGED, VENUE_REJECTED,
    SUBMISSION_UNKNOWN, PARTIALLY_FILLED, FILLED,
})

#: Only these prove a trade actually happened. A rejection is not one of them.
FILL_STATES = frozenset({PARTIALLY_FILLED, FILLED})


class SubmissionRecordError(RuntimeError):
    """The durable submission record could not be established."""


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def ledger_path(store_dir: str, session_id: str) -> str:
    return os.path.join(store_dir, f"submissions_{session_id}.jsonl")


def new_submission_id() -> str:
    return f"sub-{uuid.uuid4().hex[:12]}"


def payload_digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def sanitize(payload: dict) -> dict:
    """The outgoing body with the raw account id removed.

    Everything else is kept verbatim: the point of the record is to show what
    was actually sent, and a redacted bracket would defeat it.
    """
    out = dict(payload or {})
    if "accountId" in out:
        out["accountId"] = f"...{str(out['accountId'])[-4:]}"
    return out


def _append(path: str, record: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


# ── before the socket opens ───────────────────────────────────────────────────
def open_submission(*, store_dir: str, session_id: str, mission_id: str,
                    payload: dict, custom_tag: str, token_id: str = "",
                    authorization_fingerprint: str = "",
                    account_fingerprint: str = "", contract_id: str = "",
                    symbol: str = "", geometry: dict = None,
                    submission_id: str = None) -> dict:
    """Persist SUBMISSION_STARTED and PROVE it landed, before any transport.

    Deliberately mirrors `MissionState.consume_attempt`: it re-reads the ledger
    and refuses to let the caller proceed if the record is not on disk. A
    submission that is only in memory has not been recorded, and the whole
    purpose of this file is that the next rejection cannot be mysterious.

    Raises rather than returning a failure code -- a caller that cannot record
    what it is about to send must not send it.
    """
    submission_id = submission_id or new_submission_id()
    sanitized = sanitize(payload)
    record = {
        "schema_version": SUBMISSION_SCHEMA,
        "submission_id": submission_id,
        "state": SUBMISSION_STARTED,
        "session_id": session_id,
        "mission_id": mission_id,
        "custom_tag": custom_tag,
        "token_id": token_id,
        "authorization_fingerprint": authorization_fingerprint,
        "account_fingerprint": account_fingerprint,
        "contract_id": contract_id or (payload or {}).get("contractId"),
        "symbol": symbol,
        "side": (payload or {}).get("side"),
        "quantity": (payload or {}).get("size"),
        "order_type": (payload or {}).get("type"),
        "signed_stop_loss_ticks": ((payload or {}).get("stopLossBracket") or {}).get("ticks"),
        "signed_take_profit_ticks": ((payload or {}).get("takeProfitBracket") or {}).get("ticks"),
        "geometry": dict(geometry or {}),
        "sanitized_payload": sanitized,
        "payload_sha256": payload_digest(sanitized),
        "prepared_at_utc": _now(),
        # filled in by record_response
        "response_at_utc": None, "success": None, "venue_order_id": None,
        "error_code": None, "error_message": None, "raw_response": None,
        "transport_exception": None, "reconciliation": None,
    }
    path = ledger_path(store_dir, session_id)
    _append(path, record)

    verify = find_submission(store_dir, session_id, submission_id)
    if verify is None or verify.get("state") != SUBMISSION_STARTED:
        raise SubmissionRecordError(
            "could not verify SUBMISSION_STARTED on disk; refusing to transmit")
    return record


# ── the instant the venue answers ─────────────────────────────────────────────
def record_response(*, store_dir: str, session_id: str, submission: dict,
                    raw_response: dict = None, transport_exception: str = None,
                    state: str = None, reconciliation: dict = None) -> dict:
    """Persist the venue's answer verbatim, before anything can discard it.

    `raw_response` is written whole. Today's loss happened because the useful
    part was a substring of an exception message that nobody stored.
    """
    raw = dict(raw_response or {})
    order_id = raw.get("orderId", raw.get("order_id"))
    success = raw.get("success")
    if state is None:
        if transport_exception is not None and not raw:
            state = SUBMISSION_UNKNOWN
        elif success is False:
            state = VENUE_REJECTED
        elif order_id is not None and success is not False:
            state = VENUE_ACKNOWLEDGED
        else:
            state = SUBMISSION_UNKNOWN

    closed = dict(submission)
    closed.update({
        "state": state,
        "response_at_utc": _now(),
        "success": success,
        "venue_order_id": order_id,
        "error_code": raw.get("errorCode"),
        "error_message": raw.get("errorMessage"),
        "raw_response": raw or None,
        "transport_exception": transport_exception,
        "reconciliation": dict(reconciliation) if reconciliation else None,
    })
    _append(ledger_path(store_dir, session_id), closed)
    return closed


def record_reconciliation(*, store_dir: str, session_id: str, submission: dict,
                          state: str, reconciliation: dict) -> dict:
    """Later evidence about the same submission. Appended, never overwriting."""
    closed = dict(submission)
    closed.update({"state": state, "reconciliation": dict(reconciliation),
                   "response_at_utc": closed.get("response_at_utc") or _now(),
                   "reconciled_at_utc": _now()})
    _append(ledger_path(store_dir, session_id), closed)
    return closed


# ── reading it back ───────────────────────────────────────────────────────────
def load_submissions(store_dir: str, session_id: str, mission_id: str = None) -> list:
    """Every row in write order. A row is never rewritten, so the sequence of
    beliefs about a submission is itself evidence."""
    path = ledger_path(store_dir, session_id)
    rows = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    # A torn final line still proves a submission was recorded.
                    rows.append({"schema_version": SUBMISSION_SCHEMA,
                                 "state": SUBMISSION_UNKNOWN,
                                 "mission_id": mission_id,
                                 "unreadable_row": True})
                    continue
                if mission_id is None or row.get("mission_id") == mission_id:
                    rows.append(row)
    except OSError:
        return []
    return rows


def latest_by_submission(store_dir: str, session_id: str,
                         mission_id: str = None) -> dict:
    """The most recent row per submission_id."""
    out = {}
    for row in load_submissions(store_dir, session_id, mission_id):
        out[row.get("submission_id")] = row
    return out


def find_submission(store_dir: str, session_id: str, submission_id: str) -> dict:
    return latest_by_submission(store_dir, session_id).get(submission_id)


# ── what the ledger says about the venue ──────────────────────────────────────
def _identity_matches(row: dict, mission_id: str, token_id: str = "") -> bool:
    """Does this row belong to this mission?

    PROD-20260811-V13. The mission was `PROD-20260811-V13-T1`; the flight
    recorder stamped the SESSION-level `PROD-20260811-V13`; the file was named
    for the RETIRED `PROD-20260811`. Exact-match on one key found nothing, and
    nothing is what let a filled trade evaluate as "never reached the venue".

    So identity is joined on any of three keys, and a prefix relationship
    counts: a per-trade id extends its session id, it does not contradict it.
    The token id is the strongest join of the three -- it is minted per attempt
    and travels into the venue's own customTag.
    """
    row_mission = str(row.get("mission_id") or "")
    mine = str(mission_id or "")
    if token_id and str(row.get("token_id") or "") == str(token_id):
        return True
    if not row_mission or not mine:
        return False
    return (row_mission == mine
            or mine.startswith(row_mission + "-")
            or row_mission.startswith(mine + "-"))


def scan_all_ledgers(store_dir: str, mission_id: str, token_id: str = "") -> list:
    """Every row for this mission across EVERY ledger file in the store.

    Searching only `submissions_<session_id>.jsonl` assumes the writer and the
    reader agree about the session id. On V13 they did not, and the whole
    safety property rested on that assumption holding.
    """
    rows = []
    try:
        names = sorted(os.listdir(store_dir))
    except OSError:
        return rows
    for name in names:
        if not (name.startswith("submissions_") and name.endswith(".jsonl")):
            continue
        session = name[len("submissions_"):-len(".jsonl")]
        for row in load_submissions(store_dir, session, None):
            if _identity_matches(row, mission_id, token_id):
                rows.append(row)
    return rows


def mission_venue_evidence(store_dir: str, session_id: str, mission_id: str,
                           token_id: str = "") -> dict:
    """Summarize, for one mission, what the venue is known to have seen.

    ABSENCE OF MATCHING EVIDENCE IS NOT PROOF THE VENUE WAS NEVER REACHED.
    A search that returns nothing means the ledger cannot answer the question,
    so `venue_may_have_seen` is None -- neither True nor False -- and callers
    that need a negative must fail closed on it. Returning False there is what
    made order 3391019204, a real fill, look voidable.
    """
    by_id = {}
    for row in scan_all_ledgers(store_dir, mission_id, token_id):
        by_id[row.get("submission_id")] = row
    # The named session's own file is still consulted directly, so a store that
    # cannot be listed at all does not silently degrade to "no rows".
    for sub_id, row in latest_by_submission(store_dir, session_id, mission_id).items():
        by_id.setdefault(sub_id, row)
    rows = list(by_id.values())
    states = [r.get("state") for r in rows]
    order_ids = [r.get("venue_order_id") for r in rows if r.get("venue_order_id")]
    seen = (any(s in VENUE_MAY_HAVE_SEEN for s in states) or bool(order_ids))
    return {
        "ledger_consulted": True,
        "submission_count": len(rows),
        "states": states,
        "venue_order_ids": order_ids,
        # None == "the ledger has nothing to say about this mission"
        "venue_may_have_seen": (seen if rows else None),
        "evidence_absent": not rows,
        # HOW GOOD WAS THE QUESTION. An empty result only means something if
        # the search could have found a row that exists. `open_submission`
        # writes SUBMISSION_STARTED -- stamped with the token id -- BEFORE the
        # socket opens, so nothing anywhere under a token that was minted is
        # real proof transport never began. A mission-id-only search is weak:
        # that is exactly the search V13 ran, against an id one segment longer
        # than the one recorded, and its zero rows meant nothing at all.
        "search_key_strength": ("token" if token_id else "mission_id"),
        "searched": {"mission_id": mission_id, "token_id": token_id,
                     "session_id": session_id, "scope": "all ledger files"},
        "rejected": [r for r in rows if r.get("state") == VENUE_REJECTED],
        "fills": [r for r in rows if r.get("state") in FILL_STATES],
        "unknown": [r for r in rows if r.get("state") == SUBMISSION_UNKNOWN],
        "rows": rows,
    }


def zero_fill_rejection(evidence: dict, *, positions: int = None,
                        working_orders: int = None) -> tuple:
    """Is this a POSITIVELY CONFIRMED zero-fill venue rejection? (bool, why).

    Every condition must be affirmative. `positions`/`working_orders` are the
    venue's own counts at reconciliation time -- passing None means the venue
    was not asked, which is not the same as it answering zero, and is refused.
    """
    why = []
    rejected = (evidence or {}).get("rejected") or []
    if not rejected:
        why.append("no VENUE_REJECTED row on record")
    if (evidence or {}).get("fills"):
        why.append("a fill is on record")
    if (evidence or {}).get("unknown"):
        why.append("a submission outcome is still unknown")
    for row in rejected:
        raw = row.get("raw_response") or {}
        fill = raw.get("fillVolume", row.get("fill_volume"))
        if fill not in (0, None):
            why.append(f"venue reports fillVolume {fill}")
    if positions is None or working_orders is None:
        why.append("the venue was not asked for positions/working orders")
    else:
        if positions:
            why.append(f"{positions} open position(s)")
        if working_orders:
            why.append(f"{working_orders} working order(s)")
    return (not why), why
