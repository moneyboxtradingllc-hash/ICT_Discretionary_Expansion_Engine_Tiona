"""LIQUIDITY-SWEEP-EPISODE-IDENTITY-1 — durable memory for OBSERVED TAPE FACTS.

The organism could say "I see a sweep" and, one candle later, "what sweep?".
`sweep_detected` is a two-candle predicate: it answers a PRESENT-TENSE question
truthfully and then the event is gone. PO3 asks a HISTORICAL causal question of
that same boolean, which it can never answer.

THE THIRD MEMORY CLASS. The organism already had two, and neither fits:

    htf_memory_engine   durable INTERPRETATION/synthesis. AUTHORITY_LEVEL is
                        hard-locked "context_only" and a test forbids any
                        execution/gate/decision module from reading it. That
                        lock is correct and is NOT weakened here.
    state/MarketMemory  recent snapshots, in-memory only, rolling 20. Forgets
                        on restart, and 20 scans is shorter than the candle
                        window it would need to outlive.
    THIS LEDGER         durable IMMUTABLE OBSERVED OCCURRENCES. Eligible to
                        inform execution-bearing causal reasoning in later
                        certified units, because a sweep at a price and a time
                        is a fact of the tape, not a view about it.

IT IS DELIBERATELY BORING. It records what objectively happened and then shuts
up. It never stores direction-as-opinion, PO3 qualification, confidence, setup
quality, objective selection, or candidate authority. Those are interpretations
and they belong to their own authorities downstream.

APPEND-ONLY AND IMMUTABLE. Birth facts never change:

    same id + identical immutable facts   -> idempotent, deduped
    same id + DIFFERENT immutable facts   -> integrity conflict; the ORIGINAL is
                                             preserved and the conflict surfaces

Last-write-wins would let the organism quietly rewrite market history, which for
an execution-bearing factual substrate is the one failure mode worth refusing.

PERSISTENCE HEALTH IS OBSERVABLE. A disk failure must not kill a live trading
process, but it must never be silently reported as healthy either: a failed
write leaves the ledger LEDGER_PERSISTENCE_DEGRADED, so a later unit can decide
whether historical authority is still provable. Absence of proof is not proof.

CONTRACT ISOLATION. Storage is keyed by the exact canonical contract, and a
store whose recorded contract disagrees with the requested one is refused. A
sweep on U26 may never be retrieved as causal evidence for Z26 merely because
both are MNQ.
"""
from __future__ import annotations

import json
import os
import tempfile

from market_data.causal_identity import (CAUSAL_IDENTITY_V1,
                                         CAUSAL_IDENTITY_V2, identity_of,
                                         resolve_version)

SCHEMA = "occurrence_ledger.v1"

DEFAULT_DIR = os.path.join("data", "occurrence_ledger")
DIR_ENV = "OCCURRENCE_LEDGER_DIR"

# ── health ───────────────────────────────────────────────────────────────────
HEALTHY = "LEDGER_HEALTHY"
DEGRADED = "LEDGER_PERSISTENCE_DEGRADED"
UNAVAILABLE = "LEDGER_UNAVAILABLE"          # could not be constructed at all
NOT_CONFIGURED = "LEDGER_NOT_CONFIGURED"    # deliberately absent (no exact contract)

# ── record outcomes ──────────────────────────────────────────────────────────
RECORDED = "recorded"
#: Accepted in memory, NOT durable. A failed write may never report `RECORDED`:
#: "the disk lost it" and "the tape never did it" must stay distinguishable, or
#: a later consumer reads absence-of-record as absence-of-event.
RECORDED_NOT_DURABLE = "recorded_not_durable"
#: A re-observed occurrence that was NEVER durable has just been persisted. It
#: is not a fresh record and it is emphatically not an ordinary duplicate.
DURABILITY_RECOVERED = "durability_recovered"
#: Reserved for occurrences PROVEN on disk. In-process presence is not enough.
DUPLICATE = "duplicate"
CONFLICT = "integrity_conflict"
REJECTED = "rejected"

