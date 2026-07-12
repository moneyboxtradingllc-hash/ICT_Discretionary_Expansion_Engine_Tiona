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
TIMELINE.md + TIMELINE.html (self-contained dashboard, no network, no CDN —
open locally). Descriptive only — nothing consumes this for authority.

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
TIMELINE_HTML_PATH = os.path.join("docs", "evolution", "TIMELINE.html")


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


# ── HTML dashboard (2026-07-12, user-approved "later" item) ──────────────────
# Self-contained: inline CSS/JS, zero network, zero CDN — opens as a local
# file. Doctrine preserved: negative verdicts get EQUAL visual prominence,
# forced-pending renders visibly, every card shows its evidence artifact.

_HTML_COLORS = {"validated": "#22c55e", "rejected": "#ef4444",
                "no_change": "#94a3b8", "pending": "#f59e0b"}
_HTML_LABEL = {"validated": "VALIDATED", "rejected": "REJECTED",
               "no_change": "NO CHANGE", "pending": "PENDING"}


def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _pretty_date(d: str) -> str:
    return (f"{d[:4]}-{d[4:6]}-{d[6:8]}"
            if len(d) == 8 and d.isdigit() else d)


def render_html(base_dir=None, out_path=None) -> str:
    """TIMELINE.html — filterable dashboard over milestones.jsonl.
    Newest day first; verdict chips filter; free-text search; every card
    carries verdict / change / measured / evidence / commit."""
    milestones = load_milestones(base_dir)
    counts = {v: 0 for v in VERDICTS}
    for m in milestones:
        counts[m.get("verdict", "pending")] = \
            counts.get(m.get("verdict", "pending"), 0) + 1

    cards = []
    for date in sorted({m["date"] for m in milestones}, reverse=True):
        day = [m for m in milestones if m["date"] == date]
        day_html = [f'<h2 class="day">{_esc(_pretty_date(date))}</h2>']
        for m in day:
            v = m.get("verdict", "pending")
            color = _HTML_COLORS.get(v, _HTML_COLORS["pending"])
            measured = ""
            if m.get("metric_before") is not None or m.get("metric_after") is not None:
                measured = (f'<div class="row"><span class="k">Measured</span>'
                            f'<span class="arrowblock"><span class="before">'
                            f'{_esc(m.get("metric_before"))}</span>'
                            f'<span class="arrow">&rarr;</span>'
                            f'<span class="after">{_esc(m.get("metric_after"))}'
                            f'</span></span></div>')
            evidence = (f'<div class="row"><span class="k">Evidence</span>'
                        f'<code>{_esc(m["evidence_ref"])}</code></div>'
                        if m.get("evidence_ref") else
                        '<div class="row"><span class="k">Evidence</span>'
                        '<em class="noev">none — pending until an artifact '
                        'exists</em></div>')
            commit = (f'<div class="row"><span class="k">Commit</span>'
                      f'<code>{_esc(m["commit"])}</code></div>'
                      if m.get("commit") else "")
            forced = ('<div class="forced">&#9888; forced pending — claims '
                      "don't get badges, artifacts do</div>"
                      if m.get("forced_pending") else "")
            day_html.append(
                f'<article class="card" data-verdict="{_esc(v)}">'
                f'<header><span class="badge" style="background:{color}">'
                f'{_HTML_LABEL.get(v, "PENDING")}</span>'
                f'<span class="mission">{_esc(m["mission"])}</span></header>'
                f'<p class="change">{_esc(m["change"])}</p>'
                f'{measured}{evidence}{commit}{forced}</article>')
        cards.append('<section class="dayblock">' + "".join(day_html)
                     + "</section>")

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    chips = "".join(
        f'<button class="chip" data-filter="{v}" '
        f'style="--c:{_HTML_COLORS[v]}">{_HTML_LABEL[v]} '
        f'<b>{counts.get(v, 0)}</b></button>' for v in VERDICTS)

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Organism Evolution Timeline</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; margin: 0; }}
  body {{ background:#0b1220; color:#dbe4f0; font:15px/1.55 system-ui,
         Segoe UI, sans-serif; padding:2rem 1rem 4rem; }}
  .wrap {{ max-width: 860px; margin: 0 auto; }}
  h1 {{ font-size:1.5rem; letter-spacing:.02em; }}
  .sub {{ color:#7d8aa0; margin:.35rem 0 1.4rem; font-size:.9rem; }}
  .controls {{ display:flex; flex-wrap:wrap; gap:.5rem; margin-bottom:1.6rem;
               align-items:center; }}
  .chip {{ background:#141d31; color:#dbe4f0; border:1px solid var(--c);
           border-radius:999px; padding:.3rem .8rem; cursor:pointer;
           font-size:.8rem; }}
  .chip b {{ color:var(--c); }}
  .chip.active {{ background:var(--c); color:#0b1220; }}
  .chip.all {{ --c:#dbe4f0; }}
  #q {{ flex:1 1 200px; min-width:160px; background:#141d31; color:#dbe4f0;
        border:1px solid #2a3752; border-radius:8px; padding:.4rem .7rem; }}
  .day {{ font-size:1.02rem; color:#9fb0c8; border-bottom:1px solid #22304a;
          padding-bottom:.3rem; margin:1.8rem 0 .9rem; }}
  .card {{ background:#121b2e; border:1px solid #22304a; border-radius:12px;
           padding:1rem 1.1rem; margin-bottom:.9rem; }}
  .card header {{ display:flex; gap:.7rem; align-items:center;
                  margin-bottom:.55rem; flex-wrap:wrap; }}
  .badge {{ color:#0b1220; font-weight:700; font-size:.72rem;
            letter-spacing:.06em; border-radius:6px; padding:.18rem .55rem; }}
  .mission {{ font-weight:650; font-size:1.02rem; }}
  .change {{ color:#c3cfdf; margin-bottom:.6rem; }}
  .row {{ display:flex; gap:.6rem; margin:.3rem 0; font-size:.86rem;
          align-items:baseline; }}
  .k {{ color:#7d8aa0; min-width:74px; flex:none; text-transform:uppercase;
        font-size:.68rem; letter-spacing:.08em; padding-top:.15rem; }}
  code {{ background:#0e1626; border:1px solid #22304a; border-radius:6px;
          padding:.08rem .4rem; font-size:.8rem; word-break:break-all; }}
  .arrowblock {{ display:flex; gap:.5rem; flex-wrap:wrap;
                 align-items:baseline; }}
  .before {{ color:#8fa0b8; }}
  .after {{ color:#e8eefb; }}
  .arrow {{ color:#5b6b85; }}
  .noev {{ color:#f59e0b; }}
  .forced {{ color:#f59e0b; font-size:.8rem; margin-top:.45rem; }}
  .hidden {{ display:none; }}
  .doctrine {{ background:#121b2e; border:1px dashed #2a3752; border-radius:12px;
               padding: .8rem 1rem; color:#9fb0c8; font-size:.85rem;
               margin-bottom:1.4rem; }}
</style></head><body><div class="wrap">
<h1>Organism Evolution Timeline</h1>
<div class="sub">{len(milestones)} milestones &middot; rendered {stamp}
&middot; descriptive only — nothing consumes this for authority</div>
<div class="doctrine">Every badge is backed by a replay / lab / ablation
artifact; a claim without an artifact renders as PENDING.
<b>REJECTED and NO CHANGE entries carry the same prominence as wins — they
are the credibility of this document.</b></div>
<div class="controls">
  <button class="chip all active" data-filter="all">ALL
    <b>{len(milestones)}</b></button>
  {chips}
  <input id="q" type="search" placeholder="search missions, changes, evidence&hellip;">
</div>
<main id="timeline">
{"".join(cards)}
</main></div>
<script>
  const chipsEls = document.querySelectorAll('.chip');
  const q = document.getElementById('q');
  let verdict = 'all';
  function apply() {{
    const needle = q.value.toLowerCase();
    document.querySelectorAll('.card').forEach(c => {{
      const okV = verdict === 'all' || c.dataset.verdict === verdict;
      const okQ = !needle || c.textContent.toLowerCase().includes(needle);
      c.classList.toggle('hidden', !(okV && okQ));
    }});
    document.querySelectorAll('.dayblock').forEach(d => {{
      d.classList.toggle('hidden',
        d.querySelectorAll('.card:not(.hidden)').length === 0);
    }});
  }}
  chipsEls.forEach(ch => ch.addEventListener('click', () => {{
    chipsEls.forEach(x => x.classList.remove('active'));
    ch.classList.add('active');
    verdict = ch.dataset.filter;
    apply();
  }}));
  q.addEventListener('input', apply);
</script></body></html>"""

    path = out_path or (os.path.join(base_dir, "TIMELINE.html") if base_dir
                        else TIMELINE_HTML_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return html


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
        render_html()
        print(f"rendered {TIMELINE_PATH} + {TIMELINE_HTML_PATH}")
