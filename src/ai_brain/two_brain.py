"""Two-brain hybrid: deterministic author proposes, external Brain adjudicates.

TWO-BRAIN-HYBRID (2026-08-08), experiment/two-brain-hybrid.

The two brains are good at different things, and the architecture should say so
out loud:

    DETERMINISTIC AUTHOR   finds the setup, names the canonical objects
    EXTERNAL BRAIN         reads context, and may object to what it can name
    MECHANICAL GATES       decide whether it may be traded at all

The last line is the one that matters. A CONFIRM is not permission. Every
deterministic gate -- qualification, geometry, reward:risk, stop distance, risk
budget, sizing, trade limits -- keeps its veto after adjudication, and this
module never touches any of them.

WHAT THIS IS NOT: a way around `wrong_model`. That gate encodes the current
doctrine (only the production model may author a candidate) and is correct for
the external-authoritative lane. Hybrid authority is a SEPARATE, explicitly
declared envelope that must prove itself -- never an inference drawn from a
missing model field, which is exactly the bypass this design exists to avoid.
"""
from __future__ import annotations

import copy
import hashlib
import json

from ai_brain import ai_call_ledger as LEDGER
import os

# ── mode contract ────────────────────────────────────────────────────────────
OFF = "off"
SHADOW = "shadow"
MATERIAL_REJECT_VETO = "material_reject_veto"
MODES = (OFF, SHADOW, MATERIAL_REJECT_VETO)


def two_brain_mode() -> str:
    """`off` (default) | `shadow` | `material_reject_veto`.

    Blank means unset, not enabled -- the same law the regime demotion needed
    after a blank env value silently resolved to `enforce`. An unrecognised
    value is `off`: an operating mode nobody wrote down is not an operating mode.
    """
    raw = (os.getenv("TWO_BRAIN_MODE") or "").lower().strip()
    return raw if raw in MODES else OFF


def hybrid_enabled() -> bool:
    return two_brain_mode() != OFF


def hybrid_has_authority() -> bool:
    """True only when the mode actually lets adjudication change a disposition."""
    return two_brain_mode() == MATERIAL_REJECT_VETO


# ── verdicts ─────────────────────────────────────────────────────────────────
CONFIRM = "CONFIRM"
MATERIAL_REJECT = "MATERIAL_REJECT"
ABSTAIN = "ABSTAIN"
VERDICTS = (CONFIRM, MATERIAL_REJECT, ABSTAIN)

#: A review that claimed MATERIAL_REJECT without naming a contradiction. It is
#: NOT silently downgraded to ABSTAIN -- it is recorded as what it was, so the
#: rate of unsupported vetoes stays measurable.
INVALID_MATERIAL_REJECT = "INVALID_MATERIAL_REJECT"

# ── dispositions ─────────────────────────────────────────────────────────────
CONTINUE_TO_MECHANICAL_GATES = "CONTINUE_TO_MECHANICAL_GATES"
STAND_DOWN_CONTEXTUAL_REJECT = "STAND_DOWN_CONTEXTUAL_REJECT"
STAND_DOWN_BINDING_FAILED = "STAND_DOWN_BINDING_FAILED"
SHADOW_RECORDED_ONLY = "SHADOW_RECORDED_ONLY"

#: Reasons a deterministic thesis could not become a canonical proposal.
NO_OBJECTIVE_MATCH = "objective_binding_no_match"
AMBIGUOUS_OBJECTIVE = "objective_binding_ambiguous"
NO_INVALIDATION_MATCH = "invalidation_binding_no_match"
AMBIGUOUS_INVALIDATION = "invalidation_binding_ambiguous"

#: Grounds that belong to the MECHANICAL lane. A contextual reviewer citing one
#: of these is not adjudicating context -- it is duplicating a calculator that
#: already ran, and it does not earn a veto for doing so.
MECHANICAL_GROUNDS = ("reward", "risk:", "r:r", "reward_to_risk", "rr ",
                      "position size", "sizing", "contract count",
                      "stop distance", "stop is too", "risk budget",
                      "too small", "insufficient reward")


def digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str)
                          .encode("utf-8")).hexdigest()[:16]


