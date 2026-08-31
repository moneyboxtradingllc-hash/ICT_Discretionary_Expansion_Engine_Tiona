"""EPISTEMIC-CLOSURE-CERTIFICATION-1 — the negative space.

WHAT THE ORGANISM CAN AND CANNOT SAY, stated as questions rather than fields.

A registry of facts answers "what do we publish?". It does not answer "what can
we not express at all?", and that second question is where the expensive
failures live. A missing vocabulary does not announce itself: it arrives as a
`None`, or as a plausible-looking value that quietly means something else, and
the Brain reasons over it without ever being told the concept was unavailable.

Two examples this matrix exists to keep visible:

    A retracement inside a bullish leg and a genuine bearish reversal are the
    SAME SHAPE in `active_path.owner`, because the field holds one scope.
    Nothing in the payload says "I cannot distinguish these".

    A liquidity pool that was swept and re-formed at the same price is
    indistinguishable from one never touched, because pools carry price but no
    lifecycle. "Untaken" is not a claim the organism can currently make.

Each capability resolves to CERTIFIED, PARTIAL or BLOCKED, and every answer must
cite the contract and the test that back it. An unbacked capability claim is
itself a verification failure.
"""
from __future__ import annotations

from rule_governance.epistemic_closure.fact_contract import BLOCKED, CERTIFIED
from rule_governance.epistemic_closure.fact_registry import by_id

PARTIAL = "PARTIAL"

