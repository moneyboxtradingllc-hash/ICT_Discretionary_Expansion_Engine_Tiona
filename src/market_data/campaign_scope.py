"""Stage 3C-2: selected campaign custody, published in SHADOW only.

The owner-selected initial policy is D1=a, roles5m/15m, K=1,
D3=B/STRICT/INDEPENDENT_SUPPORTING_LIFE, D5=a, D6=a. Neither a
catalog row nor pending/active shadow custody grants execution authority.
No persistence restores custody; reads authenticate actual process ownership.
"""
from __future__ import annotations

import copy
import hashlib
import json
import uuid
import weakref

from market_data import campaign_premise as CP

SCHEMA = "campaign_scope_custody/v1"
CATALOG_SCHEMA = "campaign_premise_catalog/v1"
POLICY = {"proposer": "primary_llm", "roles": ["5m", "15m"], "k": 1,
          "scope": "B", "time": "STRICT", "bearing": "INDEPENDENT_SUPPORTING_LIFE",
          "amendment": False, "unknown": "retire"}
_PUBLICATIONS = weakref.WeakKeyDictionary()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode("utf-8")).hexdigest()


def _context(snapshot, *, revision, contract, session, process, lineage):
    return {"cutoff": CP._instant(snapshot.get("timestamp")),
            "history_revision": revision, "contract_id": contract,
            "market_session": session, "process_session_id": process,
            "custody_lineage": lineage}


def _fact_seal(snapshot):
    return _digest({k: snapshot.get(k) for k in
                    ("timestamp", "contract_id", "derived_state", "active_path_state",
                     "protected_swings", "campaign_premise_shadow")})


def _certificate(cert):
    return {"status": cert.get("status"), "covered_buckets": cert.get("covered_buckets"),
            "settled_through": cert.get("settled_through"),
            "tip_digest": _digest([cert.get("tip_bucket_open"),
                                   cert.get("tip_member_digests")]),
            "reason": cert.get("reason"), "failure_bucket": cert.get("failure_bucket")}


def _pending_seal(pending):
    return _digest({k: (v.as_dict() if k == "life" else v)
                    for k, v in pending.items() if k != "seal"})


def _raids(life, ledger_rows, cutoff):
    """Use only M1's conflict-checked canonical links, preserving every reference."""
    ids = set(life.get("sweep_occurrence_ids") or ())
    refs = {}
    for row in ledger_rows:
        oid = row.get("occurrence_id")
        if (oid in ids and row.get("contract") == life["contract_id"]
                and CP._canonical_sweep(row, life["contract_id"])
                and CP._available(row, cutoff) and not CP._association_withheld(row, cutoff)):
            refs[oid] = {"canonical_sweep_id": oid,
                         "event_time": CP._instant(row.get("event_time")),
                         "association_observed_at": CP._instant(
                             (row.get("protected_swing_lifetime") or {}).get("observed_at"))}
    return sorted(refs.values(), key=lambda x: (x["event_time"], x["canonical_sweep_id"]))