# ── canonical mechanical proposal ────────────────────────────────────────────
def build_mechanical_proposal(*, thesis: dict, objective: dict,
                              invalidation: dict, reference_price: float,
                              snapshot_id: str, timestamp: str,
                              qualification: dict = None) -> dict:
    """First-class object, not loose prose. Frozen by digest at construction."""
    reward = abs(float(objective["price"]) - reference_price)
    risk = abs(reference_price - float(invalidation["price"]))
    proposal = {
        "mechanical_proposal_id": "MP-" + digest(
            [snapshot_id, thesis.get("narrative_direction"),
             objective.get("objective_id"), invalidation.get("invalidation_id")]),
        "source": "deterministic",
        "snapshot_id": snapshot_id,
        "timestamp": timestamp,
        "direction": thesis.get("narrative_direction"),
        "entry_reference_price": reference_price,
        "objective_id": objective["objective_id"],
        "objective_price": objective["price"],
        "objective_type": objective.get("kind"),
        "invalidation_id": invalidation["invalidation_id"],
        "invalidation_price": invalidation["price"],
        "reward_to_risk": round(reward / risk, 3) if risk else None,
        "playbook_family": thesis.get("recommended_playbook_family"),
        "narrative_phase": thesis.get("narrative_phase"),
        "mechanical_reasoning": str(thesis.get("market_story") or "")[:300],
        "qualification_evidence": qualification or {},
    }
    proposal["frozen_digest"] = digest(
        {k: v for k, v in proposal.items() if k != "frozen_digest"})
    return proposal


def proposal_is_intact(proposal: dict) -> bool:
    """The mechanical proposal must survive adjudication byte-for-byte."""
    return proposal.get("frozen_digest") == digest(
        {k: v for k, v in proposal.items() if k != "frozen_digest"})


# ── exact binding ────────────────────────────────────────────────────────────
def bind_exact(level, catalog: list, id_field: str) -> dict:
    """Bind a deterministic level to a canonical object by EXACT price.

    Zero matches stands down; more than one stands down. Nearest-level
    substitution is the defect that once bound 29452.50 when the thesis named
    29493.25 -- directionally valid, and therefore silent. Accidental
    correctness is not correctness.
    """
    try:
        level = float(level)
    except (TypeError, ValueError):
        return {"bound": False,
                "reason": (NO_OBJECTIVE_MATCH if id_field == "objective_id"
                           else NO_INVALIDATION_MATCH),
                "detail": "no numeric level"}
    matches = [c for c in (catalog or [])
               if abs(float(c["price"]) - level) < 1e-6]
    if len(matches) == 1:
        return {"bound": True, "object": matches[0], "matched_level": level}
    no_match = (NO_OBJECTIVE_MATCH if id_field == "objective_id"
                else NO_INVALIDATION_MATCH)
    ambiguous = (AMBIGUOUS_OBJECTIVE if id_field == "objective_id"
                 else AMBIGUOUS_INVALIDATION)
    return {"bound": False,
            "reason": no_match if not matches else ambiguous,
            "detail": f"{len(matches)} catalog entries match {level}",
            "candidates": [c[id_field] for c in matches]}


# ── adjudication contract ────────────────────────────────────────────────────
ADJUDICATION_PROMPT = """You are reviewing an already-formed trade candidate \
produced by a deterministic market engine. You are NOT being asked to find a \
trade, and you are NOT being asked whether you like it.

You are given the market facts the engine used, and the exact candidate it \
formed. Decide whether anything in THOSE SUPPLIED FACTS materially contradicts \
the candidate.

Return STRICT JSON only:
{
  "candidate_id": "<copy exactly>",
  "verdict": "CONFIRM" | "MATERIAL_REJECT" | "ABSTAIN",
  "confidence": 0-100,
  "mechanical_direction_seen": "<copy exactly>",
  "objective_id_seen": "<copy exactly>",
  "invalidation_id_seen": "<copy exactly>",
  "material_contradictions": ["..."],
  "reasoning": "<two sentences maximum>"
}

CONFIRM - the candidate is contextually coherent with the supplied facts.
MATERIAL_REJECT - at least one SPECIFIC contradiction grounded in a supplied \
fact, named in material_contradictions. For example: the objective was already \
swept; delivery is established in the opposing direction; the protected \
structure named has already failed; PO3 resolved against the thesis; the \
authoritative active draw points elsewhere.
ABSTAIN - you cannot positively confirm, but you cannot name anything that is \
actually wrong. ABSTAIN is NOT rejection.

Do NOT reject on reward:risk, position size, stop distance or risk budget. The \
deterministic engine owns those and has already checked them.

You may not change the candidate. Copy candidate_id, mechanical_direction_seen, \
objective_id_seen and invalidation_id_seen exactly as given."""