#: `question` is deliberately phrased as something a trader would ask, not as a
#: field name. If the answer is BLOCKED, `gap` says what is missing and which
#: unit owns closing it.
CAPABILITIES = (
    {
        "capability_id": "path.multi_scope",
        "owner_unit": "MULTI-SCOPE-PATH-CONTEXT-1",
        "question": "Can the organism express a local bullish path INSIDE a "
                    "broader bearish incumbent, at the same moment?",
        "status": BLOCKED,
        "facts": ("active_path.multi_scope", "active_path.owner"),
        "gap": "`active_path` holds ONE ownership claim. A counter-path "
               "retracement and a true reversal are the same shape in it. "
               "Owned by MULTI-SCOPE-PATH-CONTEXT-1.",
    },
    {
        "capability_id": "liquidity.one_price_many_witnesses",
        "owner_unit": "OBJECTIVE-SCALE-PRESERVATION-1B",
        "question": "Can one liquidity PRICE be expressed as a single pool with "
                    "several timeframe witnesses?",
        "status": PARTIAL,
        "facts": ("liquidity.scale_hierarchy", "liquidity.brain.nearest_buy_side"),
        "gap": "The representation exists and is certified, but it is not wired "
               "into the Brain payload -- Luna still receives the flattened "
               "highest-timeframe-first legacy fields. Owned by "
               "OBJECTIVE-SCALE-PRESERVATION-1B.",
    },
    {
        "capability_id": "liquidity.nearest_is_nearest",
        "owner_unit": "OBJECTIVE-SCALE-PRESERVATION-1B",
        "question": "When the payload says 'nearest' liquidity, does it mean "
                    "mathematically nearest to price?",
        "status": BLOCKED,
        "facts": ("liquidity.brain.nearest_buy_side",
                  "liquidity.brain.nearest_sell_side"),
        "gap": "NO. `brain_input` selects the first non-null pool scanning "
               "15m -> 5m -> 3m -> 1m, so a distant 15m pool outranks a close 1m "
               "one. The fields are retained as LEGACY and may not be read by "
               "their name. Owned by OBJECTIVE-SCALE-PRESERVATION-1B, which "
               "replaces them with scale-aware selection.",
    },
    {
        "capability_id": "swing.reaffirmation_without_rebirth",
        "question": "Can one protected-swing life be reaffirmed repeatedly "
                    "without becoming a new level?",
        "status": CERTIFIED,
        "facts": ("protected_swing.registered_at",),
        "gap": None,
    },
    {
        "capability_id": "swing.new_life_at_same_price",
        "question": "Can a NEW protected-swing life form later at the same "
                    "numeric price and be told apart from the first?",
        "status": CERTIFIED,
        "facts": ("protected_swing.registered_at", "protected_swing.swing_id"),
        "gap": None,
    },
    {
        "capability_id": "swing.survival_duration",
        "question": "Can the Brain compute how long a protected level has "
                    "survived unviolated?",
        "status": CERTIFIED,
        "facts": ("protected_swing.registered_at",),
        "gap": None,
    },
    {
        "capability_id": "occurrence.htf_event_observed_repeatedly",
        "owner_unit": "CAUSAL-IDENTITY-VERSION-GATE-1",
        "question": "Can one HTF event observed on many scans be counted ONCE?",
        "status": PARTIAL,
        "facts": ("occurrence.causal_event_key.category_a",
                  "occurrence.occurrence_id"),
        "gap": "The Category A capability exists and is certified, but "
               "production still runs v1, where 15 observations of one 15m "
               "structure break are 15 durable rows. Activation is owned by "
               "CAUSAL-IDENTITY-VERSION-GATE-1 and blocked behind "
               "SWEEP-OCCURRENCE-AUTHORITY-1.",
    },
    {
        "capability_id": "occurrence.protected_swing_event_identity",
        "owner_unit": "CAUSAL-OCCURRENCE-IDENTITY-1B",
        "question": "Can a protected-swing transition be identified as a market "
                    "EVENT rather than as an observation?",
        "status": BLOCKED,
        "facts": ("occurrence.causal_event_key.category_b",),
        "gap": "No Category B key is minted. The provenance is now true after "
               "PROTECTED-SWING-CAUSAL-TIME-1; only the wiring remains. "
               "Owned by CAUSAL-OCCURRENCE-IDENTITY-1B.",
    },
    {
        "capability_id": "occurrence.single_semantic_owner",
        "owner_unit": "SWEEP-OCCURRENCE-AUTHORITY-1",
        "question": "Does exactly one subsystem own the truth of a liquidity "
                    "sweep occurrence?",
        "status": BLOCKED,
        "facts": ("occurrence.sweep_writer_authority",),
        "gap": "Two writers target one store with two id schemes (103 rows vs 3 "
               "in the live store). Owned by SWEEP-OCCURRENCE-AUTHORITY-1.",
    },
    {
        "capability_id": "startup.complete_session_history",
        "owner_unit": "STARTUP-RECOVERY-INTEGRATION",
        "question": "If the process starts at 10:31, does it hold the session's "
                    "causal history from the open?",
        "status": BLOCKED,
        "facts": ("recovery.session_state_completeness",),
        "gap": "NO. The recovery kernel is certified and deterministic but no "
               "production module imports it; live startup begins cold. Owned by "
               "STARTUP-RECOVERY-INTEGRATION.",
    },
    {
        "capability_id": "liquidity.pool_formation_time",
        "owner_unit": "LIQUIDITY-POOL-LIFECYCLE-1",
        "question": "Can the organism say WHEN a liquidity pool formed?",
        "status": BLOCKED,
        "facts": ("liquidity.pool_lifecycle",),
        "gap": "Pools carry price and timeframe, never formation provenance. "
               "Owned by LIQUIDITY-POOL-LIFECYCLE-1.",
    },
    {
        "capability_id": "liquidity.pool_consumed_state",
        "owner_unit": "LIQUIDITY-POOL-LIFECYCLE-1",
        "question": "Can the organism say whether THIS EXACT pool has been taken?",
        "status": BLOCKED,
        "facts": ("liquidity.pool_lifecycle",),
        "gap": "No consumed state exists. A re-formed pool at a swept price is "
               "indistinguishable from an untouched one. Owned by "
               "LIQUIDITY-POOL-LIFECYCLE-1.",
    },
    {
        "capability_id": "range.containment",
        "owner_unit": "ACTIVE-RANGE-CONTAINMENT-1",
        "question": "Is the published dealing range still the OPERATIVE one, and "
                    "is price actually inside it?",
        "status": BLOCKED,
        "facts": ("dealing_range.containment", "dealing_range.bounds"),
        "gap": "`position` is unclamped, so price outside the range still "
               "reports 'premium' or 'discount', and midpoint / mean-threshold "
               "authority is blocked. Owned by ACTIVE-RANGE-CONTAINMENT-1.",
    },
    {
        "capability_id": "objective.primary_vs_available_draw",
        "owner_unit": "LIQUIDITY-POOL-LIFECYCLE-1",
        "question": "Can the organism distinguish the PRIMARY draw on price from "
                    "a merely available farther one?",
        "status": BLOCKED,
        "facts": ("liquidity.scale_hierarchy", "liquidity.brain.nearest_buy_side"),
        "gap": "Selection is highest-timeframe-first availability, not draw "
               "strength. It needs the scale hierarchy in the payload AND pool "
               "lifecycle to say which pools remain untaken. "
               "Owned by LIQUIDITY-POOL-LIFECYCLE-1.",
    },
)

