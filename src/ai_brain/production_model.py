"""The single authority on which external Brain model production may use.

UPGRADE-PRODUCTION-BRAIN-TO-GPT-5.6-TERRA (2026-08-06).

Before this module the model was resolved inline as:

    os.getenv("AI_BRAIN_MODEL", os.getenv("AI_MODEL", "gpt-4o-mini"))

`AI_MODEL=gpt-4o-mini` is actually set in this deployment, so a missing or
mistyped `AI_BRAIN_MODEL` would not have failed -- it would have quietly run an
armed production session on a far weaker model while every piece of telemetry
still said Luna. Silent model substitution is the same class of defect as the
silent data-provider fallback and the smoke-cap leak: the system keeps running
and only the evidence is wrong.

For an ARMED session the model is explicit or the session refuses. Disarmed
diagnostics stay usable so the path can be inspected without arming anything.
"""
from __future__ import annotations

import hashlib
import os

# PRAC-MODEL-RULING (2026-08-19, operator). Luna is the production Brain for the
# PRAC VALIDATION PERIOD. Terra is RESERVED for the later Combine phase -- it is
# not deprecated and nothing about its integration failed. The measured reason is
# cost: the Terra segment of 2026-08-19 spent 739,891 tokens across 29 scans in
# 39 minutes and produced 29 stand_downs, so a full validation period at that
# burn rate buys operational evidence at a price the PRAC phase does not need to
# pay. Same mechanics, same execution stack, cheaper external reader.
#
# Terra returns DELIBERATELY, with its own fresh authorization, when the Combine
# phase begins -- never as a config toggle.
PRODUCTION_MODEL = "gpt-5.6-luna"
PREVIOUS_PRODUCTION_MODEL = "gpt-5.6-terra"

# `gpt-5.6` is an ALIAS that routes to Sol. Naming it here means a refusal can
# say why rather than reporting a generic mismatch.
FORBIDDEN_MODELS = {
    "gpt-5.6": "unsuffixed alias routes to gpt-5.6-sol, not the authorized tier",
    "gpt-5.6-sol": "not the authorized production tier",
    PREVIOUS_PRODUCTION_MODEL: ("reserved for the Combine phase by operator ruling "
                                "2026-08-19; PRAC validation runs on Luna"),
    "gpt-4o-mini": "legacy AI_MODEL default; never a production Brain",
}

BRAIN_TIER = "Luna"


class ModelResolutionError(RuntimeError):
    """The production Brain model could not be resolved. Always fail closed."""


def configured_model() -> str:
    """Exactly what the operator configured -- no chain, no default."""
    return (os.getenv("AI_BRAIN_MODEL") or "").strip()


def resolve_model(*, armed: bool) -> str:
    """The model this process may use.

    Armed: must be explicitly configured AND equal the production model.
    Disarmed: falls back to the production model so diagnostics still run, but
    a configured value is still honoured so a mismatch stays visible.
    """
    configured = configured_model()
    if not configured:
        if armed:
            raise ModelResolutionError(
                "NO_BRAIN_MODEL: AI_BRAIN_MODEL is not set. An armed session will "
                "not infer a Brain model -- the legacy chain would have resolved "
                f"AI_MODEL ({os.getenv('AI_MODEL') or 'unset'}) instead. "
                f"Set AI_BRAIN_MODEL={PRODUCTION_MODEL}.")
        return PRODUCTION_MODEL
    if armed and configured != PRODUCTION_MODEL:
        why = FORBIDDEN_MODELS.get(configured, "not the authorized production model")
        raise ModelResolutionError(
            f"BRAIN_MODEL_NOT_AUTHORIZED: AI_BRAIN_MODEL={configured!r} -- {why}. "
            f"Production doctrine authorizes {PRODUCTION_MODEL!r}.")
    return configured


def reasoning_effort() -> "str | None":
    """The reasoning effort this repository sends, or None for the API default.

    Reported rather than assumed: as of the Terra migration this repository sets
    NO reasoning/temperature/top_p/max_tokens on the production call. Keeping it
    None is deliberate -- the migration changes exactly one variable, the model.
    """
    v = (os.getenv("AI_BRAIN_REASONING_EFFORT") or "").strip()
    return v or None


