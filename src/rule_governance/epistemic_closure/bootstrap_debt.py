"""EPISTEMIC-CLOSURE-CERTIFICATION-1 — the debt that already existed.

WHAT THIS IS: a frozen historical inventory of authority relationships that were
ALREADY IN PRODUCTION at the moment this gate was introduced.

WHAT THIS IS NOT: permission. Nothing here authorises new authority, and the
mechanism is deliberately built so it cannot be used that way.

THE MISTAKE THIS REPLACES. The first attempt let any contract carry an
`accepted_promotion` block with a reason, an owner and a date, and be excused.
That reasoning started honestly -- three LEGACY/BLOCKED facts genuinely ARE read
by `brain_prompt` today, and demoting them is a payload change owned by other
units -- but it generalised. Any future BLOCKED fact could have acquired
decision authority by writing three lines of prose. That is not a gate; it is a
form to fill in, and eventually it becomes the way somebody makes the build
green.

THREE PROPERTIES MAKE THIS DIFFERENT:

    FROZEN     the exact set of fact_ids is pinned here and in a regression.
               A new entry breaks that test, which is the point: adding one
               must be a conscious, reviewed governance act, not a diff nobody
               reads.

    EXACT      each entry pins the precise blast radius -- which consumers,
               which payload paths, which influence. Grandfathering freezes an
               existing relationship; it does not licence that relationship to
               spread. A new consumer of a grandfathered fact FAILS.

    SHRINKING  the desired direction is removal. When
               OBJECTIVE-SCALE-PRESERVATION-1B replaces the flattened nearest
               fields, their debt should DISAPPEAR from this file. Nothing
               requires historical debt to live forever, and the verifier is
               built to notice when a debt no longer corresponds to reality.
"""
from __future__ import annotations

import os

#: The date this gate was introduced. An authority relationship discovered after
#: this may NOT be grandfathered -- it must be certified or removed.
BOOTSTRAP_DATE = "2026-08-25"
BOOTSTRAP_UNIT = "EPISTEMIC-CLOSURE-CERTIFICATION-1"

#: THE IMMUTABLE UNIVERSE. Every authority relationship that already existed
#: when this gate was introduced -- the complete historical set, frozen forever.
#:
#: A fact NOT in here may never become grandfathered debt, at any later date, by
#: any route. That is what stops "bootstrap debt" from becoming a category
#: somebody adds to. A regression pins this set, so changing it fails loudly and
#: requires a conscious governance review rather than a diff nobody reads.
BOOTSTRAP_DEBT_UNIVERSE = frozenset({
    "liquidity.brain.nearest_buy_side",
    "liquidity.brain.nearest_sell_side",
    "dealing_range.containment",
})

#: Backwards-compatible alias for the universe. The ACTIVE subset is derived
#: below and is what shrinks as debts are remediated.
GRANDFATHERED_FACT_IDS = BOOTSTRAP_DEBT_UNIVERSE

