"""READ-ONLY. WHY does the `catalogs` wake dimension change on 92% of scans?

    python tools/catalogs_churn_audit.py --day 20260922

PROD-20260922 ran 589 scans in ENFORCE and held 38. `catalogs` changed on 540
of them -- 91.7% -- while every other dimension was intermittent. A dimension
that almost never fails to change is close to no gate at all, so the owner
approved ONE bounded read-only measurement to establish whether that is
genuine semantic change or representation churn.

THIS TOOL DECIDES NOTHING AND CHANGES NOTHING. It places no order, contacts no
venue, writes no file and alters no suppression logic. It reads the brain-call
archive that `narrative_brain` already wrote (`input_payload` carries the whole
`brain_input`, catalogs included) and diffs consecutive scans.

IT MEASURES WHAT THE GATE ACTUALLY HASHES. `_catalog_view` and the three key
tuples are IMPORTED from `wake_controller` rather than reimplemented here. A
measurement of a lookalike projection would answer a question nobody asked.

TWO OF THE CANDIDATE CAUSES ARE ALREADY IMPOSSIBLE, by construction rather
than by evidence:

    ordering churn        `_catalog_view` sorts rows by canonical JSON, so a
                          reordered catalog hashes identically.
    serialization-only    `_pick` keeps ONLY the named keys, so any field
                          outside the tuples cannot reach the fingerprint.

So a change here is always one of: set membership moved, or a picked key's
VALUE moved. This tool reports which, and for value movement it names the
field -- because "price moved" and "a timestamp was restamped" are the same
number of changed dimensions and completely different facts.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from ai_brain.wake_controller import (  # noqa: E402
    _INVALIDATION_KEYS, _OBJECTIVE_KEYS, _TOOL_KEYS, _catalog_view,
)

ARCHIVE = os.path.join("data", "ai_brain")

CATALOGS = (
    ("tools", "authorized_tool_catalog", _TOOL_KEYS),
    ("objectives", "authorized_objectives", _OBJECTIVE_KEYS),
    ("invalidations", "authorized_invalidations", _INVALIDATION_KEYS),
)

#: The id field each catalog is keyed by, for membership accounting.
ID_KEY = {"tools": ("occurrence_id", "tool_id"),
          "objectives": ("objective_id",),
          "invalidations": ("invalidation_id",)}


def _identity(row: dict, names) -> str:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return f"{name}={value}"
    # An unkeyed row is its own identity. Do not silently merge two rows that
    # the catalog itself did not distinguish.
    return "unkeyed:" + json.dumps(row, sort_keys=True, separators=(",", ":"),
                                   default=str)


def _views(payload: dict) -> dict:
    return {name: _catalog_view(payload.get(key), keys)
            for name, key, keys in CATALOGS}


def _canonical(value) -> str:
    """Exactly how `semantic_fingerprint` renders a value.

    The gate hashes `json.dumps(projection, sort_keys=True, ...)`, so the
    fingerprint's notion of "different" is SERIALIZED difference, not Python
    equality. Those disagree: `30900.0 == 30900` is True, while the rendered
    forms "30900.0" and "30900" are two different strings and therefore two
    different hashes.

    Comparing with `==` here would have quietly under-reported precisely the
    representation churn this audit exists to find -- the gate would wake and
    the measurement would say nothing moved.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      default=str)


def _float_only(before, after) -> bool:
    """The same number wearing a different representation."""
    try:
        if isinstance(before, bool) or isinstance(after, bool):
            return False
        return float(before) == float(after)
    except (TypeError, ValueError):
        return False


def _diff_catalog(name: str, before: list, after: list, report: dict) -> bool:
    if _canonical(before) == _canonical(after):
        return False
    names = ID_KEY[name]
    old = {_identity(r, names): r for r in before}
    new = {_identity(r, names): r for r in after}

    added, removed = set(new) - set(old), set(old) - set(new)
    if added or removed:
        report["membership"][name] += 1
        report["members_added"][name] += len(added)
        report["members_removed"][name] += len(removed)

    value_moved = False
    for ident in set(old) & set(new):
        for field in sorted(set(old[ident]) | set(new[ident])):
            a, b = old[ident].get(field), new[ident].get(field)
            if _canonical(a) == _canonical(b):
                continue
            value_moved = True
            report["fields"][f"{name}.{field}"] += 1
            if _float_only(a, b):
                report["float_only"][f"{name}.{field}"] += 1
            if len(report["examples"][f"{name}.{field}"]) < 3:
                report["examples"][f"{name}.{field}"].append(
                    f"{ident}: {a!r} -> {b!r}")
    if value_moved:
        report["value_movement"][name] += 1
    return True


