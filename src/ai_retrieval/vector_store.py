"""
Phase AB-3 — Persistent vector store.

Append-only JSONL at data/ai_retrieval/memory_store.jsonl. Each line is a memory
record (memory_schema) with its precomputed embedding. Survives restart/replay/
sessions (Requirement 8). Observe-only. Never raises.
"""
import json
import os

from ai_retrieval.embedding import embed

_DEFAULT = os.path.join("data", "ai_retrieval")


def _dir() -> str:
    return os.getenv("AI_RETRIEVAL_DIR", _DEFAULT)


def _store_path() -> str:
    return os.path.join(_dir(), "memory_store.jsonl")


def add_record(record: dict) -> bool:
    """Embed and append one record. Idempotency is the caller's concern."""
    try:
        os.makedirs(_dir(), exist_ok=True)
        line = dict(record)
        line["embedding"] = embed(record)
        with open(_store_path(), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, default=str) + "\n")
        return True
    except Exception:  # noqa: BLE001
        return False


def add_records(records: list) -> int:
    n = 0
    for r in records:
        if add_record(r):
            n += 1
    return n


def load_records() -> list:
    """Load all stored records (with embeddings). Never raises."""
    path = _store_path()
    out = []
    try:
        if not os.path.exists(path):
            return out
        with open(path, encoding="utf-8") as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    out.append(json.loads(ln))
                except json.JSONDecodeError:
                    continue
    except Exception:  # noqa: BLE001
        return out
    return out


def count() -> int:
    return len(load_records())


def clear() -> None:
    """Test/backfill helper — remove the store file."""
    try:
        if os.path.exists(_store_path()):
            os.remove(_store_path())
    except Exception:  # noqa: BLE001
        pass
