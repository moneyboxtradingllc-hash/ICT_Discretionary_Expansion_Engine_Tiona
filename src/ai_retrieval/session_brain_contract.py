"""Which Brain contract produced a historical observation.

BIND-HISTORICAL-BRAIN-CONTRACT-PROVENANCE (2026-08-07).

`build_records` stamped `brain_contract_fingerprint()` -- the contract of the
code running the AUTHORING, not the contract that produced the narrative being
described. Re-authoring a historical session therefore relabelled it with
today's contract. PROD-20260806 ran `gpt-5.6-luna`; its live records carried
`33fc76`, which is a value from the Terra era, stamped simply because that was
current when the records were written.

Two different facts had been collapsed into one field:

    A. the Brain contract that produced the historical reasoning
    B. the authoring implementation that produced the representation

Changing authoring code does not change who produced historical reasoning, so
they are now separate fields and A never falls back to B.

A is resolved from SESSION EVIDENCE only, in this order:

    1. the archived Brain artifact, if it recorded a contract fingerprint
    2. the session authorization record bound to that session_id
    3. UNRECORDED_AT_RUNTIME -- with the runtime commit, which pins the
       contract sources exactly even though the digest was never stored

Never from current code. An unrecoverable value stays unrecoverable.
"""
from __future__ import annotations

import glob
import json
import os

UNRECORDED = "UNRECORDED_AT_RUNTIME"

#: Where a session's own authorization record lives.
_AUTH_DIR = os.path.join("data", "integration", "topstepx")


def _from_brain_artifacts(archive_path: str) -> str | None:
    """The strongest evidence: the artifact stating its own contract."""
    for pattern in (os.path.join(archive_path, "brain", "full_artifacts", "*.json"),
                    os.path.join(archive_path, "brain", "*.json")):
        for path in sorted(glob.glob(pattern))[:1]:
            try:
                artifact = json.load(open(path, encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for key in ("brain_contract_fingerprint", "contract_fingerprint"):
                if artifact.get(key):
                    return str(artifact[key])
    return None


def _from_authorization(session_id: str) -> str | None:
    path = os.path.join(_AUTH_DIR, f"session_auth_{session_id}.json")
    try:
        record = json.load(open(path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if record.get("session_id") != session_id:
        return None
    return record.get("brain_contract_fingerprint") or None


def _runtime_head(archive_path: str) -> str | None:
    """The commit that ran. Pins the contract sources even when the digest
    itself was never recorded."""
    try:
        manifest = json.load(open(os.path.join(archive_path, "manifest.json"),
                                  encoding="utf-8"))
        if manifest.get("runtime_head"):
            return str(manifest["runtime_head"])
    except (OSError, json.JSONDecodeError):
        pass
    # Multi-phase native archives record a commit per phase; the FINAL phase is
    # the one whose code produced the last of the evidence.
    try:
        phases = json.load(open(os.path.join(archive_path, "git",
                                             "phase_commit_map.json"),
                                encoding="utf-8")).get("phases") or []
        if phases and phases[-1].get("commit"):
            return str(phases[-1]["commit"])
    except (OSError, json.JSONDecodeError):
        pass
    try:
        head = open(os.path.join(archive_path, "git", "final_head.txt"),
                    encoding="utf-8").read().strip()
        return head[:7] or None
    except OSError:
        return None


def resolve_source_brain_contract(archive_path: str, session_id: str) -> dict:
    """Session-bound provenance for the contract that produced the narrative."""
    fingerprint = _from_brain_artifacts(archive_path)
    if fingerprint:
        source = "archived_brain_artifact"
    else:
        fingerprint = _from_authorization(session_id)
        source = "session_authorization_record" if fingerprint else None
    head = _runtime_head(archive_path)
    if not fingerprint:
        return {
            "source_brain_contract_fingerprint": UNRECORDED,
            "source_brain_contract_fingerprint_suffix": UNRECORDED,
            "source_brain_contract_evidence": (
                "no archived artifact and no authorization recorded a Brain "
                "contract fingerprint for this session"),
            "source_runtime_head": head,
            "source_brain_contract_resolution": "UNRECOVERABLE_FROM_EVIDENCE",
        }
    return {
        "source_brain_contract_fingerprint": fingerprint,
        "source_brain_contract_fingerprint_suffix": fingerprint[-6:],
        "source_brain_contract_evidence": source,
        "source_runtime_head": head,
        "source_brain_contract_resolution": "PROVEN_FROM_SESSION_EVIDENCE",
    }