#: One entry per grandfathered authority relationship, pinning its exact
#: existing blast radius as measured during bootstrap.
GRANDFATHERED_AUTHORITY_DEBT = (
    {
        "fact_id": "liquidity.brain.nearest_buy_side",
        "producer_module": "ai_brain.brain_input",
        "authority_class": "LEGACY",
        "payload_paths": ("liquidity.nearest_buy_side",),
        "consumers": ("ai_brain.brain_prompt",),
        "influence": "brain_narrative",
        "discovered_on": BOOTSTRAP_DATE,
        "reason":
            "The field reaches the Brain today and its name misdescribes it: "
            "`brain_input` selects the first non-null pool scanning "
            "15m -> 5m -> 3m -> 1m, so a distant 15m pool outranks a close 1m "
            "one. Measured 35/35 archived payloads published a pool that was "
            "not the nearest. Removing it changes what Luna receives, which is "
            "a payload decision this governance unit may not make.",
        "remediation_owner_unit": "OBJECTIVE-SCALE-PRESERVATION-1B",
        "remediation_target_unit": "OBJECTIVE-SCALE-PRESERVATION-1B",
    },
    {
        "fact_id": "liquidity.brain.nearest_sell_side",
        "producer_module": "ai_brain.brain_input",
        "authority_class": "LEGACY",
        "payload_paths": ("liquidity.nearest_sell_side",),
        "consumers": ("ai_brain.brain_prompt",),
        "influence": "brain_narrative",
        "discovered_on": BOOTSTRAP_DATE,
        "reason":
            "The sell-side twin, flattened by the same `next()` precedence. "
            "Measured 15/35 archived payloads published a pool that was not the "
            "nearest.",
        "remediation_owner_unit": "OBJECTIVE-SCALE-PRESERVATION-1B",
        "remediation_target_unit": "OBJECTIVE-SCALE-PRESERVATION-1B",
    },
    {
        "fact_id": "dealing_range.containment",
        "producer_module": "structure.market_context",
        "authority_class": "BLOCKED",
        "payload_paths": ("market.dealing_range",),
        "consumers": ("ai_brain.brain_prompt",),
        "influence": "brain_narrative",
        "discovered_on": BOOTSTRAP_DATE,
        "reason":
            "Premium/discount reaches the Brain via `market.dealing_range`. "
            "`market_context._dealing_range` computes position without "
            "clamping, so price above the range yields position 1.5 still "
            "labelled 'premium', and a real archived payload showed -0.683 "
            "labelled 'discount'. Clamping or removing the zone changes what "
            "Luna is told and belongs to the containment unit.",
        "remediation_owner_unit": "ACTIVE-RANGE-CONTAINMENT-1",
        "remediation_target_unit": "ACTIVE-RANGE-CONTAINMENT-1",
    },
)

#: RETIRED DEBTS. Historical evidence that a bootstrap debt was remediated --
#: and NOTHING ELSE.
#:
#: A tombstone is not a consumer exemption, not a payload permission, not a
#: LEGACY authority, and not a route back. If the same fact later regains
#: decision authority it is NEW authority and must be certified; the tombstone
#: does not help it.
#:
#: WHY TOMBSTONES EXIST AT ALL. Remediation must be provable while the debt
#: record still exists, otherwise "the entry is gone" would prove its own
#: legitimacy -- deletion certifying deletion. So the ACTIVE record is retired
#: only after `resolution_state` returns ELIGIBLE_FOR_REMOVAL, and what remains
#: is this inert historical note. Active debt shrinks to zero over time; the
#: historical fact that we once grandfathered it does not have to vanish with it.
REMEDIATED_BOOTSTRAP_DEBTS = ()

TOMBSTONE_FIELDS = ("fact_id", "remediated_on", "remediation_owner_unit",
                    "remediation_target_unit", "proof")

REQUIRED_FIELDS = ("fact_id", "authority_class", "payload_paths", "consumers",
                   "producer_module",
                   "influence", "discovered_on", "reason",
                   "remediation_owner_unit", "remediation_target_unit")


def by_id() -> dict:
    return {d["fact_id"]: d for d in GRANDFATHERED_AUTHORITY_DEBT}


def active_fact_ids() -> frozenset:
    """The UNRESOLVED subset. This is what shrinks; the universe never does."""
    return frozenset(d["fact_id"] for d in GRANDFATHERED_AUTHORITY_DEBT)


def remediated_fact_ids() -> frozenset:
    return frozenset(t["fact_id"] for t in REMEDIATED_BOOTSTRAP_DEBTS)


def is_grandfathered(fact_id) -> bool:
    """Does this fact currently carry ACTIVE grandfathered debt?

    A remediated fact is NOT grandfathered. Its tombstone is history, not an
    exemption, so if it reacquires decision authority the promotion gate treats
    that as new authority and blocks.
    """
    return fact_id in active_fact_ids()


