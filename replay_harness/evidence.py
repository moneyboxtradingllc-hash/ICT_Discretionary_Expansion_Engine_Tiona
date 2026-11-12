"""Approved evidence packets: identity, integrity, and guarded reads.

The harness reads the packets exactly as they were collected: straight out of
the zip whose SHA-256 is pinned below. Nothing is extracted, copied or
rewritten, so what is replayed is byte-for-byte what was hashed.

Two kinds of content are kept apart:

* DECISION INPUTS -- Brain call records and the session authorization. These
  existed when the decision was made.
* OUTCOMES -- everything written after a decision (decision rows, plan events,
  missions, submissions, protection records). Reading one of these goes through
  the OutcomeStore phase check and is refused during the decision pass.
"""
from __future__ import annotations

import hashlib
import json
import os
import zipfile

from guard import PHASE_COMPARISON, RULE_T_OUTCOME, LookaheadViolation

#: The five approved session packets. SHA-256 values are those reported to the
#: owner when each packet was collected.
PACKETS = (
    {"name": "EVIDENCE_20261102_203550",
     "sha256": "cfa231b2261e80a021fc17fdf1eed38b6c3ab2fd477ca7adca7770534608d72a",
     "sessions": ("PROD-20261030-RESTORED1", "PROD-20261102-RESTORED1")},
    {"name": "EVIDENCE_20261105_135250",
     "sha256": "8dd523b69bf5ed7c33329d8ffa5eff51b582117bae8ed8a8f3b7113956970992",
     "sessions": ("PROD-20261105-RESTORED1",)},
    {"name": "EVIDENCE_20261108_173324",
     "sha256": "dd00201325f065965ddccad2168069f4aafa8d677c13c5e96b79b38805251cd5",
     "sessions": ("PROD-20261106-RESTORED1",)},
    {"name": "EVIDENCE_20261109_164537",
     "sha256": "b370ce5da7e73a2656ad6d6704e53467a5ef7052886e43b7052e2de59ded47ad",
     "sessions": ("PROD-20261109-RESTORED1",)},
    {"name": "EVIDENCE_20261110_191144",
     "sha256": "431706ebaf76d59366b6650c1a4dfed6e2930a143c7382d9dc12c4115454c7f5",
     "sessions": ("PROD-20261103-RESTORED1", "PROD-20261110-RESTORED1")},
)

SESSIONS = ("PROD-20261030-RESTORED1", "PROD-20261102-RESTORED1",
            "PROD-20261103-RESTORED1", "PROD-20261105-RESTORED1",
            "PROD-20261106-RESTORED1", "PROD-20261109-RESTORED1",
            "PROD-20261110-RESTORED1")


def session_day(session_id: str) -> str:
    return session_id.split("-")[1]


def is_decision_input(rel: str) -> bool:
    base = os.path.basename(rel)
    return (rel.startswith("data/ai_brain/") and base.endswith("_MNQ.json")) or \
        base.startswith("session_auth_")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Evidence:
    def __init__(self, root: str, phase) -> None:
        self.root = root
        self._phase = phase
        self._zips = {}
        self._session_packet = {}
        for p in PACKETS:
            for s in p["sessions"]:
                self._session_packet[s] = p["name"]
        self.outcome_reads = 0

    # -- integrity ---------------------------------------------------------
    def _zip(self, name: str) -> zipfile.ZipFile:
        if name not in self._zips:
            self._zips[name] = zipfile.ZipFile(os.path.join(self.root, name + ".zip"))
        return self._zips[name]

    def verify(self) -> dict:
        """Packet hashes, then every file against the packet's own manifest.

        Hashing reads raw bytes only; no field of any outcome file is parsed
        here, so this runs before the decision pass without opening an outcome.
        """
        report = {"packets": [], "ok": True}
        for p in PACKETS:
            path = os.path.join(self.root, p["name"] + ".zip")
            entry = {"packet": p["name"] + ".zip", "expected_sha256": p["sha256"]}
            if not os.path.isfile(path):
                entry.update(present=False, ok=False)
                report["ok"] = False
                report["packets"].append(entry)
                continue
            actual = sha256_file(path)
            entry.update(present=True, actual_sha256=actual,
                         bytes=os.path.getsize(path), packet_hash_ok=(actual == p["sha256"]))
            z = self._zip(p["name"])
            manifest = json.loads(z.read(f"{p['name']}/MANIFEST.json"))
            entry["collected_at_head"] = manifest.get("head")
            members = {n for n in z.namelist() if not n.endswith("/")}
            listed, bad, missing, checked = 0, [], [], set()
            for f in manifest.get("files") or []:
                listed += 1
                # Market-data excerpts are stored under market_data_excerpt/ and
                # listed in the manifest under the path they were cut from.
                rel = (f"market_data_excerpt/{os.path.basename(f['path'])}"
                       if f.get("excerpt") else f["path"])
                member = f"{p['name']}/{rel}"
                checked.add(member)
                if member not in members:
                    missing.append(f["path"])
                    continue
                digest = sha256_bytes(z.read(member))
                if digest != f.get("sha256_redacted_copy"):
                    bad.append(f["path"])
            redacted = sum(1 for f in manifest.get("files") or []
                           if f.get("sha256_original") != f.get("sha256_redacted_copy"))
            entry.update(files_listed=listed, files_hash_mismatch=bad,
                         files_missing=missing,
                         files_in_packet_not_in_manifest=sorted(
                             n[len(p["name"]) + 1:] for n in members - checked),
                         files_changed_by_redaction=redacted,
                         files_ok=(not bad and not missing))
            entry["ok"] = bool(entry["packet_hash_ok"] and entry["files_ok"])
            report["ok"] = report["ok"] and entry["ok"]
            report["packets"].append(entry)
        return report

    # -- reads -------------------------------------------------------------
    def list(self, session_id: str, prefix: str) -> list:
        name = self._session_packet[session_id]
        z = self._zip(name)
        head = f"{name}/{prefix}"
        return sorted(n[len(name) + 1:] for n in z.namelist()
                      if n.startswith(head) and not n.endswith("/"))

    def read(self, session_id: str, rel: str) -> bytes:
        if not is_decision_input(rel):
            if self._phase.current != PHASE_COMPARISON:
                raise LookaheadViolation(
                    RULE_T_OUTCOME, rel, "comparison pass only",
                    "outcome requested during the decision pass")
            self.outcome_reads += 1
        name = self._session_packet[session_id]
        return self._zip(name).read(f"{name}/{rel}")

    def read_json(self, session_id: str, rel: str):
        return json.loads(self.read(session_id, rel))

    def read_jsonl(self, session_id: str, rel: str) -> list:
        text = self.read(session_id, rel).decode("utf-8")
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def brain_files(self, session_id: str) -> list:
        day = session_day(session_id)
        return [f for f in self.list(session_id, f"data/ai_brain/{day}_")
                if f.endswith("_MNQ.json")]