def adjudication_packet(proposal: dict, market_facts: dict) -> dict:
    """What the reviewer sees. A deep copy, so the reviewer cannot be handed a
    live reference to the thing it is reviewing."""
    return {"mechanical_proposal": copy.deepcopy(proposal),
            "market_facts": copy.deepcopy(market_facts)}


def classify_review(review: dict, proposal: dict) -> dict:
    """Validate the reviewer's answer against the contract. Never trusts a
    self-applied MATERIAL_REJECT label."""
    verdict = str((review or {}).get("verdict") or "").upper()
    contradictions = [str(c) for c in ((review or {}).get(
        "material_contradictions") or []) if str(c).strip()]
    problems = []

    if verdict not in VERDICTS:
        return {"effective_verdict": ABSTAIN, "valid": False,
                "problems": [f"unknown verdict {verdict!r}"],
                "contradictions": contradictions}

    # Identity: the reviewer may disagree, but it may not RENAME.
    for field, expected in (("candidate_id", proposal["mechanical_proposal_id"]),
                            ("mechanical_direction_seen", proposal["direction"]),
                            ("objective_id_seen", proposal["objective_id"]),
                            ("invalidation_id_seen", proposal["invalidation_id"])):
        seen = (review or {}).get(field)
        if seen is not None and seen != expected:
            problems.append(f"{field} altered: {seen!r} != {expected!r}")

    effective = verdict
    if verdict == MATERIAL_REJECT:
        if not contradictions:
            effective = INVALID_MATERIAL_REJECT
            problems.append("MATERIAL_REJECT with no contradiction named")
        elif all(any(g in c.lower() for g in MECHANICAL_GROUNDS)
                 for c in contradictions):
            effective = INVALID_MATERIAL_REJECT
            problems.append("MATERIAL_REJECT on mechanical grounds only")

    return {"effective_verdict": effective, "valid": not problems,
            "problems": problems, "contradictions": contradictions,
            "stated_verdict": verdict,
            "confidence": (review or {}).get("confidence")}


# ── combined decision envelope ───────────────────────────────────────────────
def build_envelope(*, proposal: dict, review: dict = None,
                   classification: dict = None, mode: str = None,
                   binding_failure: dict = None) -> dict:
    """Immutable combined object. The disposition is derived, never asserted."""
    mode = mode or two_brain_mode()
    envelope = {
        "schema_version": "two_brain_envelope.v1",
        "authority_mode": mode,
        "mechanical_proposal": copy.deepcopy(proposal) if proposal else None,
        "terra_review": copy.deepcopy(review) if review else None,
        "review_classification": copy.deepcopy(classification) if classification else None,
        "binding_failure": copy.deepcopy(binding_failure) if binding_failure else None,
    }
    envelope["hybrid_disposition"] = _derive_disposition(envelope)
    envelope["mechanical_proposal_intact"] = (
        proposal_is_intact(proposal) if proposal else None)
    return envelope


def _derive_disposition(envelope: dict) -> str:
    if envelope.get("binding_failure"):
        return STAND_DOWN_BINDING_FAILED
    mode = envelope["authority_mode"]
    if mode == OFF:
        return CONTINUE_TO_MECHANICAL_GATES
    if mode == SHADOW:
        # Shadow observes. It never changes what happens.
        return SHADOW_RECORDED_ONLY
    verdict = (envelope.get("review_classification") or {}).get(
        "effective_verdict")
    if verdict == MATERIAL_REJECT:
        return STAND_DOWN_CONTEXTUAL_REJECT
    # CONFIRM, ABSTAIN and INVALID_MATERIAL_REJECT all continue. ABSTAIN is not
    # rejection, and an unsupported veto does not become one by being labelled.
    return CONTINUE_TO_MECHANICAL_GATES