def campaign_scope_proof(snapshot, row, *, from_direction=None):
    """D3-B strict: a selected supporting life raids AFTER proved incumbent death.

    Establishment still requires a real local transfer from its own local
    predecessor; no campaign predecessor or campaign failure is invented.
    """
    from ai_brain.narrative_continuity import _transfer_proof
    cutoff = CP._instant(snapshot.get("timestamp"))
    to = row.get("supports")
    before = from_direction or ("bearish" if to == "bullish" else "bullish")
    path = snapshot.get("active_path_state") or {}
    if (path.get("contract_id") != snapshot.get("contract_id")
            or path.get("session") != CP._session_of(snapshot.get("timestamp"))):
        return None, "lt_context_unavailable"
    proof = _transfer_proof(path, before, to)
    if proof is None or cutoff is None:
        return None, "lt_not_verified"
    died = proof["incumbent_invalidation"]
    origin = proof["authoritative_opposing_origin"]
    for value in [died.get("at"), origin.get("at")]:
        stamp = CP._instant(value)
        if stamp is None or stamp > cutoff:
            return None, "lt_context_unavailable"
    for event in [died, origin]:
        if event.get("observed_at") is not None:
            stamp = CP._instant(event["observed_at"])
            if stamp is None or stamp > cutoff:
                return None, "lt_context_unavailable"
    if not origin.get("occurrence_id"):
        return None, "lt_origin_unavailable"
    death = CP._instant(died.get("settled_edge_time"))
    source = "settled_edge"
    if death is None or death > cutoff:
        death = CP._instant(died.get("source_bar_time")) if died.get("source_tf") == "1m" else None
        source = "1m_source"
    if death is None or death > cutoff:
        return None, "d3_death_time_unestablished"
    evaluated = [{**ref, "R": ref["event_time"],
                  "passes": bool(ref["event_time"] and death < ref["event_time"] <= cutoff)}
                 for ref in row.get("raids", ())]
    passing = [ref for ref in evaluated if ref["passes"]]
    if not passing:
        return None, "d3_raid_not_after_death"
    cited = min(passing, key=lambda x: (x["R"], x["canonical_sweep_id"]))
    result = {"route": "B", "from": before, "to": to,
              "lt_origin_occurrence_id": origin["occurrence_id"],
              "raid_references": evaluated, "cited_raid_id": cited["canonical_sweep_id"],
              "R": cited["R"], "D": death, "D_source": source,
              "local_transfer_proof": copy.deepcopy(proof)}
    result["proof_id"] = "sp:" + _digest(result)
    return result, None


def build_campaign_premise_catalog(snapshot, facts, ledger_rows, context, observed_watches=()):
    rows = []
    if facts.get("status") == CP.AVAILABLE:
        for life in facts.get("lives", ()):
            ref = CP.life_ref(life)
            observation = next((r for r in observed_watches if CP.life_ref(r) == ref), None)
            cert = (observation or life).get("certificate") or {}
            eligibility = CP.selection_eligibility(
                life, cert, protected_by_timeframe=(snapshot.get("protected_swings") or {}).get("by_timeframe") or {},
                ledger_rows=ledger_rows, cutoff=context["cutoff"])
            if (eligibility["eligible"] is not True
                    or life.get("source_tf") not in POLICY["roles"]
                    or cert.get("status") != CP.INTACT
                    or cert.get("covered_buckets", 0) < POLICY["k"]):
                continue
            raids = _raids(life, ledger_rows, context["cutoff"])
            row = {"life": ref.as_dict(), "supports": "bullish" if ref.side == "low" else "bearish",
                   "certificate": _certificate(cert), "raids": raids}
            row["premise_candidate_id"] = "pc:" + _digest(
                {"context": context, "life": ref.as_dict()})[:24]
            proof, reason = campaign_scope_proof(snapshot, row)
            row["d3"] = {"route_b": proof, "reason": reason}
            rows.append(row)
    rows.sort(key=lambda x: x["premise_candidate_id"])
    result = {"schema": CATALOG_SCHEMA, "context": copy.deepcopy(context), "rows": rows}
    result["digest"] = _digest({"context": context, "rows": rows})
    return result


def _read_publication(snapshot):
    """Never create a binding from a label, token, context or caller dictionary."""
    for custody, publication in list(_PUBLICATIONS.items()):
        if publication["snapshot"] is not snapshot:
            continue
        owner = publication["owner"]()
        if owner is None or getattr(owner, "campaign_scope_custody", None) is not custody:
            return None
        state = snapshot.get("derived_state") or {}
        context = custody._context
        if (not context or state.get("current") is not True
                or not owner.derived_state_is_current()
                or owner._history.revision != context["history_revision"]
                or owner.contract_id != context["contract_id"]
                or owner.session_id != context["process_session_id"]
                or _fact_seal(snapshot) != publication["fact_seal"]
                or snapshot.get("campaign_scope_custody_shadow") != custody._projection
                or snapshot.get("campaign_premise_catalog") != custody._catalog):
            return None
        return custody
    return None


def read_current_campaign_scope(snapshot):
    try:
        custody = _read_publication(snapshot)
        if custody is not None:
            return copy.deepcopy(custody._projection)
    except (TypeError, ValueError, AttributeError):
        pass
    return {"schema": SCHEMA, "authority": "none", "status": "UNAVAILABLE",
            "reason": "producer_publication_unavailable", "campaign": None}


