"""
MISSION-CONTROL (2026-07-30) — the throne room.

One self-contained status page rendering telemetry that ALREADY EXISTS on
disk. Rendering only: this module reads, formats, and writes one HTML file —
it holds no authority, changes no behavior, and is safe under the
decision-authority freeze.

Doctrine (inherited from the TIMELINE dashboard, test-locked):
  * self-contained — inline CSS, zero network/CDN/JS dependencies; opens as
    a local file
  * honest absence — a missing source renders as an ABSENT panel, never a
    blank or an invented value; every panel names its source file and age
  * hostile text is HTML-escaped everywhere
  * the collector NEVER raises — one corrupt file must not kill the page

CLI:
  python -m mission_control.mission_control            # render to default out
      [--out data/ops/mission_control/MISSION_CONTROL.html] [--json]
"""
from __future__ import annotations

import glob
import html
import json
import os
from datetime import datetime, timezone

DEFAULT_OUT = os.path.join("data", "ops", "mission_control",
                           "MISSION_CONTROL.html")
STALE_DAYS = 3.0

_DET_DIR = os.path.join("data", "integration", "topstepx", "deterministic")


# ── helpers ──────────────────────────────────────────────────────────────────

def _age_days(path: str) -> "float | None":
    try:
        return round((datetime.now(timezone.utc).timestamp()
                      - os.path.getmtime(path)) / 86400.0, 2)
    except OSError:
        return None