def validate_manifest() -> list:
    """The manifest's own integrity. Never trusts itself."""
    problems = []
    seen = set()
    for debt in GRANDFATHERED_AUTHORITY_DEBT:
        fid = debt.get("fact_id") or "<no fact_id>"
        for field in REQUIRED_FIELDS:
            if not debt.get(field):
                problems.append(f"{fid}: grandfathered debt is missing {field!r}")
        if fid in seen:
            problems.append(f"{fid}: duplicate grandfathered entry")
        seen.add(fid)
        # THE ANTI-EXPANSION RULE: an entry outside the immutable universe is a
        # new debt wearing an old debt's clothes.
        if fid not in BOOTSTRAP_DEBT_UNIVERSE:
            problems.append(
                f"NEW_POST_GATE_DEBT {fid}: present in the active debt manifest "
                f"but NOT in BOOTSTRAP_DEBT_UNIVERSE. Authority introduced after "
                f"{BOOTSTRAP_UNIT} cannot grandfather itself; it must be "
                f"certified or removed")
        if debt.get("discovered_on") != BOOTSTRAP_DATE:
            problems.append(
                f"{fid}: discovered_on {debt.get('discovered_on')!r} is not the "
                f"bootstrap date {BOOTSTRAP_DATE!r}. Authority introduced after "
                f"{BOOTSTRAP_UNIT} may not be grandfathered")
    # A universe member must be either ACTIVE or REMEDIATED -- never simply
    # missing, which is how a debt would quietly disappear unproven.
    accounted = seen | remediated_fact_ids()
    for fid in BOOTSTRAP_DEBT_UNIVERSE - accounted:
        problems.append(
            f"{fid}: in BOOTSTRAP_DEBT_UNIVERSE but neither an active debt nor "
            f"a remediation tombstone. A debt may not vanish without proof")

    for tomb in REMEDIATED_BOOTSTRAP_DEBTS:
        tid = tomb.get("fact_id") or "<no fact_id>"
        for field in TOMBSTONE_FIELDS:
            if not tomb.get(field):
                problems.append(f"{tid}: remediation tombstone missing {field!r}")
        if tid not in BOOTSTRAP_DEBT_UNIVERSE:
            problems.append(
                f"{tid}: remediation tombstone for a fact that was never "
                f"bootstrap debt")
        if tid in seen:
            problems.append(
                f"{tid}: is BOTH an active debt and a remediation tombstone")
    return problems


def authority_surface(debt) -> tuple:
    """The EXACT blast radius, as a comparable value.

    Grandfathering freezes this tuple. Anything that widens it -- another
    consumer, another payload path, a stronger influence -- is new authority and
    must be certified rather than inherited.
    """
    return (debt.get("fact_id"),
            tuple(sorted(debt.get("payload_paths") or ())),
            tuple(sorted(debt.get("consumers") or ())),
            debt.get("influence"))


# ── DEBT STATES ─────────────────────────────────────────────────────────────
#: The authority still exists. The normal state.
ACTIVE = "ACTIVE"
#: The inspector could not resolve producer or consumer authority. NOT eligible
#: for removal -- an unresolved relationship is not a removed one.
REVIEW_REQUIRED = "REVIEW_REQUIRED"
#: Producer ABSENT, consumer ABSENT, governance remediation PROVEN. The active
#: entry may now be retired to a tombstone.
ELIGIBLE_FOR_REMOVAL = "ELIGIBLE_FOR_REMOVAL"
#: Retired. Historical evidence only, with zero authority of any kind.
REMEDIATED = "REMEDIATED"

#: Absence of a path in one payload. DIAGNOSTIC ONLY -- never an input to state.
NOT_OBSERVED = "NOT_OBSERVED_IN_FIXTURE"