_VALID_STATUS = (CERTIFIED, PARTIAL, BLOCKED)


def validate_matrix() -> list:
    """Every reason the matrix is not internally honest.

    THE RULES ARE ASYMMETRIC ON PURPOSE. A BLOCKED capability must name its gap
    -- an unexplained "no" teaches nothing and cannot be closed. A CERTIFIED
    capability must NOT name one, and must rest only on CERTIFIED facts: a
    capability is exactly as trustworthy as its weakest fact, and claiming
    otherwise is the drift this file exists to prevent.
    """
    problems = []
    registry = by_id()
    seen = set()
    for cap in CAPABILITIES:
        cid = cap.get("capability_id") or "<no capability_id>"
        if cid in seen:
            problems.append(f"{cid}: duplicate capability_id")
        seen.add(cid)
        if not cap.get("question"):
            problems.append(f"{cid}: states no question")
        status = cap.get("status")
        if status not in _VALID_STATUS:
            problems.append(f"{cid}: status {status!r} is not one of "
                            f"{list(_VALID_STATUS)}")
        facts = cap.get("facts") or ()
        if not facts:
            problems.append(f"{cid}: cites no fact contract")
        for fid in facts:
            if fid not in registry:
                problems.append(f"{cid}: cites unregistered fact {fid!r}")
        if status == BLOCKED and not cap.get("gap"):
            problems.append(f"{cid}: BLOCKED without naming the gap")
        if status == PARTIAL and not cap.get("gap"):
            problems.append(f"{cid}: PARTIAL without naming what is missing")
        # REMEDIATION OWNERSHIP IS A FIELD, NOT A TURN OF PHRASE. An earlier
        # version inferred it by looking for "-1" in the gap text, which quietly
        # passed units named without a numeric suffix and would have passed any
        # sentence that happened to contain a hyphen and a digit.
        if status in (BLOCKED, PARTIAL) and not cap.get("owner_unit"):
            problems.append(f"{cid}: {status} without an owner_unit; a gap that "
                            f"names no owner is a complaint, not a plan")
        if status == CERTIFIED and cap.get("owner_unit"):
            problems.append(f"{cid}: CERTIFIED but names a remediation owner")
        if status == CERTIFIED:
            if cap.get("gap"):
                problems.append(f"{cid}: CERTIFIED but names a gap")
            for fid in facts:
                fact = registry.get(fid) or {}
                if fact.get("authority_class") != CERTIFIED:
                    problems.append(
                        f"{cid}: CERTIFIED but rests on {fid!r} which is "
                        f"{fact.get('authority_class')}")
    return problems


def status_of(capability_id) -> "str | None":
    for cap in CAPABILITIES:
        if cap.get("capability_id") == capability_id:
            return cap.get("status")
    return None


def blocked() -> list:
    return [c for c in CAPABILITIES if c.get("status") == BLOCKED]


def summary() -> dict:
    out = {CERTIFIED: 0, PARTIAL: 0, BLOCKED: 0}
    for cap in CAPABILITIES:
        if cap.get("status") in out:
            out[cap["status"]] += 1
    return out
