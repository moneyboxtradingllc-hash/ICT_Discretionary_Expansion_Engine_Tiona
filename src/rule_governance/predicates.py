"""
Phase 5H.1 — Predicate Library.

Candidate rule logic lives HERE, as pure, versioned functions over the
SharedMarketContext. Code review of this file IS legislative review.

CONSTITUTIONAL PRINCIPLES (immutable):
  - Predicates read SharedMarketContext ONLY — never council votes, never
    snapshot internals. Council members sponsor rules; they do not define them.
  - Predicates are deterministic: same context -> same result.
  - Predicates NEVER fire on missing data ("measured weakness only").
  - Predicates NEVER fire on error — any exception returns (False, reason).
  - Nothing in this module touches execution, scores, or decisions.

Signature: predicate(ctx: dict) -> tuple[bool, str]
  (fired, reason) — reason is logged in the divergence ledger either way.
"""

_ROTATIONAL_REGIMES = frozenset({"range_rotation", "chop"})
_UNHEALTHY_VOL      = frozenset({"unstable", "toxic", "explosive"})

_CONTINUATION_PLAYBOOKS = frozenset({
    "trend_continuation", "opening_drive", "range_expansion",
    "manipulation_to_distribution",
})
_REVERSAL_PLAYBOOKS = frozenset({
    "liquidity_sweep_reversal", "failed_breakout_reversal",
})


def _safe(fn):
    """Predicates never raise and never fire on error."""
    def wrapped(ctx: dict):
        try:
            return fn(ctx or {})
        except Exception as exc:  # noqa: BLE001
            return False, f"predicate_error:{exc}"
    wrapped.__name__ = fn.__name__
    return wrapped


# ── R-001 ─────────────────────────────────────────────────────────────────────

@_safe
def regime_environmental_compound_v1(ctx: dict):
    """
    Sponsor: REGIME.
    Gap tested: trades the matrix PERMITS (e.g. confirmed-trigger reversals in
    a range) when environmental hostility compounds.

    FIRE iff at least 2 of:
      - regime in {range_rotation, chop}
      - exhaustion_present
      - volatility_state in {unstable, toxic, explosive}
    """
    hostile = []
    regime = (ctx.get("regime") or "unknown").lower()
    vol    = (ctx.get("volatility_state") or "unknown").lower()

    if regime in _ROTATIONAL_REGIMES:
        hostile.append(f"rotational regime ({regime})")
    if ctx.get("exhaustion_present") is True:
        hostile.append("exhaustion present")
    if vol in _UNHEALTHY_VOL:
        hostile.append(f"volatility {vol}")

    if len(hostile) >= 2:
        return True, f"compound hostility ({len(hostile)}): " + "; ".join(hostile)
    return False, f"hostile conditions = {len(hostile)} (< 2)"


# ── R-002 ─────────────────────────────────────────────────────────────────────

@_safe
def delivery_continuation_objection_v1(ctx: dict):
    """
    Sponsor: DELIVERY.
    Gap tested: delivery quality — inexpressible in the 5F matrix.

    FIRE iff:
      - playbook is continuation-family
      - continuation_intact is False
      - delivery_confidence < 40
      - delivery_state is MEASURED (never fires on missing data)
    """
    playbook = (ctx.get("playbook") or "no_playbook").lower()
    if playbook not in _CONTINUATION_PLAYBOOKS:
        return False, f"playbook '{playbook}' not continuation-family"

    state = (ctx.get("delivery_state") or "unknown").lower()
    if state in ("unknown", ""):
        return False, "delivery unmeasured — missing data never fires"

    intact = ctx.get("continuation_intact") is True
    conf   = int(ctx.get("delivery_confidence", 0) or 0)

    if not intact and conf < 40:
        return True, (
            f"continuation playbook with broken delivery "
            f"(state={state}, confidence={conf}, intact=false)"
        )
    return False, f"delivery acceptable (confidence={conf}, intact={intact})"


# ── R-003 ─────────────────────────────────────────────────────────────────────

@_safe
def reversal_without_evidence_v1(ctx: dict):
    """
    Sponsor: OPPORTUNITY.
    Gap tested: reversal playbooks selected on narrative alone — no measured
    sweep+reclaim or MSS (the June 10 pattern).

    FIRE iff:
      - playbook is reversal-family
      - reversal_present is False
    """
    playbook = (ctx.get("playbook") or "no_playbook").lower()
    if playbook not in _REVERSAL_PLAYBOOKS:
        return False, f"playbook '{playbook}' not reversal-family"

    if ctx.get("reversal_present") is True:
        return False, "reversal evidence present (sweep+reclaim or MSS)"

    return True, f"reversal playbook '{playbook}' without measured reversal evidence"


# ── Library ───────────────────────────────────────────────────────────────────

PREDICATES = {
    "regime_environmental_compound_v1":   regime_environmental_compound_v1,
    "delivery_continuation_objection_v1": delivery_continuation_objection_v1,
    "reversal_without_evidence_v1":       reversal_without_evidence_v1,
}


def get_predicate(predicate_id: str):
    """Return the predicate function or None. Never raises."""
    return PREDICATES.get(predicate_id or "")


def predicate_exists(predicate_id: str) -> bool:
    return (predicate_id or "") in PREDICATES