def resolution_state(debt, contract, *, src_root, observed_paths=None) -> dict:
    """Is this debt still real? THREE INDEPENDENT PROOFS, none of them absence.

    THE ERROR THIS REFUSES. An earlier version emitted a resolution whenever a
    frozen payload path was missing from the current payload. That is the
    framework committing the exact mistake it exists to prevent: a market-fact
    branch is CONDITIONAL, so a path can vanish because this specimen had no
    active protected swing, an empty list, or an absent timeframe family. "I did
    not observe it" is evidence about the specimen, never proof that an
    authority relationship was deleted from the organism.

    THE SECOND ERROR THIS REFUSES. Producer and consumer authority are TRI-STATE.
    A static inspector is not omniscient: a payload assembled through a helper,
    an alias, a computed key or a merge can carry a field whose name never
    appears as a literal. Treating "I found nothing" as "it is gone" would
    reintroduce failure-to-prove-presence as proof-of-absence one layer down.
    UNKNOWN therefore keeps a debt alive as REVIEW_REQUIRED.

    Retirement requires ALL THREE:

        producer_authority  == ABSENT
        consumer_authority  == ABSENT
        governance          == PROVEN

    Governance proof is deliberately NOT "the debt entry disappeared" -- that
    would let removal prove its own legitimacy. It is read from the LIVE
    contract: the fact no longer declares the grandfathered authority class, and
    no consumer still claims the grandfathered influence.
    """
    from rule_governance.epistemic_closure import authority_ast as AST

    leaf_names = {p.split(".")[-1] for p in debt.get("payload_paths") or ()}

    # ── A. PRODUCER ─────────────────────────────────────────────────────────
    producer_files = _module_files(src_root, debt.get("producer_module"))
    producer = {"state": AST.UNKNOWN, "unresolved": [{"reason": "no producer"}]}
    for leaf in sorted(leaf_names):
        result = AST.field_authority(producer_files, leaf)
        if result["state"] == AST.PRESENT:
            producer = result
            break
        producer = result if producer["state"] != AST.UNKNOWN else result

    # ── B. CONSUMER ─────────────────────────────────────────────────────────
    consumer_files = []
    for consumer in debt.get("consumers") or ():
        consumer_files.extend(_module_files(src_root, consumer))
    consumer = {"state": AST.UNKNOWN, "unresolved": [{"reason": "no consumer"}]}
    for leaf in sorted(leaf_names):
        result = AST.field_authority(consumer_files, leaf)
        if result["state"] == AST.PRESENT:
            consumer = result
            break
        consumer = result

    # ── C. GOVERNANCE ───────────────────────────────────────────────────────
    from rule_governance.epistemic_closure.fact_contract import DECISION_BEARING
    live_class = (contract or {}).get("authority_class")
    still_declared = live_class == debt.get("authority_class")
    still_claimed = any(
        c.get("name") in (debt.get("consumers") or ())
        and c.get("influence") in DECISION_BEARING
        for c in (contract or {}).get("consumers") or [])
    governance_proven = not still_declared and not still_claimed

    # ── the verdict ─────────────────────────────────────────────────────────
    states = (producer["state"], consumer["state"])
    if AST.PRESENT in states or not governance_proven:
        state = ACTIVE
    elif AST.UNKNOWN in states:
        state = REVIEW_REQUIRED
    else:
        state = ELIGIBLE_FOR_REMOVAL

    observed = None
    if observed_paths is not None:
        observed = bool(set(debt.get("payload_paths") or ()) & set(observed_paths))

    return {
        "fact_id": debt.get("fact_id"),
        "state": state,
        "producer_authority": producer["state"],
        "consumer_authority": consumer["state"],
        "governance_remediation": "PROVEN" if governance_proven else "NOT_PROVEN",
        "unresolved": (producer.get("unresolved") or []) +
                      (consumer.get("unresolved") or []),
        # DIAGNOSTIC ONLY. Never an input to `state`.
        "observed_in_fixture": observed,
        "note": (NOT_OBSERVED if observed is False and state == ACTIVE else None),
        "remediation_owner": debt.get("remediation_owner_unit"),
    }


