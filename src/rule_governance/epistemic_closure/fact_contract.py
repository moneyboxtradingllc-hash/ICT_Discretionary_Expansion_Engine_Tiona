"""EPISTEMIC-CLOSURE-CERTIFICATION-1 — what a market fact must declare.

THE DOCTRINE THIS ENFORCES:

    NO MARKET FACT MAY RECEIVE LUNA DECISION AUTHORITY UNTIL ITS SEMANTIC,
    LIFECYCLE, TEMPORAL, AUTHORITY, CONSUMER AND REPLAY CONTRACTS ARE
    EXPLICITLY CERTIFIED.

A field name is not a semantic contract. A green unit test is not epistemic
certification. Both were true of `registered_at`, which every consumer read as
"when the level was born" while the producer re-stamped it on every
reaffirmation -- 24 of 33 lives on the 2026-08-24 tape, one of them 18 times.
The tests were green throughout, because no test had ever been asked to state
what the field MEANT.

WHY THIS LIVES BESIDE `rule_governance`, NOT INSIDE IT. That package governs
RULES -- predicates that gate candidates, with a shadow/promoted lifecycle and a
mutable runtime registry under `data/`. This governs FACTS -- what the organism
claims about the market. The conventions are deliberately mirrored (declaration
as data, logic as code, an explicit status lifecycle, quarantine rather than
raise) because they are the right conventions; the subject is different, and
collapsing the two would put "may this rule block a trade?" and "what does this
number mean?" under one owner.

WHY THE CONTRACTS ARE SOURCE, NOT `data/`. `rule_governance` keeps its registry
in `data/rule_governance/registry.json` because rule STATUS is runtime state
that a session mutates. A fact contract is not runtime state: it is a claim
about what the code means, it must be reviewable in a diff, and it must be
identical on every machine. Storing it under `data/` would reproduce the
machine-local evidence failure this repository has already paid for -- a
verifier that passes because a file is missing is worse than no verifier.
"""
from __future__ import annotations

# ── AUTHORITY CLASSES ───────────────────────────────────────────────────────
#: Certified across every contract dimension. ELIGIBLE for decision authority.
CERTIFIED = "CERTIFIED"
#: Reaches the Brain and may inform it, but may not be the sole basis of a
#: decision. Honest middle ground for facts that are true but incomplete.
ADVISORY = "ADVISORY"
#: Witness/telemetry. Present, readable, and explicitly barred from deciding.
OBSERVE_ONLY = "OBSERVE_ONLY"
#: A field whose NAME does not mean what a reader would assume, kept for
#: compatibility. Naming it LEGACY is the point: it may not be certified under a
#: semantic it does not have.
LEGACY = "LEGACY"
#: A claim the organism CANNOT currently make. Registering it is not an
#: admission of failure -- it is the difference between a gap and a lie.
BLOCKED = "BLOCKED"

AUTHORITY_CLASSES = (CERTIFIED, ADVISORY, OBSERVE_ONLY, LEGACY, BLOCKED)

#: Classes that may NEVER hold decision-bearing influence. The promotion gate
#: is built on this tuple.
NON_DECIDING = (OBSERVE_ONLY, LEGACY, BLOCKED)

# ── DECISION INFLUENCE ──────────────────────────────────────────────────────
BRAIN_NARRATIVE = "brain_narrative"
CANDIDATE_GENERATION = "candidate_generation"
OBJECTIVE_RANKING = "objective_ranking"
RISK = "risk"
EXECUTION = "execution"
TELEMETRY_ONLY = "telemetry_only"

INFLUENCES = (BRAIN_NARRATIVE, CANDIDATE_GENERATION, OBJECTIVE_RANKING, RISK,
              EXECUTION, TELEMETRY_ONLY)

#: Anything other than pure telemetry is decision-bearing.
DECISION_BEARING = tuple(i for i in INFLUENCES if i != TELEMETRY_ONLY)