def shadow_hypothetical(envelope: dict) -> str:
    """What material_reject_veto WOULD have done. Shadow's whole product."""
    probe = dict(envelope, authority_mode=MATERIAL_REJECT_VETO)
    return _derive_disposition(probe)


# ── hybrid authority declaration ─────────────────────────────────────────────
HYBRID_ENVELOPE_KEY = "two_brain_envelope"
SHADOW_KEY = "two_brain_shadow"

#: Adjudication is a paid call. Shadow only spends one when the deterministic
#: lane actually produced a bound proposal -- rare by construction -- and never
#: more than this many in a session.
DEFAULT_SHADOW_ADJUDICATION_CAP = 12


def shadow_adjudication_cap() -> int:
    try:
        return max(0, int(os.getenv("TWO_BRAIN_SHADOW_MAX_ADJUDICATIONS",
                                    DEFAULT_SHADOW_ADJUDICATION_CAP)))
    except (TypeError, ValueError):
        return DEFAULT_SHADOW_ADJUDICATION_CAP


#: Per-process adjudication accounting. Discovery calls and adjudication calls
#: are counted separately -- an unmetered second provider lane is exactly the
#: defect the Tiona audit named, and shadow must not become one.
ADJUDICATION_ACCOUNTING = {"calls_attempted": 0, "calls_completed": 0,
                           "calls_failed": 0, "tokens_prompt": 0,
                           "tokens_completion": 0, "tokens_total": 0,
                           "latency_seconds_total": 0.0}


def reset_adjudication_accounting() -> None:
    for key in ADJUDICATION_ACCOUNTING:
        ADJUDICATION_ACCOUNTING[key] = 0 if "latency" not in key else 0.0