#: The birth certificate. These may never change for a given occurrence_id.
#: Everything here is something the tape did, never something we concluded.
#: ACTIVE-PATH-STATE-1 (2026-08-24) extends this with the birth facts of the
#: structural event classes. `direction` here is a STRUCTURE BREAK'S OWN side as
#: the detector reported it -- a fact of the tape, not a view about it, and not
#: the same thing as `trade_direction`/`bias`, which stay forbidden below.
IMMUTABLE_FIELDS = ("event_type", "contract", "source_tf", "event_time",
                    "sweep_direction", "liquidity_side_taken", "swept_level",
                    "reclaimed", "reclaim_basis",
                    "direction", "broken_level", "side", "level", "old_level",
                    "swing_id")

#: THE OBSERVER'S CLOCKS. Under v1 these ARE part of the birth certificate,
#: because a v1 row IS an observation and `event_time` is the scan that made it.
#: Under v2 a row is a MARKET EVENT, which the market authored before anyone
#: looked -- so the same event re-observed on the next scan legitimately carries
#: a later `observed_at`, and treating that as an immutable-field violation
#: would make every second sighting an integrity conflict. The row keeps the
#: FIRST observation's stamps; later sightings are duplicates, not rewrites.
OBSERVATION_FIELDS = ("event_time", "observed_at")

#: The v2 birth certificate: what the MARKET did, plus the provenance that
#: authored the causal identity. The observer's clocks are deliberately absent.
V2_IMMUTABLE_FIELDS = tuple(
    f for f in IMMUTABLE_FIELDS if f not in OBSERVATION_FIELDS
) + ("source_bar_time", "registered_at", "old_swing_id", "old_registered_at")

#: Interpretations. If one of these ever appears in a submitted occurrence the
#: ledger refuses it rather than quietly storing an opinion as a fact.
FORBIDDEN_FIELDS = ("confidence", "setup_quality", "po3_qualified",
                    "recommendation", "objective", "candidate", "bias",
                    "trade_direction", "score", "tier")


def store_dir() -> str:
    return os.getenv(DIR_ENV) or DEFAULT_DIR


class LedgerIntegrityError(RuntimeError):
    """Raised only when a caller explicitly demands strictness."""


#: v2 stores are a SEPARATE FILE, never a rewrite of a v1 one.
#:
#: An in-place upgrade would have to reinterpret every historical
#: `occurrence_id` as though it had always meant "market event", which is
#: precisely the claim CAUSAL-OCCURRENCE-IDENTITY-1 disproves: a v1 store holds
#: fifteen rows for one 15m raid because fifteen scans each minted their own
#: identity. Collapsing those after the fact would be inventing history, and
#: leaving them keyed as-is inside a v2 store would put observation identities
#: and market identities in one namespace. Two files, two epistemologies, no
#: mixing.
V2_SUFFIX = ".causal_v2"


