"""READ-ONLY OVER THE JOURNAL. Reclassify COPIES, and show before vs after.

PROD-20260908. `session_phase_blocks_entry` now maps to STOOD_DOWN. The
question that mapping raises is what ALREADY-WRITTEN evidence would say under
it, and there are exactly two honest ways to answer:

    rewrite the journal          NO. A decision ledger is contemporaneous
                                 evidence. Editing it to agree with today's
                                 classifier destroys the only record of what
                                 the classifier said AT THE TIME, and makes
                                 every future audit unfalsifiable.

    reclassify a COPY            YES. The original file is opened "r" and
                                 never written. The recomputed records go to
                                 a NEW path, and both reconciliations are
                                 printed side by side so the change is
                                 visible rather than asserted.

`final_rejection_reason`, `detail`, and every trace field are carried through
UNCHANGED. Only `final_disposition` is recomputed, and only by
`candidate_decision_record.terminal_disposition` -- the same function the live
path calls. No second classifier is written here.

The record's own `final_disposition` is preserved alongside as
`original_final_disposition`, so a copy can never be mistaken for the journal.

    python tools/topstepx_reclassify_decision_audit.py --session PROD-20260908
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from broker.candidate_decision_record import (CANDIDATE_CREATED,  # noqa: E402
                                              reconcile,
                                              terminal_disposition)


def load_journal(path: str) -> list:
    """Opened 'r'. This module has no code path that writes to it."""
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def reclassify(rows: list) -> list:
    """A COPY of each record with `final_disposition` recomputed.

    `created` is taken from the record's OWN original disposition, never
    re-derived: whether a candidate was born is a fact the live path already
    established, and re-deciding it here from a reason string would be a second
    classifier by the back door.
    """
    out = []
    for row in rows:
        original = row.get("final_disposition")
        copy = dict(row)
        copy["original_final_disposition"] = original
        copy["final_disposition"] = terminal_disposition(
            row.get("final_rejection_reason"),
            created=(original == CANDIDATE_CREATED))
        out.append(copy)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--out", default="",
                    help="where the reclassified COPY is written; defaults "
                         "beside the journal with a .reclassified suffix")
    args = ap.parse_args()

    from ai_retrieval.retrieval_telemetry import session_root
    root = session_root(args.session)
    journal = os.path.join(root, "candidate_decisions.jsonl")
    if not os.path.exists(journal):
        print(f"REFUSED: no decision journal at {journal}")
        return 2

    before_bytes = os.path.getsize(journal)
    rows = load_journal(journal)
    copies = reclassify(rows)

    before = reconcile(rows)
    after = reconcile(copies)

    out_path = args.out or os.path.join(
        root, f"candidate_decisions.reclassified_{args.session}.jsonl")
    if os.path.abspath(out_path) == os.path.abspath(journal):
        print("REFUSED: the audit copy may not be written over the journal.")
        return 3
    with open(out_path, "w", encoding="utf-8") as fh:
        for row in copies:
            fh.write(json.dumps(row, default=str) + "\n")

    print(f"DECISION RECLASSIFICATION AUDIT -- {args.session}")
    print(f"  journal (unchanged) : {journal}")
    print(f"  audit copy written  : {out_path}")
    print(f"  records read        : {len(rows)}")
    print(f"  records written     : {len(copies)}")
    print("\n  BEFORE (as recorded at decision time)")
    print(f"    {json.dumps(before, default=str)}")
    print("\n  AFTER (same records, current classifier)")
    print(f"    {json.dumps(after, default=str)}")

    moved = collections.Counter(
        (c["original_final_disposition"], c["final_disposition"])
        for c in copies if c["original_final_disposition"] != c["final_disposition"])
    print("\n  RECLASSIFIED")
    if not moved:
        print("    nothing moved; the classifier already agreed with the journal")
    for (was, now), n in moved.most_common():
        print(f"    {n:>5}  {was} -> {now}")

    reasons = collections.Counter(
        str(c.get("final_rejection_reason") or "") for c in copies)
    print("\n  REASONS PRESERVED (unchanged in the copy)")
    for reason, n in reasons.most_common():
        print(f"    {n:>5}  {reason or '(none)'}")

    # THE TOTAL IS THE INVARIANT. A reclassification that changes how many
    # decisions there were is not a reclassification.
    ok = before["terra_proposals"] == after["terra_proposals"] == len(rows)
    print(f"\n  TOTAL PRESERVED     : {ok} "
          f"({before['terra_proposals']} -> {after['terra_proposals']})")
    unchanged = os.path.getsize(journal) == before_bytes
    print(f"  JOURNAL BYTES       : {before_bytes} before, "
          f"{os.path.getsize(journal)} after (unchanged={unchanged})")
    return 0 if (ok and unchanged) else 4


if __name__ == "__main__":
    raise SystemExit(main())
