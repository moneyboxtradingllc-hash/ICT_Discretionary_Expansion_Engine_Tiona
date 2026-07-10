"""
ADAPT-LOOP-6 — Evolution Timeline (2026-07-10).

A living changelog of the ORGANISM's evolution, keyed to evidence rather than
prose. Design commitments (user-mandated):

  1. EVENT SCHEMA KEYED TO EVIDENCE: {date, mission, commit, change,
     metric_before, metric_after, evidence_ref, verdict}. verdict is one of
     validated | rejected | no_change | pending. A milestone WITHOUT an
     evidence_ref is forced to `pending` and renders that way, visibly — claims
     don't get badges, artifacts do.
  2. THREE CHEAP SOURCES: the git log (the one-line "PHASE - Title" commit
     discipline is the spine), the report artifacts in data/replay/reports/,
     and this curated docs/evolution/milestones.jsonl — one line appended at
     each mission's ship step (test → backup → commit → push → MILESTONE).
  3. VERDICTS CAN BE NEGATIVE: `rejected` and `no_change` entries render with
     the SAME prominence as wins. The stability repairs showing "no funnel
     change" are the credibility of the whole document.

Because repairs are flag-gated and replay is deterministic, milestones are
RE-MEASURABLE: re-run the same ablation over the grown archive and update
metric_after/evidence_ref — the changelog's evidence strengthens (or honestly
weakens) with n.

Store: docs/evolution/milestones.jsonl (committed). Render: docs/evolution/
TIMELINE.md. Descriptive only — nothing consumes this for authority.

CLI:
  python -m replay_validation.evolution_timeline add --date 20260710 \\
      --mission "REPLAY-4" --commit 48b1a79 --change "counterfactual lab" \\
      --before "council veto unproven" --after "veto validated (-2.0R alt)" \\
      --evidence data/replay/reports/lab_council_yes_....json --verdict validated
  python -m replay_validation.evolution_timeline render
"""
import json
import os
import subprocess
from datetime import datetime, timezone

VERDICTS = ("validated", "rejected", "no_change", "pending")
_BADGE = {"validated": "[VALIDATED]", "rejected": "[REJECTED]",
          "no_change": "[NO CHANGE]", "pending": "[PENDING]"}

MILESTONES_PATH = os.path.join("docs", "evolution", "milestones.jsonl")
TIMELINE_PATH = os.path.join("docs", "evolution", "TIMELINE.md")


def _path(base_dir=None):
    return os.path.join(base_dir, "milestones.jsonl") if base_dir \
        else MILESTONES_PATH


def normalize_milestone(m: dict) -> dict:
    """Enforce the schema. Unknown verdict -> ValueError; missing evidence_ref
    -> verdict forced to pending (claims don't get badges, artifacts do)."""
    out = {
        "date": str(m.get("date") or ""),
        "mission": str(m.get("mission") or ""),
        "commit": (str(m.get("commit")) if m.get("commit") else None),
        "change": str(m.get("change") or ""),
        "metric_before": m.get("metric_before"),
        "metric_after": m.get("metric_after"),
        "evidence_ref": m.get("evidence_ref"),
        "verdict": str(m.get("verdict") or "pending"),
        "recorded_at": m.get("recorded_at")
                       or datetime.now(timezone.utc).isoformat(),
    }
    if not out["date"] or not out["mission"]:
        raise ValueError("milestone needs date and mission")
    if out["verdict"] not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}")
    if not out["evidence_ref"] and out["verdict"] != "pending":
        out["verdict"] = "pending"
        out["forced_pending"] = "no evidence_ref — claims don't get badges"
    return out


def add_milestone(milestone: dict, base_dir=None) -> dict:
    m = normalize_milestone(milestone)
    path = _path(base_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(m, default=str) + "\n")
    return m


def load_milestones(base_dir=None) -> list:
    path = _path(base_dir)
    out = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return sorted(out, key=lambda m: (m.get("date", ""), m.get("recorded_at", "")))


