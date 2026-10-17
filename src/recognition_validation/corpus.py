"""Immutable corpus, content-addressed artifacts and the release stream.

The corpus names sessions and their original/derived artifacts by relative
path, byte length and SHA-256 of the original bytes. A release is one
versioned availability of one bar (release/v1): its bar-open identity, when
it became available, whether its settlement is proven, and which earlier
version it supersedes. At decision clock t only releases available by t are
visible, and each bar shows its latest visible version -- a correction is
never backfilled into an earlier snapshot.

Nothing here selects a recognition benchmark: selection is the owner's
(D01). Engineering may use every lawful fixture and must say what each one
can and cannot support (contract 05 evidence classes).
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from recognition_validation import contracts as C

EVIDENCE_CLASSES = ("CONSTRUCTED", "REPOSITORY_RECORDED", "APPROVED_ARCHIVE", "FINAL_HISTORY_ONLY", "UNKNOWN")
LAYERS = ("chart", "quotes", "cognition_archive", "memory_seed", "news", "recognition_benchmark")
REPOSITORY_FIXTURE_CLASSIFICATION = "REPOSITORY_ARTIFACT_NOT_AUTOMATIC_RECOGNITION_TRUTH"


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Release:
    sequence: int
    session_id: str
    contract_id: str
    bar_open: datetime
    available_at: datetime
    settled_at: datetime | None
    version: int
    supersedes: int | None
    bar: dict

    def candle(self) -> dict:
        """The production candle dict, a fresh copy per call."""
        bar = self.bar
        return {"timestamp": self.bar_open.isoformat(), "open": bar["open"], "high": bar["high"],
                "low": bar["low"], "close": bar["close"], "volume": bar["volume"],
                "contract": bar["contract"]}


@dataclass
class ReleaseStream:
    """Ordered, validated releases for one session and one exact contract."""

    session_id: str
    contract_id: str
    releases: list = field(default_factory=list)

    @classmethod
    def from_documents(cls, documents, *, session_id: str, contract_id: str) -> "ReleaseStream":
        stream = cls(session_id=session_id, contract_id=contract_id)
        versions: dict = {}
        last_sequence, last_available = None, None
        for index, doc in enumerate(documents):
            at = f"/releases/{index}"
            try:
                C.validate(doc)
            except C.ContractError as exc:
                raise C.ContractError(exc.code, at + exc.pointer, detail=exc.detail) from exc
            C.require(C.kind_of(doc) == "release", "NOT_A_RELEASE", at)
            C.require(doc["session_id"] == session_id, "RELEASE_SESSION_MISMATCH", at + "/session_id")
            C.require(doc["contract_id"] == contract_id, "MIXED_CONTRACT", at + "/contract_id")
            C.require(last_sequence is None or doc["sequence"] > last_sequence, "RELEASE_SEQUENCE_NOT_INCREASING",
                      at + "/sequence")
            available = C.instant(doc["available_at_utc"], at)
            C.require(last_available is None or available >= last_available, "RELEASE_ARRIVAL_OUT_OF_ORDER",
                      at + "/available_at_utc")
            bar_open = C.instant(doc["bar_open_utc"], at)
            C.require(bar_open.second == 0 and bar_open.microsecond == 0, "BAR_OPEN_NOT_MINUTE", at)
            prior = versions.setdefault(bar_open, [])
            C.require(doc["version"] not in prior, "DUPLICATE_BAR_VERSION", at + "/version")
            if prior:
                C.require(doc["supersedes_version"] in prior and doc["version"] > max(prior),
                          "HIDDEN_OR_UNORDERED_REVISION", at + "/supersedes_version")
            else:
                C.require(doc["supersedes_version"] is None, "SUPERSEDES_UNKNOWN_VERSION", at + "/supersedes_version")
            prior.append(doc["version"])
            settled = C.instant(doc["settled_at_utc"], at) if doc["settled_at_utc"] else None
            stream.releases.append(Release(
                sequence=doc["sequence"], session_id=session_id, contract_id=contract_id, bar_open=bar_open,
                available_at=available, settled_at=settled, version=doc["version"],
                supersedes=doc["supersedes_version"], bar=copy.deepcopy(doc["bar"])))
            last_sequence, last_available = doc["sequence"], available
        return stream

    def visible(self, t: datetime) -> list[Release]:
        """Latest version of each bar whose release is available by t."""
        C.require(t.tzinfo is not None, "TIMEZONE_REQUIRED", "/clock")
        latest: dict = {}
        for release in self.releases:
            if release.available_at <= t:
                latest[release.bar_open] = release
        return [latest[key] for key in sorted(latest)]

    def candles_at(self, t: datetime, lookback: int | None = None) -> list[dict]:
        rows = [release.candle() for release in self.visible(t)]
        return rows if lookback is None else rows[-lookback:]

    def has_revisions(self) -> bool:
        return any(release.supersedes is not None for release in self.releases)


def release_documents_from_tape(tape, *, session_id: str, contract_id: str, source_artifact: dict,
                                lag_seconds: int = 0, classification: str = "CONSTRUCTED") -> list[dict]:
    """One release/v1 per settled bar, available when its minute settles."""
    docs = []
    for index, bar in enumerate(tape):
        opened = datetime.fromisoformat(bar["timestamp"]).astimezone(timezone.utc)
        settled = opened + timedelta(minutes=1)
        available = settled + timedelta(seconds=lag_seconds)
        docs.append({
            "schema_version": "release/v1",
            "document_id": f"{session_id}:release:{index}",
            "provenance": {"classification": classification, "author_role": "ENGINEERING_GENERATOR",
                           "source_refs": [source_artifact["path"]],
                           "notes": "Release stream derived from the referenced tape; not provider evidence."},
            "session_id": session_id, "sequence": index, "contract_id": contract_id,
            "bar_open_utc": _iso(opened), "available_at_utc": _iso(available),
            "settled_at_utc": _iso(settled), "settlement_proven": True,
            "version": 1, "supersedes_version": None, "source_artifact": dict(source_artifact),
            "bar": {"timestamp": _iso(opened), "contract": contract_id,
                    "open": float(bar["open"]), "high": float(bar["high"]), "low": float(bar["low"]),
                    "close": float(bar["close"]), "volume": float(bar.get("volume", 0) or 0)},
        })
    return docs


def write_artifact(root, relpath: str, data: bytes, origin: str) -> dict:
    """Write bytes under root (refusing overwrite) and return its reference."""
    rel = C.safe_relative_path(relpath)
    target = Path(root) / Path(*rel.parts)
    C.require(not target.exists(), "ARTIFACT_OVERWRITE_REFUSED", "/" + relpath)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {"path": relpath, "sha256": C.sha256_hex(data), "bytes": len(data), "origin": origin}


def admissibility(session: dict, *, artifacts_verified: bool) -> dict:
    """Reason-coded layer admissibility: ELIGIBLE / PARTIAL / EXCLUDED / UNPROVEN.

    Schema validity is not eligibility, and a contiguous chart proves nothing
    about quotes or cognition."""
    out = {}
    chart_reasons = []
    if not artifacts_verified:
        chart_reasons.append("artifact_digests_unverified")
    if session["settlement"]["status"] != "PROVEN":
        chart_reasons.append("settlement_" + session["settlement"]["status"].lower())
    if session["gaps"] or session["missing_intervals"]:
        chart_reasons.append("declared_gaps_or_missing_intervals")
    out["chart"] = ("ELIGIBLE" if not chart_reasons else
                    "UNPROVEN" if not artifacts_verified else "PARTIAL", chart_reasons)
    out["quotes"] = (("PARTIAL", ["quotes_present_but_not_venue_truth"]) if session["quotes"]
                     else ("UNPROVEN", ["no_independent_quote_archive"]))
    out["cognition_archive"] = (("PARTIAL", ["recorded_cognition_needs_exact_association"])
                                if session["brain_records"] else ("UNPROVEN", ["no_recorded_cognition"]))
    out["memory_seed"] = (("PARTIAL", ["sealed_seed_supplied"]) if session["memory_seed"]
                          else ("UNPROVEN", ["empty_memory_counterfactual"]))
    out["news"] = (("PARTIAL", ["news_supplied"]) if session["news"] else ("UNPROVEN", ["no_news_feed"]))
    out["recognition_benchmark"] = ("UNPROVEN", ["owner_selection_D01_absent"])
    return out


@dataclass
class LoadedSession:
    entry: dict
    stream: ReleaseStream | None
    artifacts_verified: bool
    layers: dict


@dataclass
class Corpus:
    document: dict
    file_digest: str | None
    root: Path
    sessions: dict

    @property
    def digest(self) -> str:
        return C.seal_digest(self.document)


def load_corpus(path, *, root=None) -> Corpus:
    """Validate the manifest, verify every referenced artifact, load releases."""
    document, kind, file_digest = C.validate_file(path)
    C.require(kind == "corpus", "NOT_A_CORPUS", "/schema_version")
    base = Path(root) if root is not None else Path(path).resolve().parent
    sessions = {}
    for index, entry in enumerate(document["sessions"]):
        at = f"/sessions/{index}"
        verified = True
        for name in ("original", "derived", "availability_events", "quotes", "brain_records", "memory_seed", "news"):
            ref = entry[name]
            if ref is not None:
                C.verify_artifact(ref, base, f"{at}/{name}")
        stream = None
        if entry["availability_events"] is not None:
            data = C.verify_artifact(entry["availability_events"], base, at + "/availability_events")
            releases = C.loads_strict(data.decode("utf-8"), pointer=at + "/availability_events")
            C.require(isinstance(releases, list), "RELEASES_NOT_A_LIST", at + "/availability_events")
            stream = ReleaseStream.from_documents(releases, session_id=entry["session_id"],
                                                  contract_id=entry["contract_id"])
            if entry["history_track"] == "FINAL_HISTORY_ONLY":
                C.require(not stream.has_revisions(), "FINAL_HISTORY_WITH_REVISIONS", at + "/history_track")
        else:
            verified = entry["original"] is not None
        sessions[entry["session_id"]] = LoadedSession(entry=entry, stream=stream, artifacts_verified=verified,
                                                      layers=admissibility(entry, artifacts_verified=verified))
    return Corpus(document=document, file_digest=file_digest, root=base, sessions=sessions)


def repository_fixture_inventory(repo_root) -> list[dict]:
    """Every tracked JSON fixture under tests/fixtures with its original-byte digest."""
    rows = []
    for path in sorted((Path(repo_root) / "tests" / "fixtures").glob("*.json")):
        data = path.read_bytes()
        rows.append({"path": path.relative_to(repo_root).as_posix(), "sha256": C.sha256_hex(data),
                     "bytes": len(data), "classification": REPOSITORY_FIXTURE_CLASSIFICATION})
    return rows


def constructed_session_entry(*, session_id: str, contract_id: str, market_date: str, tape: list,
                              original: dict, releases: dict, warmup_end: str, notes: str) -> dict:
    """A corpus/v1 session for a CONSTRUCTED tape: mechanics only, never recognition truth."""
    first = datetime.fromisoformat(tape[0]["timestamp"]).astimezone(timezone.utc)
    end = datetime.fromisoformat(tape[-1]["timestamp"]).astimezone(timezone.utc) + timedelta(minutes=1)
    warm = datetime.fromisoformat(warmup_end).astimezone(timezone.utc)
    return {
        "session_id": session_id, "instrument": "MNQ", "contract_id": contract_id,
        "market_date": market_date, "timezone": "America/New_York",
        "session_window": {"start_utc": _iso(first), "end_utc": _iso(end)},
        "warmup_window": {"start_utc": _iso(first), "end_utc": _iso(warm)},
        "scored_window": {"start_utc": _iso(warm), "end_utc": _iso(end)},
        "timestamp_semantics": "BAR_OPEN_UTC",
        "settlement": {"status": "PROVEN", "policy_ref": "CONSTRUCTED: every bar settles one minute after open",
                       "reason": notes},
        "provider": None, "original": original, "derived": None, "availability_events": releases,
        "history_track": "CONSTRUCTED_RELEASES", "gaps": [], "revisions": [], "missing_intervals": [],
        "quotes": None, "brain_records": None, "brain_fingerprint": None, "fingerprint_evidence_ref": None,
        "fingerprint_unknown_reason": "CONSTRUCTED tape: no recorded cognition exists",
        "memory_seed": None, "news": None, "partition": "ENGINEERING", "eligibility": "PARTIAL",
        "exclusion_reasons": ["CONSTRUCTED: mechanics only, never a recognition benchmark",
                              "no independent quote archive", "empty memory counterfactual"],
    }


def build_constructed_corpus(root, *, session_id: str, contract_id: str, market_date: str, tape: list,
                             warmup_end: str, notes: str, sealed_at: str) -> Path:
    """Write tape, releases and a sealed ENGINEERING_ONLY corpus under a fresh root."""
    root = Path(root)
    C.require(not (root / "corpus.json").exists(), "OUTPUT_ROOT_REUSE", "/corpus.json")
    tape_bytes = json.dumps(tape, sort_keys=True, indent=1).encode("utf-8")
    original = write_artifact(root, f"tapes/{session_id}.json", tape_bytes, "CONSTRUCTED")
    docs = release_documents_from_tape(tape, session_id=session_id, contract_id=contract_id,
                                       source_artifact=original)
    releases = write_artifact(root, f"releases/{session_id}.json",
                              json.dumps(docs, sort_keys=True, indent=1).encode("utf-8"), "CONSTRUCTED")
    corpus = {
        "schema_version": "corpus/v1", "document_id": f"CONSTRUCTED-{session_id}",
        "provenance": {"classification": "CONSTRUCTED", "author_role": "ENGINEERING_GENERATOR",
                       "source_refs": [original["path"]], "notes": notes},
        "selection_state": "ENGINEERING_ONLY", "owner_decision_ref": None,
        "sessions": [constructed_session_entry(session_id=session_id, contract_id=contract_id,
                                               market_date=market_date, tape=tape, original=original,
                                               releases=releases, warmup_end=warmup_end, notes=notes)],
        "seal": None,
    }
    corpus["seal"] = {"sha256": C.seal_digest(corpus), "sealed_at": sealed_at,
                      "sealer_ref": "ENGINEERING-CONSTRUCTED (not an owner seal)"}
    C.validate(corpus)
    path = root / "corpus.json"
    path.write_bytes(json.dumps(corpus, sort_keys=True, indent=1).encode("utf-8"))
    return path