# ── PERSISTENCE ─────────────────────────────────────────────────────────────
RAM_ONLY = "ram_only"            # dies with the process, by design
DURABLE = "durable"              # written to an append-only store
RECOMPUTED = "recomputed"        # derived every scan, never persisted

PERSISTENCE = (RAM_ONLY, DURABLE, RECOMPUTED)

# ── ADVERSARIAL SCENARIOS ───────────────────────────────────────────────────
#: The scenario vocabulary a contract draws from. Each one is a defect class
#: this repository has ACTUALLY suffered, which is why the list is short and
#: specific rather than a generic QA checklist.
LATE_START = "late_start"                     # the bot launched at 10:31
PROCESS_RESTART = "process_restart"           # a mid-session restart
REPEATED_HTF_EDGE = "repeated_htf_edge"       # one 15m bucket, fifteen scans
REPEATED_PRICE = "repeated_price"             # the same level visited twice
REAFFIRMED_LIFE = "reaffirmed_life"           # same swing, more evidence
NEW_LIFE_SAME_PRICE = "new_life_same_price"   # death, then rebirth at one price
MTF_DISAGREEMENT = "mtf_disagreement"         # timeframes that do not concur
MISSING_QUOTE = "missing_quote"               # no executable price exists
SESSION_BOUNDARY = "session_boundary"         # session / contract rollover
WARMUP_HISTORY = "warmup_history"             # state formed before the session

SCENARIOS = (LATE_START, PROCESS_RESTART, REPEATED_HTF_EDGE, REPEATED_PRICE,
             REAFFIRMED_LIFE, NEW_LIFE_SAME_PRICE, MTF_DISAGREEMENT,
             MISSING_QUOTE, SESSION_BOUNDARY, WARMUP_HISTORY)

#: Required on every contract. A contract missing any of these is INVALID and
#: is quarantined with a reason -- never silently accepted.
REQUIRED_FIELDS = (
    "fact_id",              # stable identity of the fact
    "producer_owner",       # the ONE subsystem that owns its truth
    "representation",       # where it physically lives
    "semantic_claim",       # precise prose: what it asserts about the market
    "authority_class",      # CERTIFIED / ADVISORY / OBSERVE_ONLY / LEGACY / BLOCKED
    "decision_influence",   # which decisions it may touch
    "persistence",          # ram_only / durable / recomputed
    "lifecycle",            # formation / mutation / invalidation
    "temporal",             # which clocks it carries and what each means
    "restart",              # what a fresh process sees
    "late_start",           # what a process that started late sees
    "consumers",            # who reads it, and what each believes it means
    "limitations",          # what it CANNOT say. May be empty; never absent.
    "certification_tests",  # the tests that prove the above
    "scenarios",            # which adversarial scenarios apply
)

#: `lifecycle` must answer all three. "It appears and it disappears" is not a
#: lifecycle contract -- almost every defect this framework exists to catch
#: lived at the REPEATED-EVIDENCE boundary, which is exactly `mutation`.
LIFECYCLE_KEYS = ("formation", "mutation", "invalidation")

#: `temporal` must name each clock it carries or explicitly say it has none.
#: Conflating these is the defect class that produced both the fifteen-fold
#: HTF duplication and the re-stamped protected swing.
TEMPORAL_KEYS = ("formation_time", "event_time", "observation_time")


class FactContractError(ValueError):
    """A malformed contract. Never raised during verification -- verification
    QUARANTINES and reports. This exists for construction-time misuse."""


def is_decision_bearing(contract) -> bool:
    """Does this fact touch anything other than telemetry?"""
    influences = (contract or {}).get("decision_influence") or ()
    return any(i in DECISION_BEARING for i in influences)