def _module_files(src_root, dotted) -> list:
    """Every source file for a dotted module or package. Empty when unknown."""
    if not dotted:
        return []
    base = os.path.join(src_root, *dotted.split("."))
    if os.path.isfile(base + ".py"):
        return [base + ".py"]
    if os.path.isdir(base):
        return [os.path.join(base, n) for n in os.listdir(base)
                if n.endswith(".py")]
    return []


def check_class_drift(contract) -> list:
    """Has a grandfathered fact's DECLARED authority class changed?

    THE GAP THIS CLOSES. Grandfathering excuses a fact from the promotion gate,
    so without this check the way to promote one was simply to edit its
    contract: mark the LEGACY liquidity field CERTIFIED and nothing objected,
    because the promotion gate had already stepped aside for it. The debt
    manifest records the class the fact HAD at bootstrap, and a divergence means
    one of two things -- a silent promotion, or a real remediation that owes a
    tombstone. Both require review; neither may pass quietly.
    """
    fid = (contract or {}).get("fact_id")
    debt = by_id().get(fid)
    if debt is None:
        return []
    live = contract.get("authority_class")
    recorded = debt.get("authority_class")
    if live == recorded:
        return []
    return [{
        "kind": "AUTHORITY_EXPANSION", "fact_id": fid,
        "detail": (f"grandfathered debt recorded authority_class {recorded!r} at "
                   f"{debt['discovered_on']}, but the contract now declares "
                   f"{live!r}. Grandfathering excuses this fact from the "
                   f"promotion gate, so changing its class here would be a "
                   f"silent promotion. If {debt['remediation_owner_unit']} has "
                   f"genuinely remediated it, retire the debt to a tombstone "
                   f"instead."),
        "remediation_owner": debt.get("remediation_owner_unit")}]


def check_expansion(contract, coverage_paths=None) -> list:
    """Has a grandfathered fact's authority GROWN since bootstrap?

    Compares the live contract -- its declared consumers and, when a real
    payload is supplied, the paths it actually occupies -- against the frozen
    surface. Returns AUTHORITY_EXPANSION findings, one per widening.
    """
    fid = (contract or {}).get("fact_id")
    debt = by_id().get(fid)
    if debt is None:
        return []

    findings = []
    frozen_consumers = set(debt.get("consumers") or ())
    from rule_governance.epistemic_closure.fact_contract import DECISION_BEARING
    live_consumers = {c.get("name") for c in contract.get("consumers") or []
                      if c.get("influence") in DECISION_BEARING}
    new_consumers = sorted(live_consumers - frozen_consumers)
    if new_consumers:
        findings.append({
            "kind": "AUTHORITY_EXPANSION", "fact_id": fid,
            "detail": (f"grandfathered debt gained decision-bearing consumer(s) "
                       f"{new_consumers}. Grandfathering freezes the authority "
                       f"that existed on {debt['discovered_on']}; it does not "
                       f"licence new consumers. Certify the fact or revert."),
            "remediation_owner": debt["remediation_owner_unit"]})

    frozen_influence = debt.get("influence")
    for consumer in contract.get("consumers") or []:
        influence = consumer.get("influence")
        if influence in DECISION_BEARING and influence != frozen_influence:
            findings.append({
                "kind": "AUTHORITY_EXPANSION", "fact_id": fid,
                "detail": (f"consumer {consumer.get('name')!r} now claims "
                           f"{influence!r}; the frozen influence is "
                           f"{frozen_influence!r}"),
                "remediation_owner": debt["remediation_owner_unit"]})

    if coverage_paths is not None:
        frozen_paths = set(debt.get("payload_paths") or ())
        extra = sorted(set(coverage_paths) - frozen_paths) if coverage_paths else []
        if extra:
            findings.append({
                "kind": "AUTHORITY_EXPANSION", "fact_id": fid,
                "detail": (f"grandfathered debt occupies payload path(s) "
                           f"{extra} beyond its frozen surface "
                           f"{sorted(frozen_paths)}"),
                "remediation_owner": debt["remediation_owner_unit"]})
    return findings
