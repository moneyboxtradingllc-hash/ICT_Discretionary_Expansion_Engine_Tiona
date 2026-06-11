"""
Phase 5H.4 — Governance Reporting.

Daily digest  — operational health: events, firings, resolution backlog.
Weekly report — the legislative session: per-rule scorecards against the
                promotion/demotion bars, member calibration, rules near
                review dates. THIS report is the artifact attached to every
                promotion commit (registry evidence_refs).

Reports are written to data/rule_governance/reports/ as JSON + markdown.
OBSERVE ONLY. Promotion decisions cite weekly reports, never single days.
Never raises.
"""
import json
import os
from datetime import datetime, timedelta

import pytz

from rule_governance.divergence_ledger import load_events
from rule_governance.member_calibration import calibrate_members
from rule_governance.rule_registry import load_registry, rules_near_review
from rule_governance.rule_scoring import score_rule, score_thesis_events

_EASTERN = pytz.timezone("America/New_York")


def _reports_dir() -> str:
    return os.path.join(
        os.getenv("RULE_GOVERNANCE_DIR", os.path.join("data", "rule_governance")),
        "reports",
    )


def _write_report(name: str, payload: dict, markdown: str) -> "str | None":
    try:
        rdir = _reports_dir()
        os.makedirs(rdir, exist_ok=True)
        json_path = os.path.join(rdir, f"{name}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        with open(os.path.join(rdir, f"{name}.md"), "w", encoding="utf-8") as f:
            f.write(markdown)
        return json_path
    except OSError:
        return None


# ── Daily digest ──────────────────────────────────────────────────────────────

def build_daily_digest(symbol: str, date_str: "str | None" = None) -> dict:
    """Operational health for one session. Never raises."""
    try:
        if date_str is None:
            date_str = datetime.now(_EASTERN).strftime("%Y%m%d")

        events = [e for e in load_events(symbol, days=30)
                  if e.get("timestamp", "").startswith(date_str)]
        resolved = [e for e in events
                    if (e.get("resolution") or {}).get("state") == "resolved"]
        by_rule: dict = {}
        for e in events:
            by_rule.setdefault(e.get("rule_id", "?"), 0)
            by_rule[e["rule_id"]] += 1

        digest = {
            "report":          "daily_digest",
            "symbol":          symbol,
            "date":            date_str,
            "events":          len(events),
            "events_by_rule":  by_rule,
            "resolved":        len(resolved),
            "pending_backlog": len(events) - len(resolved),
        }

        md = (
            f"# Rule Governance Daily Digest — {symbol} {date_str}\n\n"
            f"- events: {len(events)}\n"
            f"- by rule: {by_rule or 'none'}\n"
            f"- resolved: {len(resolved)}\n"
            f"- pending backlog: {digest['pending_backlog']}\n"
        )
        digest["report_path"] = _write_report(
            f"daily_{date_str}_{symbol}", digest, md)
        return digest
    except Exception as exc:  # noqa: BLE001
        return {"report": "daily_digest", "error": str(exc)}


# ── Weekly governance report ──────────────────────────────────────────────────

def build_weekly_report(symbol: str, days: int = 7,
                        opportunities_seen: int = 0,
                        sessions_seen: int = 0) -> dict:
    """
    The legislative session. Scores every non-retired rule against the
    promotion/demotion bars, builds the member calibration table, and flags
    rules near their review dates. Never raises.
    """
    try:
        now      = datetime.now(_EASTERN)
        week_tag = now.strftime("%Y_W%W")
        events   = load_events(symbol, days=max(days, 30))

        registry = load_registry()
        scorecards = []
        for rule in registry["rules"]:
            if rule.get("status") == "retired":
                continue
            if rule.get("status") != "shadow":
                # promoted/grandfathered rules are monitored once instrumented;
                # they have no shadow events yet — listed for completeness
                scorecards.append({
                    "rule_id": rule["rule_id"], "status": rule["status"],
                    "note": "enforced law — instrumentation pending",
                })
                continue
            card = score_rule(rule["rule_id"], events,
                              opportunities_seen=opportunities_seen,
                              sessions_seen=sessions_seen)
            card["status"] = "shadow"
            scorecards.append(card)

        calibration = calibrate_members(events)
        near_review = rules_near_review(days=7)
        thesis      = score_thesis_events(events)   # 5T.2 counterfactuals

        report = {
            "report":        "weekly_governance",
            "week":          week_tag,
            "symbol":        symbol,
            "generated_at":  now.strftime("%Y-%m-%d %H:%M"),
            "window_days":   days,
            "scorecards":    scorecards,
            "member_calibration": calibration,
            "thesis_exit_shadow": thesis,
            "rules_near_review":  near_review,
            "quarantined":   registry["quarantined"],
        }

        md_lines = [f"# Weekly Governance Report — {symbol} {week_tag}", ""]
        for card in scorecards:
            if "error" in card or "note" in card:
                md_lines.append(f"- **{card['rule_id']}** ({card.get('status')}): "
                                f"{card.get('note', card.get('error'))}")
                continue
            promo = card["promotion"]
            demo  = card["demotion"]
            verdict = ("PROMOTION ELIGIBLE" if promo["eligible"]
                       else ("DEMOTION FLAGGED" if demo["flagged"] else "incubating"))
            md_lines.append(
                f"- **{card['rule_id']}**: {verdict} | resolved={card['events_resolved']}"
                f" | net={card['net_protected_R']}R | eff={card['efficiency']}"
                f" | fills={card['fills']}"
            )
        if near_review:
            md_lines += ["", "## Rules near review"]
            for r in near_review:
                tag = "OVERDUE" if r["overdue"] else "due soon"
                md_lines.append(f"- {r['rule_id']} — review_by {r['review_by']} ({tag})")
        md_lines += ["", "_Promotion remains a human-reviewed code change._"]

        report["report_path"] = _write_report(
            f"weekly_{week_tag}_{symbol}", report, "\n".join(md_lines))
        return report
    except Exception as exc:  # noqa: BLE001
        return {"report": "weekly_governance", "error": str(exc)}