def current_campaign_catalog(snapshot):
    try:
        custody = _read_publication(snapshot)
        return copy.deepcopy(custody._catalog) if custody is not None else None
    except (TypeError, ValueError, AttributeError):
        return None


class CampaignScopeCustody:
    """One private process-local queue and bound life; reads never mutate them."""

    def __init__(self):
        self._lineage = uuid.uuid4().hex
        self._chains = {}
        self._context = self._catalog = self._projection = None
        self._campaign = self._pending = self._transition = None
        self._proposal_at = self._proposal_digest = None
        self._conflicted = False
        self._brain_fingerprint = None
        self._observation_args = None
        self._pending_disposition = None
        self._cutoff_fact_conflict = False

    def reset(self, reason="custody_reset"):
        self._retire(reason)
        self._pending = None
        self._chains = {}
        self._context = self._catalog = self._projection = None
        self._observation_args = None
        self._cutoff_fact_conflict = False
        self._lineage = uuid.uuid4().hex
        _PUBLICATIONS.pop(self, None)

    def _retire(self, reason, cutoff=None, failure=None):
        if self._campaign is not None:
            self._transition = {"kind": "retire", "reason": reason, "cutoff": cutoff,
                                "predecessor_campaign_id": self._campaign["campaign_id"],
                                "predecessor_direction": self._campaign["direction"],
                                "successor_campaign_id": None, "failure_bucket": failure}
        self._campaign = None

    def _void(self, reason, cutoff):
        if self._pending:
            self._pending_disposition = {"kind": "void", "reason": reason, "cutoff": cutoff,
                                         "proposal_id": self._pending["proposal_id"]}
            if not (self._transition and self._transition.get("cutoff") == cutoff
                    and self._transition.get("kind") == "retire"):
                self._transition = copy.deepcopy(self._pending_disposition)
        self._pending = None

    def advance(self, *, owner, snapshot, settled_1m, ledger_rows,
                history_revision, contract_id, market_session, available=True):
        """S1-S5 before cognition; S7 cannot change this frozen publication."""
        from ai_brain.production_model import brain_contract_fingerprint
        context = _context(snapshot, revision=history_revision, contract=contract_id,
                           session=market_session, process=owner.session_id, lineage=self._lineage)
        stamp = context["cutoff"]
        previous = self._context
        if previous and (any(previous[k] != context[k] for k in
                             ("history_revision", "contract_id", "market_session", "process_session_id"))
                         or stamp is None or stamp < previous["cutoff"]):
            self._retire("context_boundary", stamp)
            self._void("context_boundary", stamp)
            self._chains = {}
            self._proposal_at = self._proposal_digest = None
            self._lineage = uuid.uuid4().hex
            context["custody_lineage"] = self._lineage
        elif previous and stamp == previous["cutoff"]:
            prior_publication = _PUBLICATIONS.get(self)
            if (self._cutoff_fact_conflict or (prior_publication
                    and _fact_seal(snapshot) != prior_publication["fact_seal"])):
                # Revocation is sticky for this cutoff, including retries with
                # the old facts. Unknown custody cannot survive into activation.
                self._cutoff_fact_conflict = True
                self._retire("premise_observation_unknown", stamp)
                self._void("conflicting_same_cutoff_facts", stamp)
                self._chains = {}
                _PUBLICATIONS.pop(self, None)
                snapshot["campaign_scope_custody_shadow"] = {
                    "schema": SCHEMA, "authority": "none", "status": "UNAVAILABLE",
                    "reason": "conflicting_same_cutoff_facts", "campaign": None}
                snapshot.pop("campaign_premise_catalog", None)
                return copy.deepcopy(snapshot["campaign_scope_custody_shadow"])
            # No new facts/proposal can revise the already-published cutoff.
            snapshot["campaign_premise_catalog"] = copy.deepcopy(self._catalog)
            snapshot["campaign_scope_custody_shadow"] = copy.deepcopy(self._projection)
            self._register(owner, snapshot)
            return copy.deepcopy(self._projection)
        self._cutoff_fact_conflict = False
        self._context = context
        _PUBLICATIONS.pop(self, None)
        watched = []
        for record in (self._campaign, self._pending):
            if record and record["life"] not in watched:
                watched.append(record["life"])
        self._observation_args = copy.deepcopy(dict(
            snapshot=snapshot, settled_1m=settled_1m, ledger_rows=ledger_rows,
            history_revision=history_revision, contract_id=contract_id,
            market_session=market_session, cutoff=stamp))
        facts = snapshot.get("campaign_premise_shadow") or {}
        available = bool(available and facts.get("status") == CP.AVAILABLE and stamp
                         and facts.get("cutoff") == stamp
                         and facts.get("history_revision") == history_revision
                         and facts.get("contract_id") == contract_id
                         and facts.get("market_session") == market_session)
        observed_watches = self._observe_watches(watched)
        if self._campaign:
            observed = next((r for r in observed_watches
                             if CP.life_ref(r) == self._campaign["life"]), None)
            cert = (observed or {}).get("certificate") or {}
            if not available or cert.get("status") != CP.INTACT:
                failed = available and cert.get("status") == CP.FAILED
                self._retire("premise_failed" if failed else "premise_observation_unknown",
                             stamp, cert.get("failure_bucket") if failed else None)
            else:
                self._campaign["certificate"] = _certificate(cert)
        self._catalog = build_campaign_premise_catalog(snapshot, facts if available else {},
                                                       ledger_rows, context, observed_watches)
        if self._pending:
            pending = self._pending
            if not available:
                self._void("producer_facts_unavailable", stamp)
            elif stamp > pending["context"]["cutoff"]:
                self._activate(snapshot, pending, stamp)
        self._refresh_watches()
        self._catalog["selection_context"] = {
            "state": "ACTIVE" if self._campaign else "UNBOUND",
            "direction": self._campaign["direction"] if self._campaign else None}
        self._catalog["digest"] = _digest({k: self._catalog[k] for k in
                                           ("context", "rows", "selection_context")})
        self._brain_fingerprint = brain_contract_fingerprint()
        self._projection = {"schema": SCHEMA, "authority": "none",
                            "status": "AVAILABLE" if available else "UNAVAILABLE",
                            "reason": None if available else "producer_facts_unavailable",
                            "context": copy.deepcopy(context),
                            "state": "ACTIVE" if self._campaign else "UNBOUND",
                            "campaign": self._public_campaign(),
                            "pending": self._public_pending(),
                            "last_transition": copy.deepcopy(self._transition),
                            "pending_disposition": copy.deepcopy(self._pending_disposition),
                            "retained_chains": len(self._chains)}
        self._projection["digest"] = _digest(self._projection)
        snapshot["campaign_premise_catalog"] = copy.deepcopy(self._catalog)
        snapshot["campaign_scope_custody_shadow"] = copy.deepcopy(self._projection)
        self._register(owner, snapshot)
        return copy.deepcopy(self._projection)

    def _register(self, owner, snapshot):
        _PUBLICATIONS[self] = {"owner": weakref.ref(owner), "snapshot": snapshot,
                               "fact_seal": _fact_seal(snapshot)}

    def _refresh_watches(self):
        watched = []
        for record in (self._campaign, self._pending):
            if record and record["life"] not in watched:
                watched.append(record["life"])
        self._observe_watches(watched)

    def _observe_watches(self, watched):
        """Reuse M1 inventory; measure ONLY the <=2 explicitly retained lives.

        Watched-reference validation and certificate laws are the existing M1
        helpers, unchanged. Slot presence and NEW eligibility are not survival.
        """
        args = self._observation_args
        assert len(watched) <= CP.MAX_WATCHED_LIVES
        rows = [r for r in args["ledger_rows"] if r.get("contract") == args["contract_id"]
                and CP._session_of(r.get("event_time")) == args["market_session"]]
        observed, kept = [], {}
        for life in watched:
            refusal = CP._watch_refusal(life, contract_id=args["contract_id"],
                                       market_session=args["market_session"],
                                       cutoff=args["cutoff"], rows=rows)
            if refusal is not None:
                cert = CP._refused_certificate(life, refusal, args["history_revision"], args["cutoff"])
            else:
                cert = CP.apply_tracker_witness(CP.observe_life(
                    life, settled_1m=args["settled_1m"], history_revision=args["history_revision"],
                    contract_id=args["contract_id"], cutoff=args["cutoff"],
                    retained=self._chains.get(life.identity())),
                    CP._terminal_event(rows, life, args["cutoff"]))
                kept[life.identity()] = copy.deepcopy(cert)
            observed.append({**life.as_dict(), "certificate": cert})
        self._chains = kept
        return observed

    def _public_campaign(self):
        if not self._campaign:
            return None
        return {**copy.deepcopy({k: v for k, v in self._campaign.items() if k != "life"}),
                "premise": self._campaign["life"].as_dict()}

    def _public_pending(self):
        if not self._pending:
            return None
        return {k: copy.deepcopy(self._pending[k]) for k in
                ("proposal_id", "kind", "direction", "proposed_at", "lt_origin_occurrence_id")}

    def _activate(self, snapshot, pending, stamp):
        if _pending_seal(pending) != pending["seal"]:
            self._void("stale_proposal_seal", stamp); return
        if any(pending["context"][k] != self._context[k] for k in
               ("history_revision", "contract_id", "market_session", "process_session_id", "custody_lineage")):
            self._void("lineage_changed", stamp); return
        # A fresh-cutoff id differs; join by stable FULL LifeRef, not old id.
        rows = [r for r in self._catalog["rows"] if CP.life_ref(r["life"]) == pending["life"]]
        if len(rows) != 1:
            self._void("life_not_current_or_k_not_met", stamp); return
        row = rows[0]
        incumbent = self._campaign
        if pending["kind"] == "transfer":
            if not incumbent or incumbent["campaign_id"] != pending["incumbent_id"]:
                self._void("incumbent_not_active", stamp); return
            before = incumbent["direction"]
        else:
            if incumbent:
                self._void("not_unbound", stamp); return
            before = None
        proof, reason = campaign_scope_proof(snapshot, row, from_direction=before)
        if proof is None:
            self._void(reason, stamp); return
        original = pending["accepted"]["proof"]
        if any(proof[k] != original[k] for k in ("lt_origin_occurrence_id", "from", "to")):
            self._void("lt_origin_or_from_to_changed", stamp); return
        ident = "campaign:" + _digest([self._lineage, pending["proposal_id"], stamp])[:24]
        if incumbent:
            incumbent.update(status="RETIRED", retired_at=stamp,
                             retired_reason="route_b_transfer", successor_campaign_id=ident)
        self._campaign = {"campaign_id": ident, "direction": pending["direction"],
                          "life": pending["life"], "certificate": copy.deepcopy(row["certificate"]),
                          "activated_at": stamp, "activation_proposal_id": pending["proposal_id"],
                          "scope_proof": proof, "status": "ACTIVE"}
        self._transition = {"kind": pending["kind"], "reason": "scope_activated", "cutoff": stamp,
                            "predecessor_campaign_id": incumbent["campaign_id"] if incumbent else None,
                            "predecessor_direction": incumbent["direction"] if incumbent else None,
                            "predecessor_status": "RETIRED" if incumbent else None,
                            "predecessor_reason": "route_b_transfer" if incumbent else None,
                            "successor_campaign_id": ident, "successor_direction": pending["direction"],
                            "proposal_id": pending["proposal_id"], "scope_proof_id": proof["proof_id"]}
        self._pending = None

    def qualify(self, *, snapshot, brain_result, brain_input):
        """S7 optional field; private queue only, executable outputs untouched."""
        from ai_brain.production_model import brain_contract_fingerprint, model_matches
        out = (brain_result or {}).get("output")
        proposal = out.get("campaign_scope_proposal") if isinstance(out, dict) else None
        def outcome(status, *reasons, proposal_id=None):
            return {"status": status, "reasons": list(reasons), "proposal_id": proposal_id,
                    "cutoff": (self._context or {}).get("cutoff")}
        if proposal is None:
            return outcome("ABSENT")
        if (brain_result.get("source") != "llm" or brain_result.get("fallback_reason") is not None
                or any(brain_result.get(k) is not False for k in
                       ("repair_attempted", "family_repair_fixed", "invalidation_repair_fixed"))
                or not model_matches(brain_result.get("llm_model"))):
            return outcome("ABSENT", "proposal_not_from_primary_sovereign_cognition")
        if _read_publication(snapshot) is not self or self._projection["status"] != "AVAILABLE":
            return outcome("REFUSED", "producer_publication_unavailable")
        if self._brain_fingerprint != brain_contract_fingerprint():
            return outcome("REFUSED", "brain_contract_changed")
        if (not isinstance(proposal, dict) or set(proposal) !=
                {"kind", "direction", "premise_candidate_id", "scope_reason"}
                or any(type(v) is not str for v in proposal.values())
                or proposal["kind"] not in ("establish", "transfer")
                or proposal["direction"] not in ("bullish", "bearish")):
            return outcome("REFUSED", "malformed_proposal")
        supplied = (brain_input or {}).get("campaign_premise_catalog")
        if supplied != self._catalog:
            return outcome("REFUSED", "stale_catalog")
        pd = _digest(proposal)
        stamp = self._context["cutoff"]
        if self._proposal_at == stamp and (self._conflicted or pd != self._proposal_digest):
            self._pending = None
            self._conflicted = True
            self._refresh_watches()
            return outcome("REFUSED", "conflicting_same_cutoff_proposals")
        rows = [r for r in self._catalog["rows"]
                if r["premise_candidate_id"] == proposal["premise_candidate_id"]]
        if len(rows) != 1:
            return outcome("REFUSED", "unknown_or_ambiguous_id")
        row = rows[0]
        guard = brain_result.get("narrative_authority_guard") or {}
        direction = guard.get("proposed_direction") if guard.get("status") else out.get("narrative_direction")
        if direction != proposal["direction"] or row["supports"] != direction:
            return outcome("REFUSED", "direction_or_side_mismatch")
        incumbent = self._campaign
        if ((proposal["kind"] == "establish" and incumbent is not None)
                or (proposal["kind"] == "transfer" and
                    (incumbent is None or incumbent["direction"] == direction))):
            return outcome("REFUSED", "kind_incoherent")
        proof, reason = campaign_scope_proof(snapshot, row,
                                          from_direction=incumbent["direction"] if incumbent else None)
        if proof is None:
            return outcome("REFUSED", reason)
        if self._proposal_at == stamp:
            if self._conflicted:
                return outcome("REFUSED", "conflicting_same_cutoff_proposals")
            if pd == self._proposal_digest:
                return outcome("DUPLICATE", proposal_id=self._pending["proposal_id"] if self._pending else None)
            self._pending = None
            self._conflicted = True
            self._refresh_watches()
            return outcome("REFUSED", "conflicting_same_cutoff_proposals")
        if self._pending:
            return outcome("REFUSED", "pending_exists")
        accepted = {"catalog": copy.deepcopy(self._catalog), "row": copy.deepcopy(row),
                    "proposal": copy.deepcopy(proposal), "proof": proof,
                    "brain_fingerprint": self._brain_fingerprint,
                    "provenance": {k: brain_result.get(k) for k in
                                   ("source", "llm_model", "repair_attempted",
                                    "family_repair_fixed", "invalidation_repair_fixed")}}
        self._pending = {"proposal_id": "proposal:" + _digest([self._context, pd])[:24],
                         "kind": proposal["kind"], "direction": direction,
                         "life": CP.life_ref(row["life"]), "proposed_at": stamp,
                         "context": copy.deepcopy(self._context), "accepted": accepted,
                         "lt_origin_occurrence_id": proof["lt_origin_occurrence_id"],
                         "incumbent_id": incumbent["campaign_id"] if incumbent else None}
        self._pending["seal"] = _pending_seal(self._pending)
        self._proposal_at, self._proposal_digest, self._conflicted = stamp, pd, False
        self._refresh_watches()
        return outcome("PENDING", proposal_id=self._pending["proposal_id"])


def qualify_campaign_scope_proposal(custody, **kwargs):
    return custody.qualify(**kwargs)