def accounted_adjudicator(packet: dict, *, session_id: str = "",
                          scan: object = None, context: dict = None) -> dict:
    """The real adjudication call: production provider, production model,
    metered.

    Credentials, client construction, model resolution and timeout all come
    from the same authorities `narrative_brain._call_llm` uses. Only the prompt
    and the response shape differ, because adjudication is a different question
    from discovery and must not borrow the discovery contract.

    Never raises. A provider failure is recorded and the scan continues.
    """
    import time as _time
    started = _time.time()
    ADJUDICATION_ACCOUNTING["calls_attempted"] += 1
    result = {"ok": False, "review": None, "fallback_reason": None,
              "model": None, "usage": None, "latency_seconds": 0.0}
    try:
        from ai_layer.ai_api_adapter import _OPENAI_AVAILABLE, _openai  # type: ignore
    except Exception:  # noqa: BLE001
        result["fallback_reason"] = "adapter_import_failed"
        ADJUDICATION_ACCOUNTING["calls_failed"] += 1
        return result
    if not _OPENAI_AVAILABLE:
        result["fallback_reason"] = "openai_package_unavailable"
        ADJUDICATION_ACCOUNTING["calls_failed"] += 1
        return result
    if not os.getenv("OPENAI_API_KEY"):
        result["fallback_reason"] = "no_api_key"
        ADJUDICATION_ACCOUNTING["calls_failed"] += 1
        return result
    try:
        from ai_brain.production_model import resolve_model
        model = resolve_model(armed=False)
        result["model"] = model
        timeout = float(os.getenv("AI_BRAIN_TIMEOUT_SECONDS", "25"))
        client = _openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"),
                                timeout=timeout, max_retries=0)
        # Shadow gets its OWN cache key: its stable prefix is ADJUDICATION_PROMPT,
        # a different text from the primary brain's system prompt, so sharing a
        # key would be a guaranteed miss on both.
        cache_key = LEDGER.cache_key(role=LEDGER.SHADOW, model=model)
        client_request_id = LEDGER.new_client_request_id(
            session_id=session_id, scan=scan, role=LEDGER.SHADOW,
            purpose=LEDGER.PURPOSE_ADJUDICATION)
        result["client_request_id"] = client_request_id
        result["prompt_cache_key"] = cache_key
        create_kwargs = {
            "model": model, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": ADJUDICATION_PROMPT},
                         {"role": "user", "content": json.dumps(packet, default=str)}],
            "prompt_cache_key": cache_key,
            "extra_headers": {LEDGER.CLIENT_REQUEST_HEADER: client_request_id},
        }
        raw_http = None
        try:
            raw_http = client.chat.completions.with_raw_response.create(**create_kwargs)
            resp = raw_http.parse()
        except AttributeError:
            resp = client.chat.completions.create(**create_kwargs)
        result["request_id"] = LEDGER.server_request_id(raw_http, resp)
        result["response_id"] = getattr(resp, "id", "") or ""
        review = json.loads(resp.choices[0].message.content)
        usage = getattr(resp, "usage", None)
        result.update(ok=True, review=review, usage={
            "prompt": getattr(usage, "prompt_tokens", None),
            "completion": getattr(usage, "completion_tokens", None),
            "total": getattr(usage, "total_tokens", None)})
        ADJUDICATION_ACCOUNTING["calls_completed"] += 1
        ctx = dict(context or {})
        LEDGER.record(
            session_id=session_id, scan=scan, role=LEDGER.SHADOW,
            purpose=LEDGER.PURPOSE_ADJUDICATION, model_requested=model,
            model_returned=getattr(resp, "model", "") or "",
            client_request_id=client_request_id,
            request_id=result.get("request_id", ""),
            response_id=result.get("response_id", ""),
            usage=getattr(resp, "usage", None), ok=True,
            latency_seconds=round(_time.time() - started, 3),
            prompt_cache_key=cache_key, cache_mode="implicit",
            extra={
                "shadow_verdict": (review or {}).get("verdict"),
                "shadow_direction": (review or {}).get("direction")
                                    or ctx.get("mechanical_direction"),
                "shadow_confidence": (review or {}).get("confidence"),
                "primary_direction": ctx.get("primary_direction"),
                "primary_action": ctx.get("primary_action"),
                "agrees_with_primary": ctx.get("agrees_with_primary"),
                # The whole point of the shadow lane, restated on every row so
                # a future reader can never mistake it for an execution vote.
                "had_execution_authority": False,
            })
        for src, dst in (("prompt", "tokens_prompt"),
                         ("completion", "tokens_completion"),
                         ("total", "tokens_total")):
            value = (result["usage"] or {}).get(src)
            if value:
                ADJUDICATION_ACCOUNTING[dst] += int(value)
        return result
    except Exception as exc:  # noqa: BLE001
        result["fallback_reason"] = f"{type(exc).__name__}: {exc}"
        ADJUDICATION_ACCOUNTING["calls_failed"] += 1
        # A failed call still cost a request in most cases; it is recorded so
        # the ledger never under-counts spend.
        LEDGER.record(
            session_id=session_id, scan=scan, role=LEDGER.SHADOW,
            purpose=LEDGER.PURPOSE_ADJUDICATION,
            client_request_id=result.get("client_request_id", ""),
            request_id=result.get("request_id", ""), ok=False,
            fallback_reason=result["fallback_reason"],
            latency_seconds=round(_time.time() - started, 3),
            prompt_cache_key=result.get("prompt_cache_key", ""),
            extra={"had_execution_authority": False})
        return result
    finally:
        result["latency_seconds"] = round(_time.time() - started, 3)
        ADJUDICATION_ACCOUNTING["latency_seconds_total"] = round(
            ADJUDICATION_ACCOUNTING["latency_seconds_total"]
            + result["latency_seconds"], 3)


