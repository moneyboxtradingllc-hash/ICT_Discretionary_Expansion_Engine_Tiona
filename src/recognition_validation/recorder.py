"""Append-only run evidence: hash-chained events, call records, artifacts.

Each event is canonical event/v1 JSON on its own line, carrying its sequence,
the computed digest of its predecessor and its own payload digest. Artifacts
(transported input, prompt, raw response, parsed and post-guard output) are
content-addressed by the SHA-256 of their original bytes. A run root is fresh
by construction: an existing root refuses, so evidence is never overwritten.

Any recording failure raises RecorderError; the driver turns it into an
INFRASTRUCTURE_ERROR run that can never certify anything. Evidence on disk is
never read back as authority by the organism.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from recognition_validation import contracts as C

EVENTS = "events.jsonl"
CALLS = "brain_calls.jsonl"
ARTIFACTS = "artifacts"


class RecorderError(RuntimeError):
    """The evidence could not be durably recorded."""


def _json_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False, default=str).encode("utf-8")


class Recorder:
    def __init__(self, root, *, run_digest: str, trajectory_id: str, classification: str):
        self.root = Path(root)
        if self.root.exists() and any(self.root.iterdir()):
            raise C.ContractError("OUTPUT_ROOT_REUSE", "/" + str(self.root))
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / ARTIFACTS).mkdir()
        self.run_digest, self.trajectory_id, self.classification = run_digest, trajectory_id, classification
        self.sequence = 0
        self.previous = None
        self.events: list = []
        self.calls: list = []
        self.failed: str | None = None

    def _append(self, name: str, document: dict) -> None:
        try:
            line = _json_bytes(document) + b"\n"
            with open(self.root / name, "ab") as fh:
                fh.write(line)
                fh.flush()
                os.fsync(fh.fileno())
        except (OSError, TypeError, ValueError) as exc:
            self.failed = f"{type(exc).__name__}: {exc}"
            raise RecorderError(self.failed) from exc

    def artifact(self, data: bytes, *, kind: str, origin: str) -> dict:
        """Store bytes once under their own digest; return the artifact reference."""
        digest = C.sha256_hex(data)
        rel = f"{ARTIFACTS}/{kind}/{digest}"
        target = self.root / rel
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if target.read_bytes() != data:
                    raise RecorderError(f"artifact collision at {rel}")
            else:
                target.write_bytes(data)
        except OSError as exc:
            self.failed = f"{type(exc).__name__}: {exc}"
            raise RecorderError(self.failed) from exc
        return {"path": rel, "sha256": digest, "bytes": len(data), "origin": origin}

    def json_artifact(self, value, *, kind: str, origin: str) -> dict:
        return self.artifact(_json_bytes(value), kind=kind, origin=origin)

    def provenance(self, notes: str) -> dict:
        return {"classification": self.classification, "author_role": "STAGE5_RECORDER",
                "source_refs": [], "notes": notes}

    def event(self, **fields) -> dict:
        """Append one event/v1 after the action it describes; returns it."""
        document = {"schema_version": "event/v1",
                    "document_id": f"{self.trajectory_id}:event:{self.sequence}",
                    "provenance": self.provenance("Recorded after the actual production action."),
                    "run_digest": self.run_digest, "trajectory_id": self.trajectory_id,
                    "sequence": self.sequence, "previous_event_digest": self.previous}
        document.update(fields)
        document["event_payload_digest"] = C.event_digest(document)
        C.validate(document)
        self._append(EVENTS, document)
        self.previous = C.event_digest(document)
        self.sequence += 1
        self.events.append(document)
        return document

    def brain_call(self, record: dict) -> dict:
        C.validate(record)
        self._append(CALLS, record)
        self.calls.append(record)
        return record

    def write_document(self, name: str, document: dict) -> dict:
        C.validate(document)
        data = json.dumps(document, sort_keys=True, indent=1).encode("utf-8")
        target = self.root / name
        if target.exists():
            raise C.ContractError("ARTIFACT_OVERWRITE_REFUSED", "/" + name)
        try:
            target.write_bytes(data)
        except OSError as exc:
            self.failed = f"{type(exc).__name__}: {exc}"
            raise RecorderError(self.failed) from exc
        return {"path": name, "sha256": C.sha256_hex(data), "bytes": len(data), "origin": self.classification
                if self.classification in ("CONSTRUCTED", "REPOSITORY_RECORDED", "APPROVED_ARCHIVE") else "UNKNOWN"}


def read_events(root) -> list[dict]:
    """Strictly re-read and verify a recorded event chain (for compare/report)."""
    path = Path(root) / EVENTS
    events = [C.loads_strict(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    C.verify_event_chain(events)
    return events


def read_calls(root) -> list[dict]:
    path = Path(root) / CALLS
    if not path.exists():
        return []
    calls = [C.loads_strict(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    for call in calls:
        C.validate(call)
    return calls