def git_spine(limit: int = 200) -> list:
    """The timeline's spine: the one-line mission commits.
    [{hash, date, subject}] oldest-first. Empty on any git failure."""
    try:
        raw = subprocess.run(
            ["git", "log", f"-{limit}", "--format=%h|%as|%s", "--reverse"],
            capture_output=True, text=True, timeout=30).stdout
        out = []
        for line in raw.splitlines():
            parts = line.split("|", 2)
            if len(parts) == 3:
                out.append({"hash": parts[0], "date": parts[1],
                            "subject": parts[2]})
        return out
    except Exception:  # noqa: BLE001
        return []


def render_markdown(base_dir=None, out_path=None) -> str:
    """TIMELINE.md — milestone cards grouped by date, verdict badges equal in
    prominence, spine commits listed under each day."""
    milestones = load_milestones(base_dir)
    spine = git_spine()
    spine_by_date = {}
    for c in spine:
        spine_by_date.setdefault(c["date"], []).append(c)

    lines = [
        "# Organism Evolution Timeline",
        "",
        "_A living changelog keyed to evidence. Every badge links to a replay/",
        "lab/ablation artifact; a claim without an artifact renders as PENDING._",
        "_`REJECTED` and `NO CHANGE` entries are displayed with the same",
        "prominence as wins — they are the credibility of this document._",
        "",
        f"_Rendered {datetime.now(timezone.utc).isoformat()} — "
        f"{len(milestones)} milestones on a {len(spine)}-commit spine._",
        "",
    ]
    dates = sorted({m["date"] for m in milestones}
                   | {d for d in spine_by_date
                      if any(m["date"] == d for m in milestones)})
    for date in dates:
        pretty = f"{date[:4]}-{date[4:6]}-{date[6:8]}" if len(date) == 8 \
            and date.isdigit() else date
        lines.append(f"## {pretty}")
        lines.append("")
        for m in [x for x in milestones if x["date"] == date]:
            badge = _BADGE.get(m.get("verdict", "pending"), "[PENDING]")
            lines.append(f"### {badge} {m['mission']}")
            lines.append("")
            lines.append(f"- **Change:** {m['change']}")
            if m.get("metric_before") is not None or m.get("metric_after") is not None:
                lines.append(f"- **Measured:** {m.get('metric_before')} → "
                             f"{m.get('metric_after')}")
            if m.get("evidence_ref"):
                lines.append(f"- **Evidence:** `{m['evidence_ref']}`")
            else:
                lines.append("- **Evidence:** _none — pending until an artifact "
                             "exists_")
            if m.get("commit"):
                lines.append(f"- **Commit:** `{m['commit']}`")
            lines.append("")
        day_commits = spine_by_date.get(pretty) or spine_by_date.get(date) or []
        if day_commits:
            lines.append("<sub>spine: " + " · ".join(
                f"`{c['hash']}` {c['subject']}" for c in day_commits) + "</sub>")
            lines.append("")
    md = "\n".join(lines)
    path = out_path or (os.path.join(base_dir, "TIMELINE.md") if base_dir
                        else TIMELINE_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(md)
    return md


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Evolution Timeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    for f in ("date", "mission", "change"):
        a.add_argument(f"--{f}", required=True)
    a.add_argument("--commit")
    a.add_argument("--before")
    a.add_argument("--after")
    a.add_argument("--evidence")
    a.add_argument("--verdict", default="pending", choices=VERDICTS)
    sub.add_parser("render")
    args = p.parse_args()
    if args.cmd == "add":
        m = add_milestone({"date": args.date, "mission": args.mission,
                           "change": args.change, "commit": args.commit,
                           "metric_before": args.before,
                           "metric_after": args.after,
                           "evidence_ref": args.evidence,
                           "verdict": args.verdict})
        print(json.dumps(m, indent=1))
    else:
        render_markdown()
        print(f"rendered {TIMELINE_PATH}")