def model_matches(returned: str, expected: str = None) -> bool:
    """Whether the model the API actually served matches what we asked for.

    Providers may append a dated suffix (`gpt-5.6-terra-2026-07-01`), so a
    prefix match is accepted; a different family is not.
    """
    expected = expected or PRODUCTION_MODEL
    r = str(returned or "").strip()
    return bool(r) and (r == expected or r.startswith(expected + "-"))


# ── Brain-contract fingerprint ────────────────────────────────────────────────
#: SOURCE CLOSURE OF THE DECISION CONTRACT.
#:
#: For a long time this was three files, and twice in one day decision-relevant
#: code changed while `verify` stayed PASS:
#:   * v10-v12 created and materially rewrote `market_state/mtf_market_state.py`
#:   * v13 changed `ai_brain/brain_input.py` so Terra received the FULL
#:     per-timeframe invalidation menu instead of one collapsed summary level
#: Neither moved the fingerprint. An authorization is a statement about a
#: specific organism, and both changed what that organism is.
#:
#: WHAT BELONGS HERE: anything that changes what the Brain RECEIVES, or how its
#: answer becomes a trade. Nothing else. Execution and mission-lifecycle code
#: (runner, mission state, reconciler, recovery, submission record, production
#: loop/session) is deliberately EXCLUDED -- it governs how a decision is
#: carried out safely, not what is decided, it changes far more often, and
#: binding it would make every safety repair invalidate a live approval for no
#: gain in decision integrity. `topstepx_session_authorization.py` is excluded
#: because hashing the hasher's own container is circular.
#:
#: `production_model.py` is excluded for the same circularity reason; the model
#: identity it carries is already bound separately as `brain_model`.
#:
#: MARKET-REALITY CLOSURE (2026-08-12, after PROD-20260812). A third instance of
#: the same disease, and the worst one: `TopstepXLiveSession` did not implement
#: `bars_1m`, so production startup history was silently ZERO and the process
#: reasoned from a chart grown out of its own uptime. The repair changed the
#: historical capability, canonical ingestion, gap repair and the armed startup
#: gate -- and the fingerprint did not move a single character, because the
#: market-data ACQUISITION path sat outside this tuple.
#:
#: Toolbox was bound at Step 7 because it decides whether a SETUP may exist.
#: These files decide whether the CHART exists. Nothing the Brain receives is
#: more load-bearing than the candles, so a source that can change whether
#: historical bars can be acquired, whether they may enter canonical state,
#: whether that state is fit to author reasoning, or whether an armed session may
#: proceed to scanning, is decision-bearing by definition.
#:
#: `candle_continuity.py` is bound deliberately and not as a courtesy: it holds
#: `coherent_window`, `contiguous_tail`, `verify_continuous` and the 15-minute
#: alignment constant. Binding the four obvious files while leaving the actual
#: fitness ALGORITHM outside would have reproduced this defect one layer down --
#: someone could lower `minimum_bars` to 5 and every authorization would still
#: verify.
#:
#: `timeframe_builder.py` completes the same lane (v36). Acquisition decides
#: WHICH 1m facts exist; this decides how those facts become the 3m/5m/15m/1h
#: world Terra actually reasons about. A shifted bucket boundary, an admitted
#: partial bucket or a mis-floored timestamp would rewrite every higher-timeframe
#: structure the Brain sees while the fingerprint sat unmoved -- the identical
#: failure shape as the acquisition gap, one transformation later. Truthful 1m
#: bars are not a truthful chart until the aggregation above them is bound too.
#:
#: STILL EXCLUDED, deliberately: `topstepx_readonly.py` (collector tooling, not
#: the production path), the production loop and mission lifecycle (unchanged
#: reasoning above), and every diagnostic/report/audit helper. Authority decides
#: inclusion, never directory membership.
_CONTRACT_SOURCES = (
    # what the Brain receives
    ("prompt", "ai_brain/brain_prompt.py"),
    ("schema", "ai_brain/brain_schema.py"),
    ("validator", "ai_brain/brain_validation.py"),
    ("input", "ai_brain/brain_input.py"),
    ("protected_swings", "narrative_authority/protected_swings.py"),
    # LUNA-SWING-SEQUENCE-TRUTH-1 (2026-09-01) — THE STRUCTURAL/REGIME TRUTH
    # PRODUCERS. `protected_swings` and `input` were already bound, which binds
    # the registry and the publication hop -- but not the three modules that
    # decide WHAT STRUCTURE AND REGIME MEAN before publication. Someone could
    # have changed the canonical sequence law, the timeframe sufficiency law or
    # the range-evidence law in isolation, and a minted authorization would have
    # kept verifying against an organism that had quietly been given a different
    # picture of the market.
    #
    # regime_features / regime_classifier are bound as an EXISTING hole, not a
    # new one: `market_regime` has always travelled in the Brain payload, so
    # these two have been able to change Brain-visible truth unbound since long
    # before this unit. The unit made that materially worse by routing the
    # windowed swing witness through them, and that is what surfaced it.
    ("swing_structure", "narrative_authority/swing_structure.py"),
    # LUNA-LIQUIDITY-SCOPE-TRUTH-1 (2026-09-01) — THE LIQUIDITY-EVENT TRUTH
    # PRODUCERS. Each was machine-tested against the question the closure
    # actually asks: can an isolated semantic edit here change a CERTIFIED
    # Brain-visible fact? Every one answered yes.
    #
    #   liquidity_scope       decides internal vs external, and against which
    #                         named authority
    #   sweep_occurrence      mints the event identity the scope is frozen onto
    #   liquidity_engine      proves the sweep and stamps scope at event time
    #   manipulation_detector owns the component votes and their levels
    #   direction_vote        resolves direction / direction_conflicted
    #   session_po3           owns the accumulation range po3_scope is judged by
    #   po3_config            MANIP_CONTEXT/MANIP_LOOKBACK define which pivots
    #                         exist -- measured: narrowing the context flips the
    #                         same event from external to internal, so a
    #                         CONSTANTS file silently owns scope
    #   snapshot_builder      threads `timeframe=tf` into the component --
    #                         measured: deleting that kwarg turns a PROVEN
    #                         occurrence link into UNPROVEN
    #   production_scan_cycle stamps po3_scope from the PRIOR established range
    #
    # The cost is accepted for the same reason it was accepted for the
    # production entrypoint: churn in a bound file invalidates live
    # authorizations, and that is cheaper than an unbound file quietly changing
    # what Luna believes about what happened.
    ("liquidity_scope", "market_data/liquidity_scope.py"),
    ("sweep_occurrence", "market_data/sweep_occurrence.py"),
    ("liquidity_engine", "structure/liquidity_engine.py"),
    ("manipulation_detector", "structure/manipulation_detector.py"),
    ("direction_vote", "structure/direction_vote.py"),
    ("session_po3", "structure/session_po3.py"),
    ("po3_config", "structure/po3_config.py"),
    ("snapshot_builder", "market_data/snapshot_builder.py"),
    ("production_scan_cycle", "live_scan/production_scan_cycle.py"),
    ("regime_features", "regime_classification/regime_features.py"),
    ("regime_classifier", "regime_classification/regime_classifier.py"),
    ("mtf_market_state", "market_state/mtf_market_state.py"),
    ("structure_flip", "structure/structure_flip.py"),
    # how its answer becomes a trade
    ("candidate_producer", "broker/luna_candidate_producer.py"),
    ("risk_doctrine", "broker/topstepx_combine_risk.py"),
    # LUNA-DAILY-LOSS-BUDGET-GOVERNOR-1 (2026-08-31) — DELIBERATE CLOSURE
    # EXPANSION, for exactly the reason `risk_doctrine` sits above it.
    #
    # This module decides whether a NEW ENTRY is permitted at all, how much
    # remaining session loss room exists, and therefore the dynamic ceiling on
    # planned risk -- plus the two fail-closed states (CONTAMINATED, UNKNOWN)
    # that refuse an entry when risk truth cannot be established.
    #
    # WHY WIRING IS NOT ENOUGH. Today's fingerprint already moved because the
    # production entrypoint now signs the budget term. But that binds the CALL,
    # not the CONTENTS. Someone could later change the remaining-room
    # arithmetic, the exhaustion behaviour, the contamination handling or the
    # unknown-state fail-closed rule WITHOUT touching the entrypoint, and a
    # previously minted authorization would still verify against an organism
    # that had quietly been given different permission to risk money. Binding
    # the module is what makes that edit invalidate the authorization.
    ("daily_loss_budget", "broker/daily_loss_budget.py"),
    # ROADMAP STEP 7 (2026-08-12) — DELIBERATE CLOSURE EXPANSION.
    # Until Step 7 the toolbox was witness only: it changed what Terra SAW but
    # could not decide anything, so it sat outside the contract. Step 7 makes
    # `authorized_tool_catalog` gate authorization, so these two files now
    # determine whether a candidate may exist at all -- squarely "how its answer
    # becomes a trade". Leaving them out would let a detector threshold change
    # silently alter what authorises while an old approval still looked valid.
    ("tool_geometry", "toolbox/price_levels.py"),
    ("tool_inventory", "toolbox/toolbox_engine.py"),
    # MARKET REALITY -- whether the chart exists at all
    ("history_capability", "broker/topstepx_live_session.py"),
    ("history_acquisition", "data_feed/topstepx_provider.py"),
    ("history_fitness", "data_feed/startup_history_authority.py"),
    ("continuity_law", "data_feed/candle_continuity.py"),
    ("timeframe_construction", "data_feed/timeframe_builder.py"),
)

