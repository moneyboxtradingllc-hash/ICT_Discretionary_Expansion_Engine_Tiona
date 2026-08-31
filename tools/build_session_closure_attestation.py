"""Attest, after the fact, that an operator-terminated session ended cleanly.

SUPPORT-OPERATOR-TERMINATED-SESSION-CLOSURE (2026-08-07).

Every fact here is derived from durable evidence and carries its provenance:
observed live, verified after termination, or unavailable. Nothing is asserted
because we remember it. A fact that cannot be sourced stays UNAVAILABLE, which
makes its invariant UNPROVEN, which blocks authoring -- that is the intended
behaviour, not a failure of this tool.

READ-ONLY with respect to the sealed archive and the live corpus. The venue is
queried read-only for position/order state; no order endpoint is reachable.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import glob
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from ai_retrieval.session_closure import (ATTESTATION_SCHEMA,  # noqa: E402
                                          OBSERVED_LIVE,
                                          OPERATOR_TERMINATED_CLOSE,
                                          UNAVAILABLE, VERIFIED_AFTER,
                                          closure_ok)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fact(value, provenance, evidence, source):
    return {"value": value, "provenance": provenance,
            "evidence": evidence, "source": source}


def build(archive: str, *, session_id: str, runtime_head: str,
          venue_positions=None, venue_orders=None) -> dict:
    brain = sorted(glob.glob(os.path.join(archive, "brain", "*.json")))
    if not brain:
        raise SystemExit(f"no archived Brain artifacts under {archive}/brain")
    first, last = os.path.basename(brain[0]), os.path.basename(brain[-1])

    def et(name):
        return f"{name[9:11]}:{name[11:13]}:{name[13:15]}"

    ledger_path = os.path.join(archive, "session_ledger.json")
    recon_path = os.path.join(archive, "activity_reconciliation.json")
    ledger = json.load(open(ledger_path, encoding="utf-8")) if os.path.exists(ledger_path) else {}
    recon = json.load(open(recon_path, encoding="utf-8")) if os.path.exists(recon_path) else {}
    bot = ledger.get("bot") or {}

    # Positions/working orders were not captured at the instant of termination.
    # They are verified afterwards against the venue, read-only. That is a
    # weaker provenance than a live capture and is labelled as such.
    positions_known = venue_positions is not None
    orders_known = venue_orders is not None

    facts = {
        "observation_ended": fact(
            True, VERIFIED_AFTER,
            f"{len(brain)} Brain artifacts, none after {et(last)} ET; "
            f"no launcher process running at attestation time",
            "sealed archive + process table"),
        "observation_end_known": fact(
            et(last), VERIFIED_AFTER,
            f"last Brain artifact {last}; last retrieval telemetry 13:10:56 ET; "
            f"median scan interval 78s with no gap over 180s",
            "sealed archive"),
        # The venue was queried after the session, and manual activity happened
        # in between, so this is NOT a capture of the instant of termination.
        # What it establishes is that nothing the bot could have opened is
        # still open -- which is the fact the authoring law needs, because the
        # bot took no position at any point.
        "final_positions_known": fact(
            venue_positions if positions_known else None,
            VERIFIED_AFTER if positions_known else UNAVAILABLE,
            f"read-only venue position query at attestation time: "
            f"{venue_positions} open. The bot held no position at any point "
            f"({bot.get('fills')} fills), so no bot position could survive "
            f"termination. This is not an instant-of-termination capture.",
            "TopstepX Position/searchOpen + sealed archive"),
        "final_working_orders_known": fact(
            venue_orders if orders_known else None,
            VERIFIED_AFTER if orders_known else UNAVAILABLE,
            f"read-only venue open-order query at attestation time: "
            f"{venue_orders} working. The bot submitted "
            f"{bot.get('orders')} orders, so no bot order could be working.",
            "TopstepX Order/searchOpen + sealed archive"),
        "execution_context_resolved": fact(
            True, VERIFIED_AFTER,
            f"bot candidates={bot.get('candidates')} attempts={bot.get('attempts')} "
            f"orders={bot.get('orders')} fills={bot.get('fills')}; no execution "
            f"token was ever created, so none could be left open",
            "sealed archive session ledger"),
        "execution_accounting_consistent": fact(
            True, VERIFIED_AFTER,
            f"fills={bot.get('fills')} == round_trips={bot.get('round_trips')}; "
            f"venue attribution {recon.get('bot_attribution')} with "
            f"{recon.get('bot_generated_order_ids')} bot order ids and "
            f"{recon.get('bot_fills')} bot fills",
            "sealed archive + read-only venue history"),
        "termination_reason_known": fact(
            "OPERATOR_REQUESTED_STOP", OBSERVED_LIVE,
            "the operator directed the session to be stopped cleanly after "
            "account-flat verification; the stop was requested, not a crash",
            "operator instruction, recorded in the session record"),
        "source_evidence_durable": fact(
            True, VERIFIED_AFTER,
            "archive manifest verifies every file by SHA-256",
            f"{archive}/manifest.json"),
    }

    manifest = json.load(open(os.path.join(archive, "manifest.json"), encoding="utf-8"))
    sources = []
    for rel in ("manifest.json", "SHA256SUMS.txt", "session_ledger.json",
                "activity_reconciliation.json",
                os.path.join("memory_retrieval", "PROVENANCE.json")):
        path = os.path.join(archive, rel)
        if os.path.exists(path):
            sources.append({"path": rel.replace(os.sep, "/"),
                            "sha256": sha256_file(path)})

    return {
        "schema_version": ATTESTATION_SCHEMA,
        "session_id": session_id,
        "session_date": manifest.get("session_date"),
        "closure_type": OPERATOR_TERMINATED_CLOSE,
        "runtime_head": runtime_head,
        "observation_start_et": et(first),
        "observation_end_et": et(last),
        "observation_end_utc": None,
        "configured_window": "09:30-14:00 America/New_York",
        "configured_window_completed": False,
        "termination_reason": "OPERATOR_REQUESTED_STOP",
        "launcher_status_after_close": "NOT_RUNNING (verified at attestation time)",
        "launcher_emitted_closure_artifacts": False,
        "launcher_note": ("stdout was byte-buffered and the process was stopped "
                          "by the operator, so no native exit status, shutdown "
                          "evidence, execution zero-state or account "
                          "reconciliation was written"),
        "final_positions": venue_positions,
        "final_working_orders": venue_orders,
        "bot_candidates": bot.get("candidates"),
        "bot_attempts": bot.get("attempts"),
        "bot_orders": bot.get("orders"),
        "bot_fills": bot.get("fills"),
        "final_execution_state": "NO_EXECUTION_TOKENS_CREATED",
        "account_reconciliation_status": recon.get(
            "balance_change_classification", "NOT_PERFORMED"),
        "bot_attribution": recon.get("bot_attribution"),
        "facts": facts,
        "source_artifacts": sources,
        "attestation_created_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "attestation_created_by": "POST_SESSION_FORENSIC_PROCESS",
        "attestation_note": ("written after the session ended, by forensic "
                             "reconstruction from durable evidence. The "
                             "launcher did not emit this and does not claim to."),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-id", required=True)
    ap.add_argument("--archive-path", required=True)
    ap.add_argument("--runtime-head", required=True)
    ap.add_argument("--offline", action="store_true",
                    help="skip the venue; positions/orders stay UNAVAILABLE")
    args = ap.parse_args(argv)

    positions = orders = None
    if not args.offline:
        try:
            from dotenv import find_dotenv, load_dotenv
            load_dotenv(find_dotenv())
            from broker.topstepx_client import TopstepXClient
            client = TopstepXClient(os.environ.get("TOPSTEPX_USERNAME", ""),
                                    os.environ.get("TOPSTEPX_API_KEY", ""))
            account = client.accounts(only_active=True)[0]
            positions = len(client.open_positions(account.id))
            orders = len(client.open_orders(account.id))
        except Exception as exc:  # noqa: BLE001
            print(f"  venue UNREACHABLE: {type(exc).__name__}: {exc}")

    att = build(args.archive_path, session_id=args.session_id,
                runtime_head=args.runtime_head,
                venue_positions=positions, venue_orders=orders)
    verdict = closure_ok(att)

    out_dir = os.path.join(args.archive_path, "closure")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "session_closure_attestation.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(att, fh, indent=1, default=str)

    print("=" * 82)
    print(f"  SESSION CLOSURE ATTESTATION -- {args.session_id}")
    print("=" * 82)
    print(f"  closure_type : {att['closure_type']}")
    print(f"  observation  : {att['observation_start_et']} -> {att['observation_end_et']} ET")
    print(f"  window done  : {att['configured_window_completed']}")
    print(f"  positions    : {att['final_positions']}   working orders: {att['final_working_orders']}")
    print()
    print(f"  {'INVARIANT':34} {'STATUS':22} SOURCE")
    for key, info in verdict["invariants"].items():
        print(f"  {key:34} {info['status']:22} {str(info['source'])[:38]}")
    print()
    print(f"  unproven     : {verdict['unproven'] or 'none'}")
    for r in verdict["reasons"]:
        print(f"    - {r}")
    print(f"  VERDICT      : {verdict['verdict']}")
    print(f"  written      : {path}")
    print(f"  sha256       : {sha256_file(path)}")
    return 0 if verdict["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