def _load_json(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _absent(source: str, note: str = "source not found") -> dict:
    return {"status": "ABSENT", "source": source, "note": note}


def _panel(fn):
    """Every panel is guarded: any exception becomes an ERROR panel."""
    def wrap(root):
        try:
            return fn(root)
        except Exception as exc:  # noqa: BLE001 — the page must always render
            return {"status": "ERROR", "note": repr(exc)}
    return wrap


def _status_for_age(age: "float | None") -> str:
    if age is None:
        return "UNKNOWN"
    return "STALE" if age > STALE_DAYS else "LIVE"


# ── panels (pure reads) ──────────────────────────────────────────────────────

@_panel
def _kill_switch(root: str) -> dict:
    p = os.path.join(root, _DET_DIR, "STOP")
    return {"status": "OK", "source": p,
            "stop_file_present": os.path.exists(p)}


@_panel
def _money_venue(root: str) -> dict:
    state_p = os.path.join(root, _DET_DIR, "session_state.json")
    ev_dir = os.path.join(root, _DET_DIR, "evidence")
    if not os.path.exists(state_p):
        return _absent(state_p)
    st = _load_json(state_p)
    out = {"status": _status_for_age(_age_days(state_p)),
           "source": state_p, "age_days": _age_days(state_p),
           "mode": st.get("mode"), "account": st.get("account"),
           "instrument": st.get("instrument"),
           "decision_window": st.get("decision_window"),
           "max_trades": st.get("max_trades"),
           "max_risk_usd": st.get("max_risk_usd"),
           "daily_loss_ceiling": st.get("daily_loss_ceiling"),
           "trade_count": st.get("trade_count"),
           "realized_pnl": st.get("realized_pnl")}
    ev_files = sorted(glob.glob(os.path.join(ev_dir, "*.jsonl")))
    if ev_files:
        latest = ev_files[-1]
        lines = [ln for ln in open(latest, encoding="utf-8")
                 .read().splitlines() if ln.strip()]
        verdicts = {}
        last = None
        for ln in lines:
            try:
                rec = json.loads(ln)
            except ValueError:
                continue
            last = rec
            v = rec.get("verdict") or "?"
            verdicts[v] = verdicts.get(v, 0) + 1
        out["evidence"] = {
            "file": os.path.basename(latest), "age_days": _age_days(latest),
            "scans": len(lines), "verdicts": verdicts,
            "last_scan": None if not last else {
                "verdict": last.get("verdict"),
                "in_decision_window": last.get("in_decision_window"),
                "bridge_armed": last.get("bridge_armed"),
                "can_enter_reason": last.get("can_enter_reason"),
                "equity": last.get("equity"),
                "htf_memory_age": (last.get("snapshot") or {}).get("htf_memory_age"),
            }}
    else:
        out["evidence"] = _absent(ev_dir)
    return out


@_panel
def _venue_health(root: str) -> dict:
    p = os.path.join(root, "data", "integration", "topstepx",
                     "integration_health.json")
    if not os.path.exists(p):
        return _absent(p)
    d = _load_json(p)
    scalars = {k: v for k, v in d.items()
               if isinstance(v, (str, int, float, bool))}
    return {"status": _status_for_age(_age_days(p)), "source": p,
            "age_days": _age_days(p), "fields": scalars}


@_panel
def _organism(root: str) -> dict:
    """Latest QQQ live-session funnel + last Brain state, from stored
    snapshots via the existing stage-trace reader."""
    sdir = os.path.join(root, "data", "live_snapshots")
    names = sorted(n for n in (os.listdir(sdir) if os.path.isdir(sdir) else [])
                   if n.endswith(".json"))
    if not names:
        return _absent(sdir, "no stored snapshots")
    latest_date = names[-1][:8]
    day = [n for n in names if n.startswith(latest_date)]
    from replay_validation.stage_trace import trace_from_stored
    traces = []
    for n in day:
        try:
            traces.append(trace_from_stored(os.path.join(sdir, n)))
        except Exception:  # noqa: BLE001 — one corrupt snapshot is not a page outage
            continue
    last = traces[-1] if traces else {}
    funnel = {
        "scans": len(traces),
        "sovereign": sum(1 for t in traces if t.get("brain_sovereign")),
        "qualified": sum(1 for t in traces if t.get("qual_status")
                         in ("candidate", "qualified", "elite")),
        "intents": sum(1 for t in traces if t.get("intent_created")),
        "confirmed_triggers": sum(1 for t in traces
                                  if t.get("trigger_status") == "confirmed"),
        "would_authorize": sum(1 for t in traces if t.get("would_authorize")),
    }
    age = _age_days(os.path.join(sdir, day[-1]))
    return {"status": _status_for_age(age), "source": sdir,
            "session_date": latest_date, "age_days": age, "funnel": funnel,
            "last_scan": {k: last.get(k) for k in
                          ("timestamp", "brain_direction", "brain_sovereign",
                           "qual_status", "trigger_status", "would_authorize",
                           "gate_blockers") if k in last}}


@_panel
def _htf_memory(root: str) -> dict:
    d = os.path.join(root, "data", "htf_memory")
    files = sorted(glob.glob(os.path.join(d, "*.json")))
    if not files:
        return _absent(d, "no HTF memory stores yet")
    stores = {}
    for p in files:
        days = (_load_json(p) or {}).get("days") or {}
        stores[os.path.basename(p)[:-5]] = {
            "daily_records": len(days),
            "last_date": max(days) if days else None,
            "age_days": _age_days(p)}
    return {"status": "OK", "source": d, "stores": stores}


@_panel
def _substrate(root: str) -> dict:
    pt = os.path.join(root, "data", "paper_trades")
    files = sorted(glob.glob(os.path.join(pt, "*_paper_trades.json")))
    trades = 0
    for p in files:
        try:
            d = _load_json(p)
            if isinstance(d, list):
                trades += len(d)
            elif isinstance(d, dict) and isinstance(d.get("trades"), list):
                trades += len(d["trades"])
        except ValueError:
            continue
    acc_p = os.path.join(root, "data", "performance", "QQQ",
                         "brain_accuracy.json")
    acc = None
    if os.path.exists(acc_p):
        acc = (_load_json(acc_p) or {}).get("overall")
    return {"status": "OK" if files else "ABSENT", "source": pt,
            "journaled_trades": trades, "sessions": len(files),
            "last_session": files[-1][-len("YYYYMMDD_QQQ_paper_trades.json"):][:8]
                            if files else None,
            "brain_accuracy_overall": acc}


@_panel
def _evolution(root: str) -> dict:
    p = os.path.join(root, "docs", "evolution", "milestones.jsonl")
    if not os.path.exists(p):
        return _absent(p)
    rows = []
    for ln in open(p, encoding="utf-8").read().splitlines():
        try:
            rows.append(json.loads(ln))
        except ValueError:
            continue
    recent = [{k: r.get(k) for k in ("date", "mission", "verdict", "commit")}
              for r in rows[-6:]][::-1]
    return {"status": "OK", "source": p, "total_milestones": len(rows),
            "recent": recent}


def collect_status(root: str = ".") -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": os.path.abspath(root),
        "panels": {
            "kill_switch":  _kill_switch(root),
            "money_venue":  _money_venue(root),
            "venue_health": _venue_health(root),
            "organism":     _organism(root),
            "htf_memory":   _htf_memory(root),
            "substrate":    _substrate(root),
            "evolution":    _evolution(root),
        },
    }