#: REPO-ROOT-RELATIVE closure. Same contract, different anchor.
#:
#: The production entrypoint is not "just a tool". It holds the ACTUAL armed
#: startup authority call -- `check_startup(..., candles=candles)` -- and
#: deleting that one argument would let an armed session scan on a newborn chart
#: while every authorization still verified. That is the precise test for
#: decision-bearing, and living under `tools/` does not exempt it.
#:
#: Bound rather than relocated: moving the gate into an already-bound module
#: would not have closed the hole, because whatever module owned it would still
#: be CALLED from here, and the entrypoint can always decline to call. The
#: honest closure is the one that admits the entrypoint decides.
#:
#: The cost is real and accepted: display-only churn in this file invalidates
#: live authorizations. If that becomes a nuisance, the fix is to move telemetry
#: helpers OUT into an unbound module -- never to unbind the entrypoint.
_CONTRACT_SOURCES_REPO = (
    ("production_entrypoint", "tools/topstepx_production_session.py"),
)


def brain_contract_fingerprint() -> str:
    """Deterministic identity of the load-bearing prompt/schema/validator.

    An authorization that binds only the model would still be honoured after
    the prompt or validator changed underneath it -- which is exactly what
    happened on 2026-08-06, when the semantic contract was repaired mid-session.
    Hashing the sources makes that change invalidate the authorization.

    Contains no secret: these are committed source files.
    """
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    repo_root = os.path.dirname(here)
    h = hashlib.sha256()
    for label, rel in _CONTRACT_SOURCES + _CONTRACT_SOURCES_REPO:
        # Two anchors, one contract: `src/` for library sources, the repository
        # root for the production entrypoint. Order is fixed so the digest is
        # deterministic across machines.
        base = here if (label, rel) not in _CONTRACT_SOURCES_REPO else repo_root
        path = os.path.join(base, rel)
        h.update(label.encode())
        try:
            with open(path, "rb") as fh:
                h.update(fh.read())
        except OSError:
            h.update(b"<missing>")
    # BUILD-SAFE-DESCRIPTIVE-SESSION-MEMORY: retrieval changes what the Brain
    # RECEIVES. Binding only the prompt/schema/validator sources would let the
    # similarity threshold, the analog ceiling, the retention window or the
    # authority label move under an authorization that still verifies. The
    # RESOLVED policy values are hashed, not the file -- a value that arrives
    # from configuration must count too.
    try:
        from ai_retrieval.retrieval_contract import retrieval_contract_fingerprint
        h.update(b"retrieval")
        h.update(retrieval_contract_fingerprint().encode())
    except Exception:  # noqa: BLE001
        h.update(b"retrieval<missing>")
    return "brain:" + h.hexdigest()[:16]


def describe(*, armed: bool = False) -> dict:
    """Resolved Brain identity for startup telemetry. No secrets."""
    try:
        model = resolve_model(armed=armed)
        error = None
    except ModelResolutionError as exc:
        model, error = None, str(exc)
    return {"model": model, "tier": BRAIN_TIER if model == PRODUCTION_MODEL else "UNKNOWN",
            "configured": configured_model() or None,
            "reasoning_effort": reasoning_effort(),
            "json_mode_required": True,
            "contract_fingerprint": brain_contract_fingerprint(),
            "model_fallback": "NONE", "error": error}