def audit(paths: list) -> dict:
    report = {
        "files": len(paths), "unreadable": 0, "pairs": 0,
        "catalogs_changed": 0, "unchanged": 0,
        "changed_catalog": collections.Counter(),
        "membership": collections.Counter(),
        "members_added": collections.Counter(),
        "members_removed": collections.Counter(),
        "value_movement": collections.Counter(),
        "fields": collections.Counter(),
        "float_only": collections.Counter(),
        "examples": collections.defaultdict(list),
        "sizes": collections.defaultdict(collections.Counter),
    }
    previous = None
    for path in paths:
        try:
            with open(path, encoding="utf-8") as fh:
                payload = (json.load(fh) or {}).get("input_payload") or {}
        except Exception:  # noqa: BLE001 -- an unreadable row is a fact
            report["unreadable"] += 1
            continue
        current = _views(payload)
        for name in current:
            report["sizes"][name][len(current[name])] += 1
        if previous is not None:
            report["pairs"] += 1
            changed = False
            for name in current:
                if _diff_catalog(name, previous[name], current[name], report):
                    report["changed_catalog"][name] += 1
                    changed = True
            report["catalogs_changed" if changed else "unchanged"] += 1
        previous = current
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", required=True, help="yyyymmdd")
    ap.add_argument("--archive", default=ARCHIVE)
    ap.add_argument("--instrument", default="MNQ")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    paths = sorted(glob.glob(os.path.join(
        args.archive, f"{args.day}_*_{args.instrument}.json")))
    if not paths:
        print(f"no archived brain calls matching "
              f"{args.day}_*_{args.instrument}.json in {args.archive}")
        return 2

    report = audit(paths)
    if args.json:
        report["examples"] = dict(report["examples"])
        report["sizes"] = {k: dict(v) for k, v in report["sizes"].items()}
        print(json.dumps(report, indent=2, default=str))
        return 0

    pairs = report["pairs"] or 1
    print(f"\nCATALOGS CHURN AUDIT -- {args.day} {args.instrument}")
    print("READ-ONLY. Measures exactly what the wake gate hashes.\n")
    print(f"  archived brain calls        : {report['files']} "
          f"({report['unreadable']} unreadable)")
    print(f"  consecutive pairs compared  : {report['pairs']}")
    print(f"  pairs where catalogs CHANGED: {report['catalogs_changed']} "
          f"({100.0 * report['catalogs_changed'] / pairs:.1f}%)")
    print(f"  pairs where it held still   : {report['unchanged']}")

    print("\n-- WHICH CATALOG MOVED --------------------------------------")
    for name, _key, _keys in CATALOGS:
        print(f"  {name:<14} changed {report['changed_catalog'][name]:>5}   "
              f"membership {report['membership'][name]:>5}   "
              f"value-only {report['value_movement'][name]:>5}")
        sizes = report["sizes"][name]
        if sizes:
            print(f"                 rows per scan: "
                  f"{min(sizes)}-{max(sizes)}")

    print("\n-- MEMBERSHIP (genuine set changes) -------------------------")
    total_member = sum(report["membership"].values())
    if not total_member:
        print("  none. The SAME rows were offered every scan; nothing entered")
        print("  or left either catalog.")
    for name in sorted(report["membership"]):
        print(f"  {name:<14} +{report['members_added'][name]} "
              f"-{report['members_removed'][name]} "
              f"across {report['membership'][name]} pair(s)")

    print("\n-- WHICH FIELD MOVED (the question) -------------------------")
    if not report["fields"]:
        print("  no value movement on any picked key.")
    for field, n in report["fields"].most_common(args.top):
        floats = report["float_only"][field]
        mark = f"   [{floats} float-repr-only]" if floats else ""
        print(f"  {field:<44} {n:>5}  ({100.0 * n / pairs:.1f}% of pairs){mark}")
        for example in report["examples"][field][:2]:
            print(f"        e.g. {example[:110]}")

    print("\n-- WHAT THIS DOES AND DOES NOT ESTABLISH --------------------")
    print("  ESTABLISHED: which catalog and which FIELD moved between scans,")
    print("  measured on the exact projection the gate fingerprints.")
    print("  ORDERING and SERIALIZATION churn are excluded BY CONSTRUCTION:")
    print("  `_catalog_view` sorts rows and picks only the named keys, so")
    print("  neither can reach the fingerprint. They are not measured here")
    print("  because they cannot occur.")
    print("  NOT ESTABLISHED: whether a field that moved SHOULD wake the")
    print("  Brain. That is a doctrine question about each field, not a")
    print("  property of the record.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
