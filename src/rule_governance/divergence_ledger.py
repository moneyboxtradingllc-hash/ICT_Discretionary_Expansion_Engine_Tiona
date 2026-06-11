"""
Phase 5H.3 — Divergence Ledger.

Persists shadow-evaluation events and resolves them against measured outcomes:

  Executed events  -> realized_r from the closed trade journal record
                      (gold standard, source="fill")
  Unexecuted events-> proxy_r from the intent archive
                      (source="proxy"):
                        first_threshold_crossed == "sl_1r" -> -1.0
                        first_threshold_crossed == "tp_2r" -> +2.0
                        legacy records without ordering: MAE-first assumption
                        (conservative — biases AGAINST the rule)
                        expired with neither           -> 0.0, low_confidence

OBSERVE ONLY. Never raises. Ledger write failure degrades to a warning,
never to a scan failure and never to an execution change.
"""
import json
import os
from datetime import datetime, timedelta

import pytz

_EASTERN = pytz.timezone("America/New_York")


def _ledger_dir() -> str:
    return os.path.join(
        os.getenv("RULE_GOVERNANCE_DIR", os.path.join("data", "rule_governance")),
        "ledger",
    )


def _ledger_path(date_str: str, symbol: str) -> str:
    return os.path.join(_ledger_dir(), f"{date_str}_{symbol}_events.json")


def _load_file(path: str) -> list:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("events", [])
    except (OSError, json.JSONDecodeError):
        return []


def _save_file(path: str, events: list) -> bool:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"events": events}, f, indent=1)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


# ── Append ────────────────────────────────────────────────────────────────────

def append_events(events: list, symbol: str) -> dict:
    """Append events to today's ledger file. Never raises."""
    if not events:
        return {"appended": 0, "ok": True}
    try:
        date_str = datetime.now(_EASTERN).strftime("%Y%m%d")
        path     = _ledger_path(date_str, symbol)
        existing = _load_file(path)
        existing_ids = {e.get("event_id") for e in existing}
        new = [e for e in events if e.get("event_id") not in existing_ids]
        existing.extend(new)
        ok = _save_file(path, existing)
        return {"appended": len(new) if ok else 0, "ok": ok}
    except Exception as exc:  # noqa: BLE001
        return {"appended": 0, "ok": False, "warning": str(exc)}


# ── Load ──────────────────────────────────────────────────────────────────────

def load_events(symbol: "str | None" = None, days: int = 30) -> list:
    """All events from the last `days` ledger files. Never raises."""
    out = []
    try:
        today = datetime.now(_EASTERN).date()
        for d in range(days):
            date_str = (today - timedelta(days=d)).strftime("%Y%m%d")
            if symbol:
                out.extend(_load_file(_ledger_path(date_str, symbol)))
            else:
                ldir = _ledger_dir()
                if not os.path.isdir(ldir):
                    continue
                for fname in os.listdir(ldir):
                    if fname.startswith(date_str) and fname.endswith("_events.json"):
                        out.extend(_load_file(os.path.join(ldir, fname)))
    except Exception:  # noqa: BLE001
        pass
    return out


# ── Outcome lookups ───────────────────────────────────────────────────────────

def _find_closed_trade(trade_id: str, symbol: str) -> "dict | None":
    """Closed journal trade by id (realized_r present), last 14 days."""
    try:
        from paper_execution.trade_journal import _search_recent_files
        for _, _, trades in _search_recent_files(symbol, days=14):
            for t in trades:
                if t.get("trade_id") == trade_id:
                    if t.get("realized_r") is not None:
                        return t
                    return None  # found but still open
    except Exception:  # noqa: BLE001
        pass
    return None


def _find_intent(intent_id: str, symbol: str) -> "dict | None":
    """Intent archive record by id, today + recent files."""
    try:
        from intent_archive.intent_archive import _ARCHIVE_DIR
        today = datetime.now(_EASTERN).date()
        for d in range(14):
            date_str = (today - timedelta(days=d)).strftime("%Y%m%d")
            path = os.path.join(_ARCHIVE_DIR, f"{date_str}_{symbol}_intents.json")
            try:
                with open(path, encoding="utf-8") as f:
                    intents = json.load(f).get("intents", [])
            except (OSError, json.JSONDecodeError):
                continue
            for rec in intents:
                if rec.get("intent_id") == intent_id:
                    return rec
    except Exception:  # noqa: BLE001
        pass
    return None


def _resolve_from_intent(intent: dict) -> "dict | None":
    """Proxy resolution from an intent record. None while still open."""
    first = intent.get("first_threshold_crossed")
    if first == "sl_1r":
        return {"state": "resolved", "source": "proxy", "r": -1.0,
                "basis": "first_threshold_crossed=sl_1r"}
    if first == "tp_2r":
        return {"state": "resolved", "source": "proxy", "r": 2.0,
                "basis": "first_threshold_crossed=tp_2r"}

    # Legacy fallback: ordering unknown — MAE-first assumption (conservative)
    rps = intent.get("risk_per_share_reference")
    if rps:
        if intent.get("mae", 0.0) >= rps:
            return {"state": "resolved", "source": "proxy", "r": -1.0,
                    "basis": "legacy_mae_first_assumption"}
        if intent.get("mfe", 0.0) >= 2 * rps:
            return {"state": "resolved", "source": "proxy", "r": 2.0,
                    "basis": "legacy_mfe_2r"}

    if intent.get("status") in ("expired", "closed"):
        return {"state": "resolved", "source": "proxy", "r": 0.0,
                "low_confidence": True, "basis": "expired_indeterminate"}

    return None  # still open — stays pending


# ── Resolution job ────────────────────────────────────────────────────────────

def resolve_pending(symbol: str, days: int = 14) -> dict:
    """
    Resolve pending ledger events against trade journal closures and
    intent-archive outcomes. Runs every scan; idempotent. Never raises.
    Returns {"checked": n, "resolved": n, "still_pending": n}.
    """
    checked = resolved = pending = 0
    try:
        today = datetime.now(_EASTERN).date()
        now_str = datetime.now(_EASTERN).strftime("%Y%m%dT%H%M%S")

        for d in range(days):
            date_str = (today - timedelta(days=d)).strftime("%Y%m%d")
            path     = _ledger_path(date_str, symbol)
            events   = _load_file(path)
            if not events:
                continue

            changed = False
            for ev in events:
                if (ev.get("resolution") or {}).get("state") != "pending":
                    continue
                checked += 1

                resolution = None
                if ev.get("executed") and ev.get("trade_id"):
                    trade = _find_closed_trade(ev["trade_id"], symbol)
                    if trade is not None:
                        resolution = {
                            "state": "resolved", "source": "fill",
                            "r": float(trade["realized_r"]),
                            "basis": "journal_realized_r",
                        }
                elif ev.get("intent_id"):
                    intent = _find_intent(ev["intent_id"], symbol)
                    if intent is not None:
                        resolution = _resolve_from_intent(intent)

                if resolution is not None:
                    resolution["resolved_at"] = now_str
                    ev["resolution"] = resolution
                    resolved += 1
                    changed = True
                else:
                    pending += 1

            if changed:
                _save_file(path, events)
    except Exception:  # noqa: BLE001
        pass

    return {"checked": checked, "resolved": resolved, "still_pending": pending}