def validate(contract) -> list:
    """Every reason this contract is invalid. Empty list means well-formed.

    WELL-FORMED IS NOT CERTIFIED. This checks that a contract SAYS the required
    things; whether what it says is TRUE is the verifier's job, and whether the
    code agrees is the certification tests' job.
    """
    problems = []
    if not isinstance(contract, dict):
        return ["contract is not a mapping"]

    fid = contract.get("fact_id") or "<no fact_id>"
    #: MAY BE EMPTY, but never absent.
    #:
    #: `limitations` -- a fact may genuinely have none worth stating.
    #: `consumers`   -- a BLOCKED or not-yet-wired fact has NO readers, and that
    #:                  is precisely what those statuses mean. Demanding a
    #:                  consumer here would push an author to invent one, which
    #:                  is the failure mode this whole framework exists to stop.
    #:                  A CERTIFIED decision-bearing fact with no consumers is
    #:                  still a contradiction, and is caught separately below.
    may_be_empty = ("limitations", "consumers")
    for field in REQUIRED_FIELDS:
        if field not in contract:
            problems.append(f"{fid}: missing required field {field!r}")
        elif field not in may_be_empty and contract.get(field) in (None, "", (), []):
            problems.append(f"{fid}: {field!r} is empty")

    cls = contract.get("authority_class")
    if cls is not None and cls not in AUTHORITY_CLASSES:
        problems.append(f"{fid}: authority_class {cls!r} is not one of "
                        f"{list(AUTHORITY_CLASSES)}")

    for inf in contract.get("decision_influence") or ():
        if inf not in INFLUENCES:
            problems.append(f"{fid}: decision_influence {inf!r} is unknown")

    if contract.get("persistence") not in (None, *PERSISTENCE):
        problems.append(f"{fid}: persistence {contract['persistence']!r} is unknown")

    life = contract.get("lifecycle")
    if isinstance(life, dict):
        for key in LIFECYCLE_KEYS:
            if not life.get(key):
                problems.append(f"{fid}: lifecycle.{key} is not declared")
    elif "lifecycle" in contract:
        problems.append(f"{fid}: lifecycle must be a mapping of "
                        f"{list(LIFECYCLE_KEYS)}")

    temporal = contract.get("temporal")
    if isinstance(temporal, dict):
        unknown = [k for k in temporal if k not in TEMPORAL_KEYS]
        if unknown:
            problems.append(f"{fid}: temporal declares unknown clocks {unknown}")
        if not any(temporal.get(k) for k in TEMPORAL_KEYS):
            problems.append(f"{fid}: temporal declares no clock at all; a fact "
                            f"with no time semantics must say so explicitly")
    elif "temporal" in contract:
        problems.append(f"{fid}: temporal must be a mapping")

    for name in contract.get("scenarios") or ():
        if name not in SCENARIOS:
            problems.append(f"{fid}: adversarial scenario {name!r} is unknown")

    consumers = contract.get("consumers")
    if isinstance(consumers, (list, tuple)):
        for c in consumers:
            if not isinstance(c, dict) or not c.get("name"):
                problems.append(f"{fid}: each consumer needs a name")
            elif not c.get("believes"):
                # THE `registered_at` DEFECT IN ONE RULE. A consumer that does
                # not state what it believes cannot be checked against the
                # producer, and that mismatch is exactly what shipped.
                problems.append(f"{fid}: consumer {c.get('name')!r} does not "
                                f"state what it believes the fact means")
    elif "consumers" in contract:
        problems.append(f"{fid}: consumers must be a list")

    # THE PROMOTION GATE, at the contract level. A fact that cannot be trusted
    # may not quietly acquire authority by editing one line.
    if cls in NON_DECIDING and is_decision_bearing(contract):
        problems.append(
            f"{fid}: authority_class {cls} may not hold decision influence "
            f"{list(contract.get('decision_influence') or ())} -- promoting it "
            f"requires certification, not a field edit")

    if cls == CERTIFIED and not (contract.get("certification_tests") or ()):
        problems.append(f"{fid}: CERTIFIED with no certification tests")

    # A fact that reaches a decision must say WHO acts on it. Otherwise the
    # producer/consumer agreement check below has nothing to check against, and
    # "who would notice if this were wrong?" has no answer.
    if is_decision_bearing(contract) and not (contract.get("consumers") or ()):
        problems.append(f"{fid}: decision-bearing but names no consumer")

    return problems