# ── renderer (self-contained, escaped) ───────────────────────────────────────

_CSS = """
body{background:#0d1117;color:#c9d1d9;font-family:Consolas,Menlo,monospace;
     margin:0;padding:24px}
h1{color:#e6edf3;font-size:20px;margin:0 0 4px}
.sub{color:#8b949e;font-size:12px;margin-bottom:20px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));
      gap:14px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;
      padding:14px 16px;overflow-x:auto}
.card h2{font-size:13px;letter-spacing:1px;color:#e6edf3;margin:0 0 8px;
         text-transform:uppercase}
.chip{display:inline-block;font-size:10px;padding:1px 8px;border-radius:10px;
      margin-left:8px;vertical-align:middle}
.LIVE{background:#1f6f43;color:#fff}.OK{background:#1f6f43;color:#fff}
.STALE{background:#8a6d1d;color:#fff}.ABSENT{background:#6e1f28;color:#fff}
.ERROR{background:#6e1f28;color:#fff}.UNKNOWN{background:#444c56;color:#fff}
table{border-collapse:collapse;width:100%;font-size:12px}
td{padding:2px 8px 2px 0;vertical-align:top;color:#c9d1d9}
td.k{color:#8b949e;white-space:nowrap}
.src{color:#484f58;font-size:10px;margin-top:8px;word-break:break-all}
.stop{color:#f85149;font-weight:bold}
"""


def _esc(v) -> str:
    return html.escape(str(v), quote=True)


def _rows(d: dict) -> str:
    out = []
    for k, v in d.items():
        if k in ("status", "source", "note"):
            continue
        if isinstance(v, dict):
            v = json.dumps(v, default=str)
        out.append(f"<tr><td class='k'>{_esc(k)}</td>"
                   f"<td>{_esc(v)}</td></tr>")
    return "<table>" + "".join(out) + "</table>"


def _card(title: str, panel: dict) -> str:
    status = _esc(panel.get("status", "UNKNOWN"))
    body = _rows(panel)
    note = (f"<div class='src'>{_esc(panel['note'])}</div>"
            if panel.get("note") else "")
    src = (f"<div class='src'>{_esc(panel['source'])}</div>"
           if panel.get("source") else "")
    return (f"<div class='card'><h2>{_esc(title)}"
            f"<span class='chip {status}'>{status}</span></h2>"
            f"{body}{note}{src}</div>")


def render_html(status: dict) -> str:
    panels = status.get("panels", {})
    stop = (panels.get("kill_switch") or {}).get("stop_file_present")
    banner = ("<div class='card'><span class='stop'>STOP FILE PRESENT — "
              "LANE HALTED</span></div>" if stop else "")
    cards = "".join(_card(k.replace("_", " "), v) for k, v in panels.items())
    return (f"<style>{_CSS}</style>"
            f"<h1>MISSION CONTROL</h1>"
            f"<div class='sub'>generated {_esc(status.get('generated_at'))} · "
            f"root {_esc(status.get('root'))} · rendering only — this page "
            f"holds no authority</div>{banner}"
            f"<div class='grid'>{cards}</div>")


def render(root: str = ".", out: str = DEFAULT_OUT) -> str:
    status = collect_status(root)
    page = ("<!doctype html><html><head><meta charset='utf-8'>"
            "<title>Mission Control</title></head><body>"
            + render_html(status) + "</body></html>")
    out_path = os.path.join(root, out) if not os.path.isabs(out) else out
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(page)
    return out_path


def _main() -> int:
    import argparse
    p = argparse.ArgumentParser(description="MISSION-CONTROL status page")
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--json", action="store_true",
                   help="print collected status as JSON instead of rendering")
    args = p.parse_args()
    if args.json:
        print(json.dumps(collect_status("."), indent=1, default=str))
        return 0
    path = render(".", args.out)
    print(f"rendered {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