class OccurrenceLedger:
    """One durable append-only file of observed occurrences, per exact contract.

    CAUSAL-OCCURRENCE-IDENTITY-1 gives this store an explicit identity version.

        v1 (default)  keyed by `occurrence_id` -- WHICH OBSERVATION is this.
                      Byte-for-byte the behaviour that shipped, on the same
                      path, and what every production caller gets by not asking
                      for anything else.
        v2            keyed by `causal_event_key` -- WHICH MARKET EVENT is this.
                      A separate file, and `occurrence_id` is still recorded on
                      every row as the witness identity it has always been.

    THE VERSION CHOOSES THE AUTHORITY, and chooses it once. A store never tries
    one key and falls back to the other: that would dedup some rows by what the
    market did and others by when we happened to look, in one file, with nothing
    saying which rule produced which row.
    """

    def __init__(self, contract: str, *, directory: str = None,
                 causal_identity_version=None):
        self.causal_identity_version = resolve_version(causal_identity_version)
        self.contract = str(contract or "").strip()
        if not self.contract:
            # No production default. A ledger that invents a contract would
            # relabel foreign evidence as production evidence.
            raise ValueError("occurrence ledger requires an exact contract")
        self.directory = directory or store_dir()
        self._health = HEALTHY
        self._detail = ""
        self._conflicts: list = []
        self._records: dict = {}
        # TWO AXES THAT MAY NEVER COLLAPSE:
        #     present in process memory   (`_records`)
        #     PROVEN durably persisted    (`_durable`)
        # Without the second, a write that failed would be re-observed next scan,
        # find its own id already in `_records`, and report DUPLICATE -- a failed
        # write masquerading as a successful one, one scan later.
        self._durable: set = set()
        self._load()

    # ── storage ─────────────────────────────────────────────────────────────
    @property
    def path(self) -> str:
        safe = self.contract.replace(os.sep, "_").replace("/", "_")
        if self.causal_identity_version == CAUSAL_IDENTITY_V2:
            return os.path.join(self.directory, f"{safe}{V2_SUFFIX}.json")
        return os.path.join(self.directory, f"{safe}.json")

    def _key(self, occurrence) -> "str | None":
        """The ONE identity this store deduplicates by. Version decides."""
        return identity_of(occurrence, self.causal_identity_version)

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as fh:
                blob = json.load(fh)
        except Exception as exc:            # noqa: BLE001
            self._degrade(f"unreadable store: {type(exc).__name__}")
            return
        stored = str((blob or {}).get("contract") or "")
        if stored and stored != self.contract:
            # Never silently adopt another contract's history.
            self._degrade(f"store contract {stored!r} != {self.contract!r}")
            return
        # NEVER READ A STORE UNDER THE WRONG IDENTITY LAW. A file whose keys are
        # observation identities, loaded as though they were market identities,
        # would report DUPLICATE for events it has never actually seen -- a
        # silent history rewrite, which is the one failure this store exists to
        # refuse. An absent stamp means a file written before versions existed,
        # which is a v1 file by definition.
        stored_version = (blob or {}).get("causal_identity_version",
                                          CAUSAL_IDENTITY_V1)
        try:
            stored_version = int(stored_version)
        except (TypeError, ValueError):
            stored_version = None
        if stored_version != self.causal_identity_version:
            self._degrade(
                f"store causal identity version {stored_version!r} != "
                f"{self.causal_identity_version!r}")
            return
        records = (blob or {}).get("occurrences")
        if isinstance(records, dict):
            self._records = {k: v for k, v in records.items() if isinstance(v, dict)}
            # Read back off disk IS the proof of durability.
            self._durable = set(self._records)

    def _persist(self) -> bool:
        blob = {"schema": SCHEMA, "contract": self.contract,
                # Stamped so the file states its own identity law rather than
                # relying on a reader to remember which one wrote it.
                "causal_identity_version": self.causal_identity_version,
                "occurrences": self._records}
        try:
            os.makedirs(self.directory, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.directory, prefix=".ledger-")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(blob, fh, indent=2, sort_keys=True, default=str)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except Exception as exc:            # noqa: BLE001 — never kill the scan
            self._degrade(f"write failed: {type(exc).__name__}: {str(exc)[:120]}")
            return False
        return True

    def _degrade(self, detail: str) -> None:
        """STICKY BY DESIGN. A later write succeeding does not prove the store
        is whole again -- whatever failed may have been lost, and silently
        flipping back to HEALTHY would claim a completeness this object cannot
        demonstrate. No automatic recovery semantics are invented here; a
        consumer that needs proven-good memory must construct a fresh ledger and
        see for itself."""
        self._health = DEGRADED
        self._detail = detail

    # ── the contract with callers ───────────────────────────────────────────
    def record(self, occurrence: dict) -> dict:
        """Append one observed occurrence. Idempotent; never overwrites."""
        def out(outcome, detail="", key=None):
            return {"schema": SCHEMA, "outcome": outcome, "detail": detail,
                    "occurrence_id": (occurrence or {}).get("occurrence_id"),
                    # The identity this store actually keyed by. Reported so a
                    # caller never has to infer which law was in force.
                    "identity_key": key,
                    "causal_identity_version": self.causal_identity_version,
                    "health": self._health}

        if not isinstance(occurrence, dict):
            return out(REJECTED, "not a mapping")
        if not occurrence.get("occurrence_id"):
            # The WITNESS identity is required under both versions: a row that
            # cannot say which observation produced it is not a witness.
            return out(REJECTED, "an occurrence with no identity is not an occurrence")
        oid = self._key(occurrence)
        if not oid:
            return out(REJECTED,
                       "causal identity could not be established; an event that "
                       "cannot say what it is may not enter an append-only store")
        present = [f for f in FORBIDDEN_FIELDS if f in occurrence]
        if present:
            return out(REJECTED, f"interpretation is not a tape fact: {present}")
        if occurrence.get("contract") and occurrence["contract"] != self.contract:
            return out(REJECTED,
                       f"contract {occurrence['contract']!r} != ledger {self.contract!r}")

        immutable = (V2_IMMUTABLE_FIELDS
                     if self.causal_identity_version == CAUSAL_IDENTITY_V2
                     else IMMUTABLE_FIELDS)
        existing = self._records.get(oid)
        if existing is not None:
            differing = [f for f in immutable
                         if existing.get(f) != occurrence.get(f)]
            if differing:
                # HISTORY IS NOT REWRITABLE. Keep the original, surface the clash.
                clash = {"occurrence_id": oid, "identity_key": oid,
                         "differing_fields": differing,
                         "stored": {f: existing.get(f) for f in differing},
                         "submitted": {f: occurrence.get(f) for f in differing}}
                self._conflicts.append(clash)
                return dict(out(CONFLICT, f"immutable fields differ: {differing}",
                                key=oid), conflict=clash)
            if oid in self._durable:
                return out(DUPLICATE, "already recorded and proven durable", key=oid)
            # KNOWN, BUT NEVER DURABLE. Re-observation is a chance to make it so
            # rather than an excuse to call it a duplicate.
            if self._persist():
                self._durable.add(oid)
                return out(DURABILITY_RECOVERED,
                           "was in memory only; durability now proven", key=oid)
            return out(RECORDED_NOT_DURABLE,
                       "still in memory only; durable persistence FAILED again",
                       key=oid)

        self._records[oid] = dict(occurrence)
        if self._persist():
            self._durable.add(oid)
            return out(RECORDED, key=oid)
        return out(RECORDED_NOT_DURABLE,
                   "accepted in memory; durable persistence FAILED — this "
                   "occurrence will not survive a restart", key=oid)

    def is_durable(self, occurrence_id: str) -> bool:
        """Proven on disk, not merely present in this process."""
        return occurrence_id in self._durable

    def occurrences(self, *, event_type: str = None,
                    source_tf: str = None) -> list:
        """Every recorded occurrence, newest last by event_time."""
        rows = list(self._records.values())
        if event_type:
            rows = [r for r in rows if r.get("event_type") == event_type]
        if source_tf:
            rows = [r for r in rows if r.get("source_tf") == source_tf]
        return sorted(rows, key=lambda r: str(r.get("event_time") or ""))

    def get(self, occurrence_id: str) -> "dict | None":
        row = self._records.get(occurrence_id)
        return dict(row) if isinstance(row, dict) else None

    def health(self) -> dict:
        """Truthful persistence status. Absence of proof is not proof."""
        return {"schema": SCHEMA, "status": self._health, "detail": self._detail,
                "contract": self.contract, "path": self.path,
                "recorded": len(self._records),
                # In-memory count is not a durability claim.
                "durable": len(self._durable),
                "not_durable": sorted(set(self._records) - self._durable),
                "integrity_conflicts": len(self._conflicts),
                "conflicts": list(self._conflicts)}