class ShadowObserver:
    """Watches a live session and records what the hybrid WOULD have done.

    Structurally incapable of changing production: it returns a record, is
    never consulted by any gate, and every failure is swallowed. If this class
    raises, a scan would be lost to an observation -- so it does not raise.
    """

    def __init__(self, adjudicator=None) -> None:
        #: injected so the harness can run offline; production supplies the
        #: accounted call.
        self._adjudicate = adjudicator
        self.adjudications_used = 0
        self.session_id = ""
        self.scan = None
        self.tokens_used = 0
        self.stats = {"scans_observed": 0, "directional": 0, "bound": 0,
                      "binding_failed": 0, "adjudicated": 0, "capped": 0,
                      "adjudication_failed": 0}

    def budget(self) -> dict:
        """What the shadow lane has spent. Surfaced in session telemetry so a
        second brain can never spend invisibly again."""
        return {"shadow_calls_used": self.adjudications_used,
                "shadow_calls_allowed": shadow_adjudication_cap(),
                "shadow_tokens_used": self.tokens_used,
                "shadow_stats": dict(self.stats)}

    def observe(self, *, snapshot: dict, brain_input: dict,
                deterministic_thesis: dict, objective_catalog: list,
                invalidation_catalog: list, snapshot_id: str,
                session_id: str = "", scan: object = None) -> dict | None:
        self.session_id = session_id or self.session_id
        self.scan = scan if scan is not None else self.scan
        try:
            return self._observe(snapshot, brain_input, deterministic_thesis,
                                 objective_catalog, invalidation_catalog,
                                 snapshot_id)
        except Exception as exc:  # noqa: BLE001 — an observation may never cost a scan
            self.stats["adjudication_failed"] += 1
            return {"schema_version": "two_brain_shadow.v1", "error":
                    f"{type(exc).__name__}: {exc}"}

    def _observe(self, snapshot, brain_input, thesis, objectives,
                 invalidations, snapshot_id):
        self.stats["scans_observed"] += 1
        direction = (thesis or {}).get("narrative_direction")
        if direction not in ("bullish", "bearish"):
            return {"schema_version": "two_brain_shadow.v1",
                    "mechanical_direction": direction,
                    "outcome": "MECHANICAL_STAND_DOWN"}
        self.stats["directional"] += 1

        price = (brain_input.get("market") or {}).get("current_price")
        draw = ((brain_input.get("liquidity") or {}).get("active_draw") or {})
        obj = bind_exact(draw.get("level"), objectives, "objective_id")
        if not obj["bound"]:
            self.stats["binding_failed"] += 1
            env = build_envelope(proposal=None, binding_failure=obj, mode=SHADOW)
            return {"schema_version": "two_brain_shadow.v1", "envelope": env,
                    "outcome": "BINDING_FAILED", "binding": obj}

        opposing = [i for i in (invalidations or [])
                    if (direction == "bearish" and float(i["price"]) > float(price))
                    or (direction == "bullish" and float(i["price"]) < float(price))]
        inv = ({"bound": True, "object": opposing[0]} if len(opposing) == 1
               else {"bound": False, "reason": (NO_INVALIDATION_MATCH if not opposing
                                                else AMBIGUOUS_INVALIDATION),
                     "detail": f"{len(opposing)} valid invalidations"})
        if not inv["bound"]:
            self.stats["binding_failed"] += 1
            env = build_envelope(proposal=None, binding_failure=inv, mode=SHADOW)
            return {"schema_version": "two_brain_shadow.v1", "envelope": env,
                    "outcome": "BINDING_FAILED", "binding": inv}

        proposal = build_mechanical_proposal(
            thesis=thesis, objective=obj["object"], invalidation=inv["object"],
            reference_price=float(price), snapshot_id=snapshot_id,
            timestamp=str(brain_input.get("timestamp") or ""),
            qualification=(snapshot.get("qualification") or {}))
        self.stats["bound"] += 1

        if self._adjudicate is None or self.adjudications_used >= shadow_adjudication_cap():
            self.stats["capped"] += 1
            return {"schema_version": "two_brain_shadow.v1",
                    "envelope": build_envelope(proposal=proposal, mode=SHADOW),
                    "outcome": "BOUND_NOT_ADJUDICATED",
                    "reason": ("no adjudicator" if self._adjudicate is None
                               else "session adjudication cap reached")}

        self.adjudications_used += 1
        # Context travels so the durable row can state what the PRIMARY brain
        # said at the same moment. Agreement is only meaningful side by side.
        ctx = {"primary_direction": (brain_input.get("primary_direction")
                                     or (brain_input.get("ai_brain") or {}).get("narrative_direction")),
               "primary_action": (brain_input.get("primary_action")
                                  or (brain_input.get("ai_brain") or {}).get("current_action")),
               "mechanical_direction": (thesis or {}).get("narrative_direction")}
        ctx["agrees_with_primary"] = (
            None if not ctx["primary_direction"]
            else ctx["primary_direction"] == ctx["mechanical_direction"])
        try:
            raw = self._adjudicate(
                adjudication_packet(proposal,
                                    brain_input.get("market_facts") or brain_input),
                session_id=self.session_id, scan=self.scan, context=ctx)
        except TypeError:
            # a test double may accept only the packet
            raw = self._adjudicate(adjudication_packet(
                proposal, brain_input.get("market_facts") or brain_input))

        # The accounted adjudicator returns a call record; a test double may
        # return the review directly. Both are accepted, and a failed call is
        # recorded rather than silently becoming an absent opinion.
        call_meta = None
        if isinstance(raw, dict) and "review" in raw and "ok" in raw:
            call_meta = {k: raw.get(k) for k in
                         ("ok", "model", "usage", "latency_seconds",
                          "fallback_reason")}
            if not raw.get("ok"):
                self.stats["adjudication_failed"] += 1
                return {"schema_version": "two_brain_shadow.v1",
                        "envelope": build_envelope(proposal=proposal, mode=SHADOW),
                        "outcome": "ADJUDICATION_FAILED",
                        "reason": raw.get("fallback_reason"),
                        "call": call_meta}
            review = raw.get("review")
        else:
            review = raw

        self.stats["adjudicated"] += 1
        try:
            self.tokens_used += int(((call_meta or {}).get("usage") or {}).get("total") or 0)
        except (TypeError, ValueError):
            pass
        classification = classify_review(review, proposal)
        env = build_envelope(proposal=proposal, review=review,
                             classification=classification, mode=SHADOW)
        return {"schema_version": "two_brain_shadow.v1", "envelope": env,
                "outcome": "ADJUDICATED",
                "would_have_done": shadow_hypothetical(env),
                "effective_verdict": classification["effective_verdict"],
                "call": call_meta}


