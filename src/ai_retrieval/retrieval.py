"""
Phase AB-3 — Retrieval API + audit logging.

Given the current snapshot/context, return the nearest historical analogs by
market-state cosine similarity. Authoritative retrieval excludes structure-
tainted and non-validated-provenance records (Requirement 3 / T2).

OBSERVE-ONLY: this module retrieves and logs. It does not author, qualify,
select, approve, or execute anything (Requirement 7). Never raises.
"""
import json
import os
from datetime import datetime

import pytz

from ai_retrieval.embedding import embed, cosine
from ai_retrieval.memory_schema import is_authoritative
from ai_retrieval.vector_store import load_records

_EASTERN = pytz.timezone("America/New_York")


def _log_dir() -> str:
    return os.path.join(os.getenv("AI_RETRIEVAL_DIR", os.path.join("data", "ai_retrieval")),
                        "retrieval_logs")


def _enabled() -> bool:
    return os.getenv("AI_RETRIEVAL_ENABLED", "false").lower().strip() == "true"


def _analog_view(rec: dict, score: float) -> dict:
    nc = rec.get("narrative_context", {}) or {}
    oc = rec.get("outcome_context", {}) or {}
    pc = rec.get("playbook_context", {}) or {}
    mc = rec.get("market_context", {}) or {}
    return {
        "similarity": round(score, 4),
        "timestamp": mc.get("timestamp"),
        "regime": mc.get("regime"),
        "narrative_direction": nc.get("narrative_direction"),
        "narrative_phase": nc.get("narrative_phase"),
        "delivery_direction": nc.get("delivery_direction"),
        "active_liquidity_draw": nc.get("active_liquidity_draw"),
        "active_playbook": pc.get("active_playbook"),
        "trade_taken": oc.get("trade_taken"),
        "outcome": oc.get("win_loss_be"),
        "r_multiple": oc.get("r_multiple"),
        "management_path": oc.get("management_path"),
        "direction_source": (rec.get("provenance", {}) or {}).get("direction_source"),
    }


def retrieve_analogs(context: dict, k: int = 5, authoritative_only: bool = True,
                     min_similarity: float = 0.5, persist_log: bool = True) -> dict:
    """
    Return top-k historical analogs of `context` (a live snapshot-shaped dict or
    a memory record). Logs query + accepted + rejected for auditability (T7).
    Never raises; observe-only.
    """
    try:
        qvec = embed(context)
        records = load_records()

        scored, rejected = [], []
        for rec in records:
            rvec = rec.get("embedding") or embed(rec)
            score = cosine(qvec, rvec)
            authoritative = is_authoritative(rec)
            if authoritative_only and not authoritative:
                rejected.append({"reason": "non_authoritative_provenance",
                                 "direction_source": (rec.get("provenance", {}) or {}).get("direction_source"),
                                 "similarity": round(score, 4)})
                continue
            if score < min_similarity:
                rejected.append({"reason": "below_min_similarity",
                                 "similarity": round(score, 4)})
                continue
            scored.append((score, rec))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:k]
        analogs = [_analog_view(rec, score) for score, rec in top]

        result = {
            "enabled": True,
            "authority": "observe_only",
            "query_embedding_dim": len(qvec),
            "corpus_size": len(records),
            "authoritative_only": authoritative_only,
            "returned": len(analogs),
            "analogs": analogs,
            "rejected_count": len(rejected),
        }

        if persist_log:
            result["log_path"] = _persist(qvec, analogs, rejected, context)
        return result
    except Exception as exc:  # noqa: BLE001
        return {"enabled": True, "authority": "observe_only", "analogs": [],
                "error": f"retrieval error (observe-only): {exc}"}


def _persist(qvec, analogs, rejected, context) -> "str | None":
    try:
        d = _log_dir()
        os.makedirs(d, exist_ok=True)
        ts = datetime.now(_EASTERN).strftime("%Y%m%d_%H%M%S_%f")
        path = os.path.join(d, f"retrieval_{ts}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({
                "query_timestamp": context.get("timestamp"),
                "query_vector": qvec,
                "accepted_memories": analogs,
                "rejected_memories": rejected,
                "provenance_status": {
                    "accepted": len(analogs),
                    "rejected_non_authoritative": sum(
                        1 for r in rejected if r.get("reason") == "non_authoritative_provenance"),
                },
            }, fh, default=str)
        return path
    except Exception:  # noqa: BLE001
        return None


def retrieve_for_snapshot(snapshot: dict, symbol: str) -> dict:
    """Scan-loop hook (observe-only). Gated by AI_RETRIEVAL_ENABLED."""
    if not _enabled():
        return {"enabled": False, "authority": "observe_only", "analogs": []}
    return retrieve_analogs(snapshot, k=5, authoritative_only=True)