def authorized_hybrid_envelope(brain_result: dict) -> dict:
    """The ONLY way a deterministic thesis earns candidate authority.

    Every condition must be proven positively. Authority is never inferred from
    an absent model field or a `source == deterministic` string -- inferring it
    is precisely the bypass this contract replaces.
    """
    envelope = (brain_result or {}).get(HYBRID_ENVELOPE_KEY)
    if not isinstance(envelope, dict):
        return {"authorized": False, "reason": "no_hybrid_envelope"}
    if envelope.get("authority_mode") != MATERIAL_REJECT_VETO:
        return {"authorized": False,
                "reason": f"mode_{envelope.get('authority_mode')}_grants_no_authority"}
    if two_brain_mode() != MATERIAL_REJECT_VETO:
        return {"authorized": False, "reason": "runtime_mode_does_not_permit_hybrid"}
    proposal = envelope.get("mechanical_proposal")
    if not isinstance(proposal, dict):
        return {"authorized": False, "reason": "no_mechanical_proposal"}
    if proposal.get("source") != "deterministic":
        return {"authorized": False, "reason": "proposal_not_deterministic"}
    for field in ("objective_id", "invalidation_id", "direction",
                  "entry_reference_price"):
        if proposal.get(field) in (None, ""):
            return {"authorized": False, "reason": f"proposal_missing_{field}"}
    if not proposal_is_intact(proposal):
        return {"authorized": False, "reason": "mechanical_proposal_mutated"}
    if not envelope.get("terra_review"):
        return {"authorized": False, "reason": "adjudication_missing"}
    if envelope.get("hybrid_disposition") != CONTINUE_TO_MECHANICAL_GATES:
        return {"authorized": False,
                "reason": f"disposition_{envelope.get('hybrid_disposition')}"}
    return {"authorized": True, "reason": "hybrid_envelope_authorized",
            "proposal": proposal}
