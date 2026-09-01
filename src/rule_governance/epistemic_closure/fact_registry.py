"""EPISTEMIC-CLOSURE-CERTIFICATION-1 — the contracts themselves.

WHAT THE ORGANISM CLAIMS ABOUT THE MARKET, declared once, in source, reviewable
in a diff. Every entry states what a fact MEANS, who owns it, how it is born,
what may change it, what kills it, which clocks it carries, what survives a
restart, who reads it, and what it CANNOT say.

BOOTSTRAPPED FROM EVIDENCE, NOT FROM OPTIMISM. Nothing here is marked CERTIFIED
to make the verifier green. Several load-bearing facts are registered BLOCKED or
LEGACY precisely because the organism cannot presently back them, and the
verifier passing means it knows both what it knows and what it does not.

Facts are keyed by `fact_id`. Payload paths are the CANONICAL BRAIN PAYLOAD
paths produced by `ai_brain.brain_input.build_brain_input`, so coverage is
checked against what Luna actually receives rather than against source text.
"""
from __future__ import annotations

from rule_governance.epistemic_closure.fact_contract import (ADVISORY, BLOCKED, BRAIN_NARRATIVE,
                                           CANDIDATE_GENERATION, CERTIFIED,
                                           DURABLE, EXECUTION, LATE_START, LEGACY,
                                           MISSING_QUOTE, MTF_DISAGREEMENT,
                                           NEW_LIFE_SAME_PRICE, OBJECTIVE_RANKING,
                                           OBSERVE_ONLY, PROCESS_RESTART,
                                           RAM_ONLY, REAFFIRMED_LIFE, RECOMPUTED,
                                           REPEATED_HTF_EDGE, REPEATED_PRICE,
                                           SESSION_BOUNDARY, TELEMETRY_ONLY,
                                           WARMUP_HISTORY, validate)

T_PS = "tests/test_protected_swing_causal_time.py"
T_CI = "tests/test_causal_occurrence_identity.py"
T_AP = "tests/test_active_path_state.py"
T_KR = "tests/test_session_recovery_kernel.py"
T_EC = "tests/test_epistemic_closure_certification.py"
T_SC = "tests/test_objective_scale_preservation.py"
T_SP = "tests/test_session_po3_authority.py"
T_CS = "tests/test_cross_session_context.py"
T_SS = "tests/test_swing_sequence_truth.py"
T_LS = "tests/test_liquidity_scope_truth.py"


# ══ PROTECTED SWINGS ════════════════════════════════════════════════════════
# CERTIFIED as of PROTECTED-SWING-CAUSAL-TIME-1. Before that unit the semantic
# contract below was FALSE: the producer re-stamped `registered_at` on every
# reaffirmation while every consumer read it as a birth time.
_LIQUIDITY_SCOPE = [
    {
        "fact_id": "liquidity_event.available",
        "producer_owner": "ai_brain.brain_input",
        "representation": "liquidity_events.available",
        "semantic_claim":
            "Whether ANY production-authoritative sweep exists on this scan.  "
            "False means ABSENT -- no lawful occurrence at all -- which is a  "
            "DIFFERENT claim from a proven event whose scope is UNKNOWN. The  "
            "four states never collapse: internal/external classify, UNKNOWN  "
            "means the scope authority was unavailable, ABSENT means there  "
            "was no event to scope. ",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {
            "formation": "minted with the occurrence, from a sweep production "
                         "evidence law actually proved",
            "mutation": "NONE",
            "invalidation": "n/a -- a historical event does not un-happen",
        },
        "temporal": {"formation_time": "the sweep event instant",
                     "observation_time": "the scan that minted it"},
        "restart": "reconstructed from the durable occurrence",
        "late_start": "absent when the event was not witnessed; never inferred",
        "limitations": ("Says nothing about liquidity that was taken but not proven  "
            "under production evidence law ",),
        "certification_tests": (
            f"{T_LS}::TestScopeRequiresAProvenOccurrence",
        ),
        "semantic_predicates": ("liquidity.scope_requires_a_proven_occurrence", ),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
        "consumers": [{"name": "ai_brain.brain_prompt",
                       "believes": "what liquidity event actually occurred",
                       "influence": BRAIN_NARRATIVE}],
    },
    {
        "fact_id": "liquidity_event.event_time",
        "producer_owner": "market_data.sweep_occurrence",
        "representation": "liquidity_events.events[].event_time",
        "semantic_claim":
            "The instant the sweep occurred, as reported by the settled candle  "
            "that pierced the level and closed back through it. Part of the  "
            "occurrence identity, and the field that makes the component join  "
            "exact rather than inferred. ",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {
            "formation": "minted with the occurrence, from a sweep production "
                         "evidence law actually proved",
            "mutation": "NONE",
            "invalidation": "n/a -- a historical event does not un-happen",
        },
        "temporal": {"formation_time": "the sweep event instant",
                     "observation_time": "the scan that minted it"},
        "restart": "reconstructed from the durable occurrence",
        "late_start": "absent when the event was not witnessed; never inferred",
        "limitations": ("An event instant, not a decision instant ",),
        "certification_tests": (
            f"{T_LS}::TestEventTimeImmutability",
        ),
        "semantic_predicates": ("liquidity.scope_is_event_time_immutable", ),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
        "consumers": [{"name": "ai_brain.brain_prompt",
                       "believes": "what liquidity event actually occurred",
                       "influence": BRAIN_NARRATIVE}],
    },
    {
        "fact_id": "liquidity_event.side",
        "producer_owner": "market_data.sweep_occurrence",
        "representation": "liquidity_events.events[].liquidity_side_taken",
        "semantic_claim":
            "WHICH liquidity was taken: buy_side or sell_side. SIDE IS NOT  "
            "SCOPE AND NEITHER IS DIRECTION. A sell-side sweep is a sell-side  "
            "sweep; it is not bullish, and pairing it with `external` does not  "
            "make it a trade. ",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {
            "formation": "minted with the occurrence, from a sweep production "
                         "evidence law actually proved",
            "mutation": "NONE",
            "invalidation": "n/a -- a historical event does not un-happen",
        },
        "temporal": {"formation_time": "the sweep event instant",
                     "observation_time": "the scan that minted it"},
        "restart": "reconstructed from the durable occurrence",
        "late_start": "absent when the event was not witnessed; never inferred",
        "limitations": ("Names the pool taken, nothing about what follows ",),
        "certification_tests": (
            f"{T_LS}::TestScopeIsNotDirection",
        ),
        "semantic_predicates": ("liquidity.scope_is_not_direction", ),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
        "consumers": [{"name": "ai_brain.brain_prompt",
                       "believes": "what liquidity event actually occurred",
                       "influence": BRAIN_NARRATIVE}],
    },
    {
        "fact_id": "liquidity_event.swept_level",
        "producer_owner": "market_data.sweep_occurrence",
        "representation": "liquidity_events.events[].swept_level",
        "semantic_claim":
            "The price of the level that was pierced and reclaimed. Published  "
            "so a scope claim can be checked against the boundaries that  "
            "judged it, rather than taken on trust. ",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {
            "formation": "minted with the occurrence, from a sweep production "
                         "evidence law actually proved",
            "mutation": "NONE",
            "invalidation": "n/a -- a historical event does not un-happen",
        },
        "temporal": {"formation_time": "the sweep event instant",
                     "observation_time": "the scan that minted it"},
        "restart": "reconstructed from the durable occurrence",
        "late_start": "absent when the event was not witnessed; never inferred",
        "limitations": ("A historical level. Not a live objective and not a stop ",),
        "certification_tests": (
            f"{T_LS}::TestEventTimeImmutability",
        ),
        "semantic_predicates": ("liquidity.scope_is_event_time_immutable", ),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
        "consumers": [{"name": "ai_brain.brain_prompt",
                       "believes": "what liquidity event actually occurred",
                       "influence": BRAIN_NARRATIVE}],
    },
    {
        "fact_id": "liquidity_event.reclaimed",
        "producer_owner": "market_data.sweep_occurrence",
        "representation": "liquidity_events.events[].reclaimed",
        "semantic_claim":
            "Whether the SAME settled candle closed back through the level it  "
            "pierced. REJECTION IS NOT DIRECTION: it says the level held, not  "
            "which way price goes next. ",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {
            "formation": "minted with the occurrence, from a sweep production "
                         "evidence law actually proved",
            "mutation": "NONE",
            "invalidation": "n/a -- a historical event does not un-happen",
        },
        "temporal": {"formation_time": "the sweep event instant",
                     "observation_time": "the scan that minted it"},
        "restart": "reconstructed from the durable occurrence",
        "late_start": "absent when the event was not witnessed; never inferred",
        "limitations": ("One-bar reclaim only; a multi-bar reclaim would need its  "
            "own detector and is not this fact ",),
        "certification_tests": (
            f"{T_LS}::TestScopeIsNotDirection",
        ),
        "semantic_predicates": ("liquidity.scope_is_not_direction", ),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
        "consumers": [{"name": "ai_brain.brain_prompt",
                       "believes": "what liquidity event actually occurred",
                       "influence": BRAIN_NARRATIVE}],
    },
    {
        "fact_id": "liquidity_event.timeframe",
        "producer_owner": "market_data.sweep_occurrence",
        "representation": "liquidity_events.events[].timeframe",
        "semantic_claim":
            "The timeframe whose settled series proved this sweep. Part of the  "
            "occurrence identity: the detector runs PER TIMEFRAME, so a 1m and  "
            "a 3m sweep sharing an instant, side and level are different  "
            "events -- and without this field the causal join would refuse  "
            "both as ambiguous. ",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {
            "formation": "minted with the occurrence, from a sweep production "
                         "evidence law actually proved",
            "mutation": "NONE",
            "invalidation": "n/a -- a historical event does not un-happen",
        },
        "temporal": {"formation_time": "the sweep event instant",
                     "observation_time": "the scan that minted it"},
        "restart": "reconstructed from the durable occurrence",
        "late_start": "absent when the event was not witnessed; never inferred",
        "limitations": ("Names the proving series, not a hierarchy of importance ",),
        "certification_tests": (
            f"{T_LS}::TestDetectorScope",
        ),
        "semantic_predicates": ("liquidity.scope_names_its_authority", ),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
        "consumers": [{"name": "ai_brain.brain_prompt",
                       "believes": "what liquidity event actually occurred",
                       "influence": BRAIN_NARRATIVE}],
    },
    {
        "fact_id": "liquidity_link.occurrence_id",
        "producer_owner": "ai_brain.brain_input",
        "representation": "protected_swings.caused_by",
        "semantic_claim":
            "WHICH liquidity occurrence caused a protected swing, as a  "
            "REFERENCE AND NOT A COPY. The occurrence remains the single owner  "
            "of side, scope, rejection and event-time provenance, so the swing  "
            "record cannot drift out of agreement with the event that created  "
            "it. Linkage certainty is PROVEN/UNPROVEN, which is about IDENTITY  "
            "and is not the internal/external/unknown scope vocabulary. An  "
            "unprovable link is OMITTED rather than published as a doubtful  "
            "one. The certified join is event_time + side + swept_level +  "
            "timeframe -- the strongest identity common to both the component  "
            "and the occurrence. Member-level provenance is NOT common to both  "
            "representations (1m publishes no member list) and is therefore  "
            "not part of the join; if stronger common provenance is introduced  "
            "later, this contract must be reconsidered. ",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {
            "formation": "minted with the occurrence, from a sweep production "
                         "evidence law actually proved",
            "mutation": "NONE",
            "invalidation": "n/a -- a historical event does not un-happen",
        },
        "temporal": {"formation_time": "the sweep event instant",
                     "observation_time": "the scan that minted it"},
        "restart": "reconstructed from the durable occurrence",
        "late_start": "absent when the event was not witnessed; never inferred",
        "limitations": ("Present only when EXACTLY ONE occurrence satisfies the  "
            "complete exact key; zero or several both yield no link ",),
        "certification_tests": (
            f"{T_LS}::TestScopeRequiresAProvenOccurrence",
        ),
        "semantic_predicates": ("liquidity.scope_requires_a_proven_occurrence", ),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
        "consumers": [{"name": "ai_brain.brain_prompt",
                       "believes": "what liquidity event actually occurred",
                       "influence": BRAIN_NARRATIVE}],
    },
    {
        "fact_id": "liquidity_scope.detector_scope",
        "producer_owner": "market_data.liquidity_scope",
        "representation": "liquidity_events.events[].detector_scope",
        "semantic_claim":
            "Where the swept level sat relative to the MANIPULATION PIVOT CONTEXT "
            "at the instant of the sweep: `internal`, `external`, or `unknown`. "
            "A buy-side sweep is judged against the outermost swing HIGH and a "
            "sell-side sweep against the outermost LOW. "
            "FOUR STATES THAT ARE NOT INTERCHANGEABLE: internal and external "
            "are classifications; `unknown` means a PROVEN occurrence whose "
            "scope authority was unavailable; and ABSENCE of the whole event "
            "means no production-authoritative sweep existed at all. "
            "IT IS NOT A DIRECTION. external + sell_side + reclaimed are three "
            "facts, not a signal.",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {
            "formation": "stamped once, when the sweep occurrence is minted",
            "mutation": "NONE. Later scans mint NEW occurrences; they never "
                        "restate an existing one",
            "invalidation": "n/a -- a historical event does not stop having "
                            "happened",
        },
        "temporal": {"formation_time": "the sweep event instant",
                     "observation_time": "the scan that minted the occurrence"},
        "restart": "reconstructed from the durable occurrence, which carries "
                   "its own event-time reference; never recomputed against a "
                   "later context",
        "late_start": "a process that did not witness the event has no "
                      "occurrence for it, and therefore no scope -- absent, "
                      "never guessed",
        "limitations": (
            "Says nothing about magnitude, intent or what follows. A rolling pivot "
            "context has no identity across scans, so this claim is meaningful "
            "only together with its event-time reference.",
        ),
        "certification_tests": (
            f"{T_LS}::TestDetectorScope",
            f"{T_LS}::TestEventTimeImmutability",
        ),
        "semantic_predicates": ("liquidity.scope_is_event_time_immutable", "liquidity.scope_is_not_direction", ),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
        "consumers": [
            {"name": "ai_brain.brain_prompt",
             "believes": "what liquidity was taken, and relative to which named "
                         "authority, at the moment it happened",
             "influence": BRAIN_NARRATIVE},
        ],
    },
    {
        "fact_id": "liquidity_scope.detector_reference",
        "producer_owner": "market_data.liquidity_scope",
        "representation": "liquidity_events.events[].detector_scope_relative_to",
        "semantic_claim":
            "WHICH AUTHORITY the detector scope was judged against, as a constant: "
            "`MANIPULATION_PIVOT_CONTEXT`. Published because \"external\" is "
            "meaningless without \"external to what\", and this unit exists "
            "because the organism published the word and withheld the "
            "reference. The boundaries themselves travel as "
            "detector_outer_high / detector_outer_low.",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {
            "formation": "stamped once, when the sweep occurrence is minted",
            "mutation": "NONE. Later scans mint NEW occurrences; they never "
                        "restate an existing one",
            "invalidation": "n/a -- a historical event does not stop having "
                            "happened",
        },
        "temporal": {"formation_time": "the sweep event instant",
                     "observation_time": "the scan that minted the occurrence"},
        "restart": "reconstructed from the durable occurrence, which carries "
                   "its own event-time reference; never recomputed against a "
                   "later context",
        "late_start": "a process that did not witness the event has no "
                      "occurrence for it, and therefore no scope -- absent, "
                      "never guessed",
        "limitations": (
            "Names the authority, not its quality. A pivot context is a rolling "
            "window, not a structural range.",
        ),
        "certification_tests": (
            f"{T_LS}::TestEventTimeImmutability",
        ),
        "semantic_predicates": ("liquidity.scope_names_its_authority", ),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
        "consumers": [
            {"name": "ai_brain.brain_prompt",
             "believes": "what liquidity was taken, and relative to which named "
                         "authority, at the moment it happened",
             "influence": BRAIN_NARRATIVE},
        ],
    },
    {
        "fact_id": "liquidity_scope.detector_boundaries",
        "producer_owner": "market_data.liquidity_scope",
        "representation": "liquidity_events.events[].detector_outer_high",
        "semantic_claim":
            "The outermost swing HIGH of the pivot context as it stood at the "
            "event, published with detector_outer_low so the scope claim is "
            "falsifiable rather than asserted. Null when no pivot high was "
            "available, in which case a buy-side scope reads `unknown`.",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {
            "formation": "stamped once, when the sweep occurrence is minted",
            "mutation": "NONE. Later scans mint NEW occurrences; they never "
                        "restate an existing one",
            "invalidation": "n/a -- a historical event does not stop having "
                            "happened",
        },
        "temporal": {"formation_time": "the sweep event instant",
                     "observation_time": "the scan that minted the occurrence"},
        "restart": "reconstructed from the durable occurrence, which carries "
                   "its own event-time reference; never recomputed against a "
                   "later context",
        "late_start": "a process that did not witness the event has no "
                      "occurrence for it, and therefore no scope -- absent, "
                      "never guessed",
        "limitations": (
            "A boundary at event time only. It does not describe the market now.",
        ),
        "certification_tests": (
            f"{T_LS}::TestEventTimeImmutability",
        ),
        "semantic_predicates": ("liquidity.scope_is_event_time_immutable", ),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
        "consumers": [
            {"name": "ai_brain.brain_prompt",
             "believes": "what liquidity was taken, and relative to which named "
                         "authority, at the moment it happened",
             "influence": BRAIN_NARRATIVE},
        ],
    },
    {
        "fact_id": "liquidity_scope.detector_boundary_low",
        "producer_owner": "market_data.liquidity_scope",
        "representation": "liquidity_events.events[].detector_outer_low",
        "semantic_claim":
            "The low-side counterpart of detector_outer_high.",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {
            "formation": "stamped once, when the sweep occurrence is minted",
            "mutation": "NONE. Later scans mint NEW occurrences; they never "
                        "restate an existing one",
            "invalidation": "n/a -- a historical event does not stop having "
                            "happened",
        },
        "temporal": {"formation_time": "the sweep event instant",
                     "observation_time": "the scan that minted the occurrence"},
        "restart": "reconstructed from the durable occurrence, which carries "
                   "its own event-time reference; never recomputed against a "
                   "later context",
        "late_start": "a process that did not witness the event has no "
                      "occurrence for it, and therefore no scope -- absent, "
                      "never guessed",
        "limitations": (
            "A boundary at event time only.",
        ),
        "certification_tests": (
            f"{T_LS}::TestEventTimeImmutability",
        ),
        "semantic_predicates": ("liquidity.scope_is_event_time_immutable", ),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
        "consumers": [
            {"name": "ai_brain.brain_prompt",
             "believes": "what liquidity was taken, and relative to which named "
                         "authority, at the moment it happened",
             "influence": BRAIN_NARRATIVE},
        ],
    },
    {
        "fact_id": "liquidity_scope.po3_scope",
        "producer_owner": "market_data.liquidity_scope",
        "representation": "liquidity_events.events[].po3_scope",
        "semantic_claim":
            "Where the swept level sat relative to the SESSION PO3 ACCUMULATION "
            "RANGE that was ESTABLISHED BEFORE the event: `internal`, "
            "`external`, or `unknown`. "
            "`unknown` is the honest answer when no established range existed "
            "yet, and a range that forms LATER never relabels an earlier "
            "event. Measured 2026-09-01: the 09:39 sweep is `unknown` because "
            "the accumulation range was born at 13:45Z, six minutes after. "
            "IT MAY DISAGREE WITH detector_scope, legitimately: a level can "
            "sit inside a wide pivot context and outside a tighter "
            "established range. Both are published; neither overrides.",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {
            "formation": "stamped once, when the sweep occurrence is minted",
            "mutation": "NONE. Later scans mint NEW occurrences; they never "
                        "restate an existing one",
            "invalidation": "n/a -- a historical event does not stop having "
                            "happened",
        },
        "temporal": {"formation_time": "the sweep event instant",
                     "observation_time": "the scan that minted the occurrence"},
        "restart": "reconstructed from the durable occurrence, which carries "
                   "its own event-time reference; never recomputed against a "
                   "later context",
        "late_start": "a process that did not witness the event has no "
                      "occurrence for it, and therefore no scope -- absent, "
                      "never guessed",
        "limitations": (
            "Requires an ESTABLISHED range. A forming range has not earned the "
            "authority to say what is outside it, so it yields `unknown` "
            "rather than a provisional classification.",
        ),
        "certification_tests": (
            f"{T_LS}::TestPo3Scope",
            f"{T_LS}::TestTodayIsRepresentationOnly",
        ),
        "semantic_predicates": ("liquidity.po3_scope_needs_a_prior_range", "liquidity.scope_is_not_direction", ),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
        "consumers": [
            {"name": "ai_brain.brain_prompt",
             "believes": "what liquidity was taken, and relative to which named "
                         "authority, at the moment it happened",
             "influence": BRAIN_NARRATIVE},
        ],
    },
    {
        "fact_id": "liquidity_scope.po3_reference",
        "producer_owner": "market_data.liquidity_scope",
        "representation": "liquidity_events.events[].po3_scope_relative_to",
        "semantic_claim":
            "WHICH AUTHORITY the session scope was judged against, as a constant: "
            "`SESSION_PO3_ACCUMULATION_RANGE`. Null when no established range "
            "existed.",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {
            "formation": "stamped once, when the sweep occurrence is minted",
            "mutation": "NONE. Later scans mint NEW occurrences; they never "
                        "restate an existing one",
            "invalidation": "n/a -- a historical event does not stop having "
                            "happened",
        },
        "temporal": {"formation_time": "the sweep event instant",
                     "observation_time": "the scan that minted the occurrence"},
        "restart": "reconstructed from the durable occurrence, which carries "
                   "its own event-time reference; never recomputed against a "
                   "later context",
        "late_start": "a process that did not witness the event has no "
                      "occurrence for it, and therefore no scope -- absent, "
                      "never guessed",
        "limitations": (
            "Names the authority, not its quality.",
        ),
        "certification_tests": (
            f"{T_LS}::TestPo3Scope",
        ),
        "semantic_predicates": ("liquidity.scope_names_its_authority", ),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
        "consumers": [
            {"name": "ai_brain.brain_prompt",
             "believes": "what liquidity was taken, and relative to which named "
                         "authority, at the moment it happened",
             "influence": BRAIN_NARRATIVE},
        ],
    },
    {
        "fact_id": "liquidity_scope.po3_range_id",
        "producer_owner": "market_data.liquidity_scope",
        "representation": "liquidity_events.events[].po3_range_id",
        "semantic_claim":
            "Stable identity of the CAUSAL accumulation range, unchanged across "
            "legitimate boundary extensions. Derived from session and birth, "
            "which do not move when the range extends. Lets the Brain tell "
            "\"the same range, later extended\" from \"a different range\". "
            "The exact-version snapshot identifiers are deliberately NOT "
            "published: they are opaque audit ids, and every fact they "
            "certify already travels as structured boundaries above. They "
            "remain on the immutable occurrence for forensic verification.",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {
            "formation": "stamped once, when the sweep occurrence is minted",
            "mutation": "NONE. Later scans mint NEW occurrences; they never "
                        "restate an existing one",
            "invalidation": "n/a -- a historical event does not stop having "
                            "happened",
        },
        "temporal": {"formation_time": "the sweep event instant",
                     "observation_time": "the scan that minted the occurrence"},
        "restart": "reconstructed from the durable occurrence, which carries "
                   "its own event-time reference; never recomputed against a "
                   "later context",
        "late_start": "a process that did not witness the event has no "
                      "occurrence for it, and therefore no scope -- absent, "
                      "never guessed",
        "limitations": (
            "Comparable for identity only; it carries no boundaries of its own.",
        ),
        "certification_tests": (
            f"{T_LS}::TestRangeIdentityVersusSnapshot",
        ),
        "semantic_predicates": ("liquidity.range_id_survives_extension", ),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
        "consumers": [
            {"name": "ai_brain.brain_prompt",
             "believes": "what liquidity was taken, and relative to which named "
                         "authority, at the moment it happened",
             "influence": BRAIN_NARRATIVE},
        ],
    },
    {
        "fact_id": "liquidity_scope.po3_boundaries",
        "producer_owner": "market_data.liquidity_scope",
        "representation": "liquidity_events.events[].po3_range_high",
        "semantic_claim":
            "The accumulation-range HIGH as it stood at the event, published with "
            "po3_range_low so the session scope claim is falsifiable.",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {
            "formation": "stamped once, when the sweep occurrence is minted",
            "mutation": "NONE. Later scans mint NEW occurrences; they never "
                        "restate an existing one",
            "invalidation": "n/a -- a historical event does not stop having "
                            "happened",
        },
        "temporal": {"formation_time": "the sweep event instant",
                     "observation_time": "the scan that minted the occurrence"},
        "restart": "reconstructed from the durable occurrence, which carries "
                   "its own event-time reference; never recomputed against a "
                   "later context",
        "late_start": "a process that did not witness the event has no "
                      "occurrence for it, and therefore no scope -- absent, "
                      "never guessed",
        "limitations": (
            "Event-time boundaries. The range may have extended since.",
        ),
        "certification_tests": (
            f"{T_LS}::TestRangeIdentityVersusSnapshot",
        ),
        "semantic_predicates": ("liquidity.range_id_survives_extension", ),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
        "consumers": [
            {"name": "ai_brain.brain_prompt",
             "believes": "what liquidity was taken, and relative to which named "
                         "authority, at the moment it happened",
             "influence": BRAIN_NARRATIVE},
        ],
    },
    {
        "fact_id": "liquidity_scope.po3_boundary_low",
        "producer_owner": "market_data.liquidity_scope",
        "representation": "liquidity_events.events[].po3_range_low",
        "semantic_claim":
            "The low-side counterpart of po3_range_high.",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {
            "formation": "stamped once, when the sweep occurrence is minted",
            "mutation": "NONE. Later scans mint NEW occurrences; they never "
                        "restate an existing one",
            "invalidation": "n/a -- a historical event does not stop having "
                            "happened",
        },
        "temporal": {"formation_time": "the sweep event instant",
                     "observation_time": "the scan that minted the occurrence"},
        "restart": "reconstructed from the durable occurrence, which carries "
                   "its own event-time reference; never recomputed against a "
                   "later context",
        "late_start": "a process that did not witness the event has no "
                      "occurrence for it, and therefore no scope -- absent, "
                      "never guessed",
        "limitations": (
            "Event-time boundaries.",
        ),
        "certification_tests": (
            f"{T_LS}::TestRangeIdentityVersusSnapshot",
        ),
        "semantic_predicates": ("liquidity.range_id_survives_extension", ),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
        "consumers": [
            {"name": "ai_brain.brain_prompt",
             "believes": "what liquidity was taken, and relative to which named "
                         "authority, at the moment it happened",
             "influence": BRAIN_NARRATIVE},
        ],
    },
    {
        "fact_id": "liquidity_scope.scope_reason",
        "producer_owner": "market_data.liquidity_scope",
        "representation": "liquidity_events.events[].scope_reason",
        "semantic_claim":
            "WHY a proven occurrence has an unresolved scope, e.g. \"no "
            "established session accumulation range at event time; po3 scope "
            "is unavailable, not internal\". Explanatory, and deliberately "
            "distinct from the structured states: it exists so `unknown` says "
            "what was missing instead of being opaque.",
        "authority_class": ADVISORY,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {
            "formation": "stamped once, when the sweep occurrence is minted",
            "mutation": "NONE. Later scans mint NEW occurrences; they never "
                        "restate an existing one",
            "invalidation": "n/a -- a historical event does not stop having "
                            "happened",
        },
        "temporal": {"formation_time": "the sweep event instant",
                     "observation_time": "the scan that minted the occurrence"},
        "restart": "reconstructed from the durable occurrence, which carries "
                   "its own event-time reference; never recomputed against a "
                   "later context",
        "late_start": "a process that did not witness the event has no "
                      "occurrence for it, and therefore no scope -- absent, "
                      "never guessed",
        "limitations": (
            "Prose. It explains a structured state and must never be parsed as one.",
        ),
        "certification_tests": (
            f"{T_LS}::TestPo3Scope",
        ),
        "semantic_predicates": ("liquidity.prose_asserts_nothing", ),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
        "consumers": [
            {"name": "ai_brain.brain_prompt",
             "believes": "what liquidity was taken, and relative to which named "
                         "authority, at the moment it happened",
             "influence": BRAIN_NARRATIVE},
        ],
    },
]

_PROTECTED_SWINGS = [
    # ── ORDINAL SUCCESSION ──────────────────────────────────────────────────
    # LUNA-SWING-SEQUENCE-TRUTH-1 (2026-09-01). Contracted because the facts
    # below are NEW Brain-visible paths, and an uncontracted payload path fails
    # this gate closed -- correctly. Measured live 2026-09-01: the registry
    # walked highs 29157.75 -> 29163.25 -> 29173 -> 29179 and lows
    # 29040 -> 29085 -> 29116 -> 29135.75 while the Brain was told
    # `swing_sequence: unknown` and read each swing as an isolated rejection.
    {
        "fact_id": "protected_swing.lineage_step",
        "producer_owner": "narrative_authority.protected_swings.ProtectedSwingTracker",
        "representation": "protected_swings.lineage.{side}s.{tf}[i] (tracker state; NOT published to the Brain -- the curated ordinal_sequence carries what it needs)",
        "semantic_claim":
            "One SUCCESSION between two consecutive confirmed protected-swing "
            "lives on one timeframe and side: the price and formation time of "
            "the life that ended, the price and formation time of the life that "
            "replaced it, and the ordinal relationship between them "
            "(higher_high / lower_high / equal_high, or the low equivalents). "
            "It is a fact about a RELATIONSHIP, not about either endpoint, "
            "which is why it does not live on the swing record. The list is "
            "CHRONOLOGICAL, oldest first, and bounded to the most recent 32 "
            "lives per slot. `ordinal` is null for the first life on a slot, "
            "because a first swing succeeds nothing.",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {
            "formation": "appended when a genuinely DIFFERENT level takes an "
                         "occupied slot (succession), or on the first "
                         "registration into an empty slot",
            "mutation": "NONE. Re-affirmation of a live level appends nothing "
                        "and alters nothing -- reaffirmation changes nothing, "
                        "succession creates lineage",
            "invalidation": "entries age out only via the 32-life bound; a "
                            "violation ends a LIFE, not its succession record",
        },
        "temporal": {"formation_time": "current_registered_at",
                     "observation_time": "the scan timestamp, carried on the "
                                         "occurrence, never here"},
        "restart": "RAM-only. A fresh process rebuilds lineage as new "
                   "successions are confirmed; it does not back-fill history it "
                   "did not witness, and reports INSUFFICIENT until two "
                   "confirmed lives exist on a side",
        "late_start": "a late process has a SHORTER lineage, never a wrong one; "
                      "the canonical sequence degrades to INSUFFICIENT rather "
                      "than inventing a relationship",
        "consumers": [
            {"name": "narrative_authority.swing_structure",
             "believes": "the ordered confirmed swings from which the canonical "
                         "ordinal sequence is derived",
             "influence": BRAIN_NARRATIVE},
            {"name": "ai_brain.brain_input",
             "believes": "what confirmed structure actually did, published "
                         "beside the causal `basis` rather than instead of it",
             "influence": BRAIN_NARRATIVE},
        ],
        "limitations": (
            "Says nothing about WHY structure advanced, only that it did. A succession is not displacement, not delivery and not permission.",
        ),
        "certification_tests": (
            f"{T_SS}::TestBothDimensionsSurvive",
        ),
        "semantic_predicates": ("swing.ordinals_are_derived",),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
    },
    {
        "fact_id": "protected_swing.ordered_confirmed_levels",
        "producer_owner": "narrative_authority.swing_structure.canonical_sequence",
        "representation": "protected_swings.ordinal_sequence.highs",
        "semantic_claim":
            "The confirmed swing-high prices the sequence was derived from, "
            "CHRONOLOGICAL, oldest first, read from one timeframe's lineage. "
            "Published with `lows` so the Brain can see the actual ladder "
            "rather than only its summary verdict. Prices, not levels to trade.",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {"formation": "read from the lineage each scan",
                      "mutation": "extends on succession; bounded at 32",
                      "invalidation": "empty when no lineage exists"},
        "temporal": {"formation_time": "derived", "observation_time": "the scan"},
        "restart": "RAM-only; a fresh process sees only witnessed successions",
        "late_start": "a shorter ladder, never a wrong one",
        "consumers": [{"name": "ai_brain.brain_prompt",
                       "believes": "the ordered confirmed highs behind the "
                                   "sequence", "influence": BRAIN_NARRATIVE}],
        "limitations": (
            "Historical confirmed prices, not live levels and not objectives.",
        ),
        "certification_tests": (
            f"{T_SS}::TestBrainPublication",
        ),
        "semantic_predicates": ("swing.ordinals_are_derived",),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
    },
    {
        "fact_id": "protected_swing.ordered_confirmed_lows",
        "producer_owner": "narrative_authority.swing_structure.canonical_sequence",
        "representation": "protected_swings.ordinal_sequence.lows",
        "semantic_claim":
            "The low-side counterpart of `highs`: confirmed swing-low prices, "
            "chronological, oldest first.",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {"formation": "read from the lineage each scan",
                      "mutation": "extends on succession; bounded at 32",
                      "invalidation": "empty when no lineage exists"},
        "temporal": {"formation_time": "derived", "observation_time": "the scan"},
        "restart": "RAM-only; a fresh process sees only witnessed successions",
        "late_start": "a shorter ladder, never a wrong one",
        "consumers": [{"name": "ai_brain.brain_prompt",
                       "believes": "the ordered confirmed lows behind the "
                                   "sequence", "influence": BRAIN_NARRATIVE}],
        "limitations": (
            "Historical confirmed prices, not live levels and not objectives.",
        ),
        "certification_tests": (
            f"{T_SS}::TestBrainPublication",
        ),
        "semantic_predicates": ("swing.ordinals_are_derived",),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
    },
    {
        "fact_id": "protected_swing.high_ordinals",
        "producer_owner": "narrative_authority.swing_structure.canonical_sequence",
        "representation": "protected_swings.ordinal_sequence.high_ordinals",
        "semantic_claim":
            "The ordinal relationship BETWEEN each consecutive pair of confirmed "
            "highs: `higher_high`, `lower_high` or `equal_high`. There is one "
            "fewer entry than there are highs, because a relationship needs two "
            "endpoints. Derived from the prices each scan rather than trusted "
            "from a stored field, so any assembly route yields the same answer.",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {"formation": "derived from the ordered highs",
                      "mutation": "extends with the ladder",
                      "invalidation": "empty when fewer than two highs exist"},
        "temporal": {"formation_time": "derived", "observation_time": "the scan"},
        "restart": "deterministic for a given ladder",
        "late_start": "fewer relationships, never invented ones",
        "consumers": [{"name": "ai_brain.brain_prompt",
                       "believes": "how each confirmed high related to the one "
                                   "before it", "influence": BRAIN_NARRATIVE}],
        "limitations": (
            "Relationships only; carries no timing, no magnitude and no strength.",
        ),
        "certification_tests": (
            f"{T_SS}::TestCanonicalSequence",
        ),
        "semantic_predicates": ("swing.ordinals_are_derived",),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
    },
    {
        "fact_id": "protected_swing.low_ordinals",
        "producer_owner": "narrative_authority.swing_structure.canonical_sequence",
        "representation": "protected_swings.ordinal_sequence.low_ordinals",
        "semantic_claim":
            "The low-side counterpart of `high_ordinals`: `higher_low`, "
            "`lower_low` or `equal_low` between consecutive confirmed lows.",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {"formation": "derived from the ordered lows",
                      "mutation": "extends with the ladder",
                      "invalidation": "empty when fewer than two lows exist"},
        "temporal": {"formation_time": "derived", "observation_time": "the scan"},
        "restart": "deterministic for a given ladder",
        "late_start": "fewer relationships, never invented ones",
        "consumers": [{"name": "ai_brain.brain_prompt",
                       "believes": "how each confirmed low related to the one "
                                   "before it", "influence": BRAIN_NARRATIVE}],
        "limitations": (
            "Relationships only; carries no timing, no magnitude and no strength.",
        ),
        "certification_tests": (
            f"{T_SS}::TestCanonicalSequence",
        ),
        "semantic_predicates": ("swing.ordinals_are_derived",),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
    },
    {
        "fact_id": "protected_swing.witness_sequence",
        "producer_owner": "regime_classification.regime_features",
        "representation": "protected_swings.ordinal_sequence.windowed_witness.sequence",
        "semantic_claim":
            "The windowed pivot witness's own verdict, in ITS vocabulary: "
            "`higher_highs_higher_lows`, `lower_highs_lower_lows`, "
            "`mixed_bullish_lean`, `mixed_bearish_lean`, `balanced` or "
            "`unknown`. Deliberately NOT translated into the canonical "
            "vocabulary, so the Brain cannot mistake a windowed opinion for the "
            "confirmed registry's answer.",
        "authority_class": ADVISORY,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {"formation": "computed from settled candle pivots",
                      "mutation": "recomputed each scan",
                      "invalidation": "`unknown` when no timeframe was sufficient"},
        "temporal": {"formation_time": "derived", "observation_time": "the scan"},
        "restart": "deterministic for a given settled series",
        "late_start": "may be `unknown` with few settled bars",
        "consumers": [{"name": "ai_brain.brain_prompt",
                       "believes": "a subordinate second opinion on structure",
                       "influence": BRAIN_NARRATIVE}],
        "limitations": (
            "Windowed opinion in its own vocabulary; never authoritative.",
        ),
        "certification_tests": (
            f"{T_SS}::TestSettledEvidenceOwnsTheWindowedWitness",
        ),
        "semantic_predicates": ("swing.witness_is_settled_and_single",),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
    },
    {
        "fact_id": "protected_swing.witness_timeframe",
        "producer_owner": "regime_classification.regime_features",
        "representation": "protected_swings.ordinal_sequence.windowed_witness.source_timeframe",
        "semantic_claim":
            "WHICH single settled timeframe produced the windowed witness "
            "(`15m`, `5m`, `3m`, or null when none was sufficient). Selection "
            "is by mechanical pivot sufficiency only -- never by desired "
            "direction -- and exactly one timeframe is chosen, so the witness "
            "is never a mixed-timeframe pivot set.",
        "authority_class": ADVISORY,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {"formation": "the first candidate with sufficient pivots",
                      "mutation": "may change scan to scan as evidence changes",
                      "invalidation": "null when no candidate was sufficient"},
        "temporal": {"formation_time": "derived", "observation_time": "the scan"},
        "restart": "deterministic for a given settled series",
        "late_start": "may fall to a faster timeframe with less history",
        "consumers": [{"name": "ai_brain.brain_prompt",
                       "believes": "which window the second opinion came from",
                       "influence": BRAIN_NARRATIVE}],
        "limitations": (
            "Names the window, not its reliability.",
        ),
        "certification_tests": (
            f"{T_SS}::TestSettledEvidenceOwnsTheWindowedWitness",
        ),
        "semantic_predicates": ("swing.witness_is_settled_and_single",),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
    },
    {
        "fact_id": "protected_swing.witness_detail",
        "producer_owner": "regime_classification.regime_features",
        "representation": "protected_swings.ordinal_sequence.windowed_witness.detail",
        "semantic_claim":
            "Human-readable explanation of the windowed witness, e.g. "
            "'HH=3 LH=1 HL=2 LL=0 over 60 candles' or "
            "'only 0 swing highs / 0 swing lows in window'. Explanatory only.",
        "authority_class": ADVISORY,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {"formation": "composed with the witness",
                      "mutation": "tracks the witness",
                      "invalidation": "n/a"},
        "temporal": {"formation_time": "derived", "observation_time": "the scan"},
        "restart": "deterministic for a given settled series",
        "late_start": "unaffected",
        "consumers": [{"name": "ai_brain.brain_prompt",
                       "believes": "why the windowed witness says what it says",
                       "influence": BRAIN_NARRATIVE}],
        "limitations": (
            "Prose. Explanatory only.",
        ),
        "certification_tests": (
            f"{T_SS}::TestSettledEvidenceOwnsTheWindowedWitness",
        ),
        "semantic_predicates": ("swing.prose_asserts_nothing",),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
    },
    {
        "fact_id": "protected_swing.witness_fallback_trace",
        "producer_owner": "regime_classification.regime_features",
        "representation": "protected_swings.ordinal_sequence.windowed_witness.fallback_trace",
        "semantic_claim":
            "Every timeframe CONSIDERED for the windowed witness with its pivot "
            "counts, in the order tried, e.g. "
            "['15m: 0 highs / 0 lows', '5m: 4 highs / 3 lows']. Published so "
            "the selection is auditable and so a witness that found nothing "
            "says WHERE it looked -- the defect this unit repaired was a "
            "selection that silently never looked past 15m.",
        "authority_class": ADVISORY,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {"formation": "appended per candidate considered",
                      "mutation": "rebuilt each scan",
                      "invalidation": "empty when no candidate series existed"},
        "temporal": {"formation_time": "derived", "observation_time": "the scan"},
        "restart": "deterministic for a given settled series",
        "late_start": "unaffected",
        "consumers": [{"name": "ai_brain.brain_prompt",
                       "believes": "which windows were examined before the "
                                   "witness was chosen",
                       "influence": BRAIN_NARRATIVE}],
        "limitations": (
            "Records what was examined, not why a timeframe lacked pivots.",
        ),
        "certification_tests": (
            f"{T_SS}::TestSettledEvidenceOwnsTheWindowedWitness",
        ),
        "semantic_predicates": ("swing.witness_is_settled_and_single",),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
    },
    {
        "fact_id": "protected_swing.sequence_provenance",
        "producer_owner": "narrative_authority.swing_structure.canonical_sequence",
        "representation": "protected_swings.ordinal_sequence.authority",
        "semantic_claim":
            "WHICH MECHANISM AUTHORED the ordinal sequence, as a constant "
            "string: `confirmed_swing_registry`. Published so the Brain can "
            "tell canonical structure from the windowed pivot witness beside "
            "it, rather than inferring authority from position in the payload.",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {"formation": "constant for this producer",
                      "mutation": "NONE",
                      "invalidation": "n/a"},
        "temporal": {"formation_time": "derived", "observation_time": "the scan"},
        "restart": "constant across processes",
        "late_start": "unaffected",
        "consumers": [{"name": "ai_brain.brain_prompt",
                       "believes": "which mechanism is authoritative for "
                                   "ordinal structure",
                       "influence": BRAIN_NARRATIVE}],
        "limitations": (
            "Names the author, not the quality of what was authored.",
        ),
        "certification_tests": (
            f"{T_SS}::TestBrainPublication",
        ),
        "semantic_predicates": ("swing.registry_outranks_witness",),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
    },
    {
        "fact_id": "protected_swing.confirmed_swing_counts",
        "producer_owner": "narrative_authority.swing_structure.canonical_sequence",
        "representation": "protected_swings.ordinal_sequence.confirmed_highs",
        "semantic_claim":
            "HOW MUCH CONFIRMED EVIDENCE the sequence rests on: the number of "
            "confirmed swing lives read from the selected slot. Published "
            "beside `confirmed_lows` so the Brain can weigh a sequence drawn "
            "from two swings differently from one drawn from eight, and so "
            "INSUFFICIENT is legible rather than opaque. A count, never a "
            "strength score and never permission.",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {"formation": "counted from the lineage each scan",
                      "mutation": "grows as successions confirm; bounded at 32",
                      "invalidation": "0 when no lineage exists"},
        "temporal": {"formation_time": "derived", "observation_time": "the scan"},
        "restart": "RAM-only; a fresh process counts only what it witnessed",
        "late_start": "a late process reports a smaller count, never a wrong one",
        "consumers": [{"name": "ai_brain.brain_prompt",
                       "believes": "how many confirmed swings support the "
                                   "sequence",
                       "influence": BRAIN_NARRATIVE}],
        "limitations": (
            "A count is not conviction. Eight confirmed swings do not make a sequence tradable.",
        ),
        "certification_tests": (
            f"{T_SS}::TestBrainPublication",
        ),
        "semantic_predicates": ("swing.insufficient_is_not_unknown",),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
    },
    {
        "fact_id": "protected_swing.confirmed_low_count",
        "producer_owner": "narrative_authority.swing_structure.canonical_sequence",
        "representation": "protected_swings.ordinal_sequence.confirmed_lows",
        "semantic_claim":
            "The low-side counterpart of `confirmed_highs`: the number of "
            "confirmed low lives the sequence rests on. Contracted separately "
            "because the two sides can legitimately differ, and a sequence is "
            "INSUFFICIENT when EITHER side is short.",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {"formation": "counted from the lineage each scan",
                      "mutation": "grows as successions confirm; bounded at 32",
                      "invalidation": "0 when no lineage exists"},
        "temporal": {"formation_time": "derived", "observation_time": "the scan"},
        "restart": "RAM-only; a fresh process counts only what it witnessed",
        "late_start": "a late process reports a smaller count, never a wrong one",
        "consumers": [{"name": "ai_brain.brain_prompt",
                       "believes": "how many confirmed lows support the sequence",
                       "influence": BRAIN_NARRATIVE}],
        "limitations": (
            "A count is not conviction; see confirmed_highs.",
        ),
        "certification_tests": (
            f"{T_SS}::TestBrainPublication",
        ),
        "semantic_predicates": ("swing.insufficient_is_not_unknown",),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
    },
    {
        "fact_id": "protected_swing.sequence_detail",
        "producer_owner": "narrative_authority.swing_structure.canonical_sequence",
        "representation": "protected_swings.ordinal_sequence.detail",
        "semantic_claim":
            "A HUMAN-READABLE EXPLANATION of how the sequence was reached, e.g. "
            "'highs rising (1m), lows rising (1m) over 4/4 confirmed swings', or "
            "the reason it is INSUFFICIENT or UNKNOWN. Explanatory only: it "
            "restates facts published structurally elsewhere and introduces no "
            "claim of its own. It exists so an unresolved sequence says WHY.",
        "authority_class": ADVISORY,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {"formation": "composed each scan from the same inputs",
                      "mutation": "tracks the sequence it describes",
                      "invalidation": "n/a"},
        "temporal": {"formation_time": "derived", "observation_time": "the scan"},
        "restart": "deterministic for a given lineage",
        "late_start": "unaffected",
        "consumers": [{"name": "ai_brain.brain_prompt",
                       "believes": "why the sequence is what it is",
                       "influence": BRAIN_NARRATIVE}],
        "limitations": (
            "Prose. It restates structured facts and must never be parsed as one.",
        ),
        "certification_tests": (
            f"{T_SS}::TestCanonicalSequence",
        ),
        "semantic_predicates": ("swing.prose_asserts_nothing",),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
    },
    {
        "fact_id": "protected_swing.ordinal_sequence",
        "producer_owner": "narrative_authority.swing_structure.canonical_sequence",
        "representation": "protected_swings.ordinal_sequence.sequence",
        "semantic_claim":
            "The canonical ordinal state of confirmed structure, derived ONLY "
            "from the confirmed protected-swing registry: BULLISH_SEQUENCE "
            "(highs rising and lows rising), BEARISH_SEQUENCE (both falling), "
            "MIXED (any conflicting arrangement, including higher highs with "
            "lower lows -- reported, never resolved into a lean), INSUFFICIENT "
            "(the registry is readable but holds fewer than two confirmed "
            "swings on a side), or UNKNOWN (no registry was supplied, or it "
            "could not be read). INSUFFICIENT and UNKNOWN are DIFFERENT CLAIMS "
            "and may not collapse: the first means the mechanism is early, the "
            "second means it is unavailable. "
            "IT IS STRUCTURE, NOT PERMISSION. A bullish sequence is not a buy "
            "and authorizes nothing; PO3 phase, delivery, liquidity and "
            "location remain independently authoritative.",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {
            "formation": "recomputed every scan from the current lineage",
            "mutation": "changes only when the lineage it reads changes",
            "invalidation": "an unreadable lineage yields UNKNOWN; it never "
                            "falls back to a previous answer",
        },
        "temporal": {"formation_time": "derived, no independent birth time",
                     "observation_time": "the scan that computed it"},
        "restart": "deterministic for a given lineage: the same confirmed "
                   "levels yield the same sequence in any process",
        "late_start": "reports INSUFFICIENT until enough confirmed lives exist",
        "consumers": [
            {"name": "ai_brain.brain_prompt",
             "believes": "what confirmed highs and lows have done relative to "
                         "one another, as evidence to weigh -- not an instruction",
             "influence": BRAIN_NARRATIVE},
        ],
        "limitations": (
            "A sequence is not a direction to trade. It says what confirmed structure did, not what price will do next, and it is silent on location, PO3 phase and whether any entry is lawful.",
        ),
        "certification_tests": (
            f"{T_SS}::TestCanonicalSequence",
            f"{T_SS}::TestTodayIsRepresentationOnly",
        ),
        "semantic_predicates": ("swing.bullish_means_both_sides_rose",
                                "swing.bearish_means_both_sides_fell",
                                "swing.conflict_is_mixed",
                                "swing.insufficient_is_not_unknown",
                                "swing.structure_is_not_permission",),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
    },
    {
        "fact_id": "protected_swing.windowed_witness",
        "producer_owner": "regime_classification.regime_features",
        "representation": "protected_swings.ordinal_sequence.windowed_witness",
        "semantic_claim":
            "A SECOND, NON-AUTHORITATIVE view of swing structure, computed from "
            "candle pivots on ONE settled timeframe selected by mechanical "
            "pivot sufficiency (15m, else 5m, else 3m). `source_timeframe` "
            "names the timeframe chosen and `fallback_trace` records every "
            "candidate considered with its pivot counts, so the selection is "
            "auditable. It is a REGIME WITNESS: where it disagrees with the "
            "confirmed registry the registry wins, and the disagreement is "
            "published rather than silently resolved.",
        "authority_class": ADVISORY,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {
            "formation": "recomputed every scan from settled candles",
            "mutation": "changes with the settled series",
            "invalidation": "`unknown` when no candidate timeframe produced "
                            "sufficient pivots",
        },
        "temporal": {"formation_time": "derived, no independent birth time",
                     "observation_time": "the scan that computed it"},
        "restart": "deterministic for a given settled series",
        "late_start": "fewer settled bars may yield `unknown`; it never "
                      "substitutes the realtime series to avoid that",
        "consumers": [
            {"name": "ai_brain.brain_prompt",
             "believes": "a windowed second opinion, explicitly subordinate to "
                         "the confirmed registry",
             "influence": BRAIN_NARRATIVE},
        ],
        "limitations": (
            "Subordinate to the confirmed registry and drawn from ONE timeframe; it can be `unknown` while the registry has a clear answer.",
        ),
        "certification_tests": (
            f"{T_SS}::TestSettledEvidenceOwnsTheWindowedWitness",
        ),
        "semantic_predicates": ("swing.witness_is_settled_and_single",),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
    },
    {
        "fact_id": "protected_swing.witness_agreement",
        "producer_owner": "narrative_authority.swing_structure.witness_agreement",
        "representation": "protected_swings.ordinal_sequence.witness_agreement.agreement",
        "semantic_claim":
            "Whether the windowed pivot witness agrees with the canonical "
            "confirmed-registry sequence: `agree`, `disagree`, or "
            "`not_comparable` (either side is UNKNOWN/INSUFFICIENT, or the "
            "windowed value has no canonical counterpart). "
            "IT IS NOT A DIRECTION AND NOT A STATE OF THE MARKET. It is named "
            "`agreement` rather than `state` deliberately: `bias`/`state` keys "
            "inside the structural blocks are the legacy structure engine's "
            "directional verdicts, and carrying them killed 43 scans on "
            "2026-08-11.",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {
            "formation": "recomputed every scan from the two sequences",
            "mutation": "changes with either input",
            "invalidation": "`not_comparable` whenever a comparison would be "
                            "meaningless; it never guesses agreement",
        },
        "temporal": {"formation_time": "derived, no independent birth time",
                     "observation_time": "the scan that computed it"},
        "restart": "deterministic for a given pair of sequences",
        "late_start": "`not_comparable` until both sides are available",
        "consumers": [
            {"name": "ai_brain.brain_prompt",
             "believes": "whether two independent mechanisms see the same "
                         "structure; disagreement is uncertainty to weigh",
             "influence": BRAIN_NARRATIVE},
        ],
        "limitations": (
            "Agreement is not correctness -- two mechanisms can agree and both be early. Disagreement is uncertainty, not a signal.",
        ),
        "certification_tests": (
            f"{T_SS}::TestWitnessIsNotAuthority",
        ),
        "semantic_predicates": ("swing.registry_outranks_witness",
                                "swing.agreement_needs_both_sides",),
        "scenarios": (REAFFIRMED_LIFE, SESSION_BOUNDARY),
    },
    {
        "fact_id": "protected_swing.registered_at",
        "producer_owner": "narrative_authority.protected_swings.ProtectedSwingTracker",
        "representation": "protected_swings.by_timeframe.{side}.{tf}.registered_at",
        "semantic_claim":
            "The IMMUTABLE FORMATION TIME of one continuous protected-swing "
            "life. The instant the raid on this level was first rejected. It "
            "does not move while the life continues, so (now - registered_at) "
            "is the duration the level has survived unviolated.",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RAM_ONLY,
        "lifecycle": {
            "formation": "assigned once, when a sweep+reclaim registers a level "
                         "into an EMPTY timeframe/side slot",
            "mutation": "NONE while the life continues. A further raid rejection "
                        "at the same canonical level is RE-AFFIRMATION and "
                        "preserves the original stamp -- stronger evidence may "
                        "not make a level younger",
            "invalidation": "the life ends when price closes beyond the level by "
                            "the violation buffer, or when a different level "
                            "takes the slot (replacement). A later life at the "
                            "same numeric price gets a NEW stamp",
        },
        "temporal": {"formation_time": "this field",
                     "observation_time": "the scan timestamp, carried separately "
                                         "on the occurrence, never here"},
        "restart": "recomputed from the canonical tape; a fresh process derives "
                   "the same stamp for the same life",
        "late_start": "a process that starts late reconstructs the same stamp via "
                      "the recovery kernel; process uptime does not affect it",
        "consumers": [
            {"name": "ai_brain.brain_prompt",
             "believes": "when the raid was rejected and the level was born; the "
                         "start of its unviolated survival interval",
             "influence": BRAIN_NARRATIVE},
            {"name": "broker.luna_candidate_producer",
             "believes": "formation time of the protected level",
             "influence": TELEMETRY_ONLY},
            {"name": "ai_retrieval.descriptive_memory",
             "believes": "formation time of the protected level",
             "influence": TELEMETRY_ONLY},
            {"name": "ai_retrieval.session_segmentation",
             "believes": "formation time of the protected level",
             "influence": TELEMETRY_ONLY},
        ],
        "limitations": (
            "Says nothing about how many times the level was re-tested or how "
            "strongly it was defended. Survival duration is not strength.",
        ),
        "certification_tests": (
            f"{T_PS}::TestLifecycleStatesAreDistinguished",
            f"{T_PS}::TestSamePriceNewLife",
            f"{T_PS}::TestLunaCanNowJudgeSurvival",
            f"{T_PS}::TestRecoveryEquivalence",
        ),
        "semantic_predicates": ("protected_swing.formation_immutable",),
        "scenarios": (REAFFIRMED_LIFE, NEW_LIFE_SAME_PRICE, REPEATED_PRICE,
                      LATE_START, PROCESS_RESTART),
    },
    {
        "fact_id": "protected_swing.level",
        "producer_owner": "narrative_authority.protected_swings.ProtectedSwingTracker",
        "representation": "protected_swings.by_timeframe.{side}.{tf}.level",
        "semantic_claim":
            "The price of a swing high/low that was raided and rejected, and is "
            "defended until price closes beyond it. Canonically rounded to 4dp.",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE, CANDIDATE_GENERATION),
        "persistence": RAM_ONLY,
        "lifecycle": {
            "formation": "sweep_detected AND reclaim_detected on that timeframe",
            "mutation": "replaced only by a DIFFERENT level taking the slot; a "
                        "same-level reaffirmation is a no-op",
            "invalidation": "a close beyond the level by the violation buffer "
                            "removes it from that timeframe only",
        },
        "temporal": {"formation_time": "protected_swing.registered_at"},
        "restart": "recomputed from the canonical tape",
        "late_start": "reconstructed by the recovery kernel",
        "consumers": [
            {"name": "ai_brain.brain_input",
             "believes": "a defended level, per timeframe",
             "influence": BRAIN_NARRATIVE},
            {"name": "broker.luna_candidate_producer",
             "believes": "a candidate invalidation reference",
             "influence": CANDIDATE_GENERATION},
        ],
        "limitations": (
            "Per timeframe and never ranked by distance to price; a 1m level is "
            "execution-local evidence and a 15m level is context.",
        ),
        "certification_tests": (f"{T_PS}::TestFieldSemantics",
                                f"{T_PS}::TestScopeIsHeld"),
        "semantic_predicates": ("protected_swing.level_dies_on_acceptance",),
        "scenarios": (REAFFIRMED_LIFE, MTF_DISAGREEMENT, SESSION_BOUNDARY),
    },
    {
        "fact_id": "protected_swing.swing_id",
        "producer_owner": "narrative_authority.protected_swings.ProtectedSwingTracker",
        "representation": "{tf}:swing_{side}:{level}",
        "semantic_claim":
            "A canonical NAME for a protected level -- timeframe, side and "
            "rounded price. It names a PRICE, not an occurrence.",
        "authority_class": CERTIFIED,
        "decision_influence": (TELEMETRY_ONLY,),
        "persistence": RAM_ONLY,
        "lifecycle": {
            "formation": "derived from tf/side/level at registration",
            "mutation": "never; it is a pure function of its inputs",
            "invalidation": "ends with the record that carries it",
        },
        "temporal": {"formation_time": "none of its own; see registered_at"},
        "restart": "deterministic from the tape",
        "late_start": "deterministic from the tape",
        "consumers": [
            {"name": "market_state.active_path",
             "believes": "the name of the level a leg rests on",
             "influence": BRAIN_NARRATIVE},
        ],
        "limitations": (
            "NOT UNIQUE WITHIN A SESSION. A level can be violated and re-form at "
            "the identical price, producing the same swing_id for two different "
            "lives -- proven on the 2026-08-25 tape at 1m:swing_low:29233.5. "
            "Occurrence identity therefore requires (swing_id, registered_at).",
        ),
        "certification_tests": (f"{T_PS}::TestSamePriceNewLife",
                                f"{T_CI}::TestSamePriceReformation"),
        "semantic_predicates": ("protected_swing.id_not_unique_across_lives",),
        "scenarios": (REPEATED_PRICE, NEW_LIFE_SAME_PRICE),
    },
]

# ══ MARKET-EVENT OCCURRENCE IDENTITY ════════════════════════════════════════
_OCCURRENCES = [
    {
        "fact_id": "occurrence.occurrence_id",
        "producer_owner": "market_state.active_path.occurrence_id",
        "representation": "occurrence.occurrence_id",
        "semantic_claim":
            "WHICH PERSISTED WITNESS ROW this is. Identity of an OBSERVATION, "
            "minted from the scan clock. It is not a market-event identity.",
        "authority_class": CERTIFIED,
        "decision_influence": (TELEMETRY_ONLY,),
        "persistence": DURABLE,
        "lifecycle": {
            "formation": "minted per observation from contract/type/tf/scan-time",
            "mutation": "never -- the durable store refuses rewrites of birth facts",
            "invalidation": "never; durable facts are permanent",
        },
        "temporal": {"observation_time": "embedded in the id itself"},
        "restart": "reloaded from the durable ledger",
        "late_start": "a late process sees only what was already written",
        "consumers": [
            {"name": "market_data.occurrence_ledger",
             "believes": "the v1 dedup key", "influence": TELEMETRY_ONLY},
        ],
        "limitations": (
            "Because it embeds the SCAN clock, one market event observed on many "
            "scans mints many ids -- measured 15 ids for one 15m structure break "
            "on 2026-08-25. It may never be read as 'how many times the market "
            "did this'.",
        ),
        "certification_tests": (f"{T_CI}::TestV1IsPreserved",
                                f"{T_CI}::TestCategoryA"),
        "scenarios": (REPEATED_HTF_EDGE, PROCESS_RESTART),
    },
    {
        "fact_id": "occurrence.causal_event_key.category_a",
        "producer_owner": "market_data.causal_identity.causal_event_key",
        "representation": "v2|{event_type}|{contract}|{tf}|{source_bar_time}|{disc}",
        "semantic_claim":
            "WHICH MARKET EVENT this is, for settled-bar-derived events "
            "(LIQUIDITY_SWEEP, STRUCTURE_BREAK). Identity comes from the "
            "canonical bucket that AUTHORED the claim, so the same event "
            "observed on any number of scans is one event.",
        "authority_class": CERTIFIED,
        "decision_influence": (TELEMETRY_ONLY,),
        "persistence": DURABLE,
        "lifecycle": {
            "formation": "derived from the newest settled bucket for that tf",
            "mutation": "never; the authoring bucket does not change",
            "invalidation": "never",
        },
        "temporal": {"event_time": "source_bar_time, the canonical bucket open",
                     "observation_time": "carried separately as observed_at"},
        "restart": "deterministic; identical keys from the same tape",
        "late_start": "deterministic; the bucket identity does not depend on when "
                      "the process looked",
        "consumers": [
            {"name": "market_data.occurrence_ledger",
             "believes": "the v2 dedup key, when explicitly constructed at v2",
             "influence": TELEMETRY_ONLY},
            {"name": "market_state.active_path.ActivePath",
             "believes": "the v2 dedup key, when explicitly constructed at v2",
             "influence": TELEMETRY_ONLY},
        ],
        "limitations": (
            "CAPABILITY ONLY. Production runs v1; no production caller selects "
            "v2. Activation is gated on CAUSAL-IDENTITY-VERSION-GATE-1 and on "
            "resolving the dual sweep-writer authority gap.",
        ),
        "certification_tests": (f"{T_CI}::TestCategoryA",
                                f"{T_CI}::TestLedger",
                                f"{T_CI}::TestProductionDoesNotActivateV2"),
        "semantic_predicates": ("causal.one_edge_one_event",
                                "causal.production_is_v1"),
        "scenarios": (REPEATED_HTF_EDGE, PROCESS_RESTART, LATE_START),
    },
    {
        "fact_id": "occurrence.causal_event_key.category_b",
        "producer_owner": "market_data.causal_identity.causal_event_key",
        "representation": "NOT MINTED -- returns None for the protected-swing family",
        "semantic_claim":
            "WHICH MARKET EVENT this is, for protected-swing transitions. NOT "
            "AVAILABLE. The provenance it needs is now true, but no key is "
            "minted and nothing may dedup by it.",
        "authority_class": BLOCKED,
        "decision_influence": (TELEMETRY_ONLY,),
        "persistence": RECOMPUTED,
        "lifecycle": {
            "formation": "blocked -- no key is produced",
            "mutation": "blocked",
            "invalidation": "blocked",
        },
        "temporal": {"formation_time": "protected_swing.registered_at, once wired"},
        "restart": "n/a while blocked",
        "late_start": "n/a while blocked",
        "consumers": [
            {"name": "market_data.occurrence_ledger",
             "believes": "nothing -- a v2 store REJECTS these outright",
             "influence": TELEMETRY_ONLY},
        ],
        "limitations": (
            "BLOCKED pending CAUSAL-OCCURRENCE-IDENTITY-1B. The tracker defect "
            "that blocked it (registered_at re-stamped on a living swing) was "
            "repaired by PROTECTED-SWING-CAUSAL-TIME-1, so what remains is "
            "wiring, not correctness. Until then a v2 Active Path holds NO "
            "protected-swing evidence and is not equivalent to v1.",
        ),
        "certification_tests": (f"{T_CI}::TestCategoryBIsRefused",),
        "semantic_predicates": ("causal.category_b_refused",),
        "scenarios": (REAFFIRMED_LIFE, NEW_LIFE_SAME_PRICE),
    },
    {
        "fact_id": "occurrence.source_bar_time",
        "producer_owner": "market_data.snapshot_builder.settled_source_provenance",
        "representation": "snapshot.settled_source.{tf}.source_bar_time",
        "semantic_claim":
            "The canonical OPEN of the newest settled bucket on that timeframe "
            "-- the bar that authored this timeframe's confirmed structure and "
            "liquidity. Stable for the whole life of the bucket.",
        "authority_class": CERTIFIED,
        "decision_influence": (TELEMETRY_ONLY,),
        "persistence": RECOMPUTED,
        "lifecycle": {
            "formation": "published each scan from the same settled series the "
                         "detectors were handed",
            "mutation": "advances only when a new bucket settles",
            "invalidation": "n/a; recomputed every scan",
        },
        "temporal": {"event_time": "this field"},
        "restart": "deterministic from the tape",
        "late_start": "deterministic from the tape",
        "consumers": [
            {"name": "market_state.active_path.extract_occurrences",
             "believes": "the authoring bucket of a Category A event",
             "influence": TELEMETRY_ONLY},
        ],
        "limitations": ("Names the bucket, not the instant the bucket became "
                        "knowable -- that is settled_edge_time.",),
        "certification_tests": (f"{T_CI}::TestSettledSourceProvenance",),
        "scenarios": (REPEATED_HTF_EDGE, LATE_START),
    },
    {
        "fact_id": "occurrence.settled_edge_time",
        "producer_owner": "market_data.snapshot_builder.settled_source_provenance",
        "representation": "snapshot.settled_source.{tf}.settled_edge_time",
        "semantic_claim":
            "The terminal constituent that CLOSED the authoring bucket, taken "
            "from source_member_times[-1]. Says when the bucket became knowable.",
        "authority_class": OBSERVE_ONLY,
        "decision_influence": (TELEMETRY_ONLY,),
        "persistence": RECOMPUTED,
        "lifecycle": {
            "formation": "read from the aggregate's member list",
            "mutation": "advances with the authoring bucket",
            "invalidation": "n/a",
        },
        "temporal": {"event_time": "the closing constituent of the source bucket"},
        "restart": "deterministic from the tape",
        "late_start": "deterministic from the tape",
        "consumers": [
            {"name": "market_state.active_path.extract_occurrences",
             "believes": "diagnostic provenance, never identity",
             "influence": TELEMETRY_ONLY},
        ],
        "limitations": (
            "ABSENT ON 1m, honestly. A pass-through minute publishes no member "
            "list, so there is no terminal constituent to name; deriving one by "
            "arithmetic would manufacture provenance. Never used for identity.",
        ),
        "certification_tests": (f"{T_CI}::TestSettledSourceProvenance",),
        "scenarios": (REPEATED_HTF_EDGE,),
    },
    {
        "fact_id": "occurrence.sweep_writer_authority",
        "producer_owner": "UNRESOLVED -- two writers claim this fact",
        "representation": "data/occurrence_ledger/{contract}.json LIQUIDITY_SWEEP rows",
        "semantic_claim":
            "WHO OWNS the truth of a liquidity-sweep occurrence. Currently "
            "AMBIGUOUS: two writers target one store with two id schemes.",
        "authority_class": BLOCKED,
        "decision_influence": (TELEMETRY_ONLY,),
        "persistence": DURABLE,
        "lifecycle": {
            "formation": "two independent producers, no arbitration",
            "mutation": "n/a",
            "invalidation": "n/a",
        },
        "temporal": {"observation_time": "scan time, in both schemes"},
        "restart": "both writers reload the same store",
        "late_start": "unchanged",
        "consumers": [
            {"name": "market_data.occurrence_ledger",
             "believes": "one append-only market-event store",
             "influence": TELEMETRY_ONLY},
        ],
        "limitations": (
            "AUTHORITY GAP. `live_scan.production_scan_cycle._record_sweep_"
            "occurrences` writes LIQUIDITY_SWEEP:{c}:{tf}:{time} via "
            "`market_data.sweep_occurrence`, while `market_state.active_path."
            "extract_occurrences` writes the same family as "
            "LIQUIDITY_SWEEP:{c}:{tf}:{time}:{direction}. Measured in the live "
            "store: 103 rows from the first, 3 from the second. Production v2 "
            "causal identity is BLOCKED until SWEEP-OCCURRENCE-AUTHORITY-1 "
            "unifies them or proves their responsibilities disjoint.",
        ),
        "certification_tests": (f"{T_EC}::TestAuthorityOwnership",),
        "scenarios": (REPEATED_HTF_EDGE, PROCESS_RESTART),
    },
]

# ══ ACTIVE PATH ═════════════════════════════════════════════════════════════
_ACTIVE_PATH = [
    {
        "fact_id": "active_path.owner",
        "producer_owner": "market_state.active_path.ActivePath",
        "representation": "active_path_state.owner",
        "semantic_claim":
            "Which side has ESTABLISHED ownership of the current leg -- a "
            "rejected raid origin PLUS structural progression. Evidence about "
            "the market, never authorisation to trade.",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RECOMPUTED,
        "lifecycle": {
            "formation": "a forming hypothesis is promoted by a same-direction "
                         "structure break",
            "mutation": "strengthens via progression; a flip requires the "
                        "incumbent leg to die first",
            "invalidation": "released when the load-bearing level is violated, or "
                            "at a session/contract boundary",
        },
        "temporal": {"event_time": "derived from the occurrences it ingested"},
        "restart": "rehydrated by replaying durable occurrences for this session",
        "late_start": "a late process replays the ledger; events that predate the "
                      "ledger are not recoverable",
        "consumers": [
            {"name": "ai_brain.brain_input",
             "believes": "which side owns the tape",
             "influence": BRAIN_NARRATIVE},
        ],
        "limitations": (
            "SINGLE SCOPE. It expresses ONE ownership claim, so it cannot say "
            "'bullish locally inside a bearish incumbent' -- see "
            "active_path.multi_scope.",
            "May never forbid a trade; a lawful counter-path entry stays "
            "executable.",
        ),
        "certification_tests": (f"{T_CI}::TestActivePathDedup",),
        "semantic_predicates": ("path.ownership_requires_confirmation",),
        "scenarios": (PROCESS_RESTART, LATE_START, SESSION_BOUNDARY,
                      REPEATED_HTF_EDGE),
    },
    {
        "fact_id": "active_path.multi_scope",
        "producer_owner": "NONE -- the vocabulary does not exist",
        "representation": "ABSENT from the payload",
        "semantic_claim":
            "Simultaneous ownership at two scopes: a broader incumbent leg and a "
            "local counter-path leg inside it. THE ORGANISM CANNOT EXPRESS THIS.",
        "authority_class": BLOCKED,
        "decision_influence": (TELEMETRY_ONLY,),
        "persistence": RECOMPUTED,
        "lifecycle": {
            "formation": "blocked -- no representation exists",
            "mutation": "blocked",
            "invalidation": "blocked",
        },
        "temporal": {"event_time": "n/a while blocked"},
        "restart": "n/a",
        "late_start": "n/a",
        "consumers": [],
        "limitations": (
            "REPRESENTATION GAP, registered so that single-owner state is never "
            "read as containing information it cannot hold. A retracement inside "
            "a bullish path and a genuine bearish reversal are currently the "
            "same shape in this field. Pending MULTI-SCOPE-PATH-CONTEXT-1.",
        ),
        "certification_tests": (f"{T_EC}::TestCapabilityMatrix",),
        "scenarios": (MTF_DISAGREEMENT,),
    },
    {
        "fact_id": "active_path.load_bearing_structure",
        "producer_owner": "market_state.active_path.ActivePath",
        "representation": "active_path_state.load_bearing_structure",
        "semantic_claim":
            "The protected level the current leg CURRENTLY rests on, as its "
            "producer reports it -- not the best level the leg ever held.",
        "authority_class": CERTIFIED,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RECOMPUTED,
        "lifecycle": {
            "formation": "set when a supporting protected swing registers",
            "mutation": "follows the producer even when the move is ADVERSE; "
                        "pinning it to a favourable level asserted intactness "
                        "about a level the producer had stopped holding",
            "invalidation": "violation of this exact level kills the leg",
        },
        "temporal": {"formation_time": "the supporting swing's registered_at",
                     "event_time": "the occurrence that set it"},
        "restart": "rehydrated, then reconciled against the live tracker",
        "late_start": "reconciled; correspondence that cannot be established is "
                      "reported absent rather than assumed",
        "consumers": [
            {"name": "ai_brain.brain_input",
             "believes": "what the leg rests on right now",
             "influence": BRAIN_NARRATIVE},
        ],
        "limitations": ("Names a level, not a probability that it holds.",),
        "certification_tests": (f"{T_CI}::TestActivePathDedup",),
        "semantic_predicates": ("path.load_bearing_is_producer_backed",),
        "scenarios": (PROCESS_RESTART, REAFFIRMED_LIFE, REPEATED_PRICE),
    },
]

# ══ LIQUIDITY ═══════════════════════════════════════════════════════════════
_LIQUIDITY = [
    {
        "fact_id": "liquidity.brain.nearest_buy_side",
        "producer_owner": "ai_brain.brain_input (FLATTENING, not the engine)",
        "representation": "liquidity.nearest_buy_side",
        "semantic_claim":
            "The first non-null buy-side pool found scanning 15m -> 5m -> 3m -> "
            "1m. HIGHEST-TIMEFRAME-FIRST, not mathematically nearest to price.",
        "authority_class": LEGACY,
        "decision_influence": (TELEMETRY_ONLY,),
        "persistence": RECOMPUTED,
        "lifecycle": {
            "formation": "recomputed every scan by flattening the per-tf engine "
                         "values",
            "mutation": "changes whenever the highest-timeframe pool changes",
            "invalidation": "n/a; recomputed",
        },
        "temporal": {"observation_time": "the scan"},
        "restart": "recomputed; no state",
        "late_start": "recomputed; no state",
        "consumers": [
            {"name": "ai_brain.brain_prompt",
             "believes": "an available buy-side pool",
             "influence": BRAIN_NARRATIVE},
        ],
        "limitations": (
            "THE NAME IS MISLEADING AND THAT IS WHY IT IS LEGACY. "
            "`brain_input.py:764` selects with next() over ('15m','5m','3m','1m'), "
            "so a 15m pool 300 points away wins over a 1m pool 5 points away. The "
            "per-timeframe ENGINE field of the same name IS correctly nearest "
            "within its timeframe -- these are two different facts sharing a "
            "name. Scale-aware selection is liquidity.scale_hierarchy.",
        ),
        "certification_tests": (f"{T_EC}::TestLegacyFactsAreNotCertified",),
        "semantic_predicates": ("liquidity.nearest_is_htf_first",),
        "scenarios": (MTF_DISAGREEMENT,),
    },
    {
        "fact_id": "liquidity.brain.nearest_sell_side",
        "producer_owner": "ai_brain.brain_input (FLATTENING, not the engine)",
        "representation": "liquidity.nearest_sell_side",
        "semantic_claim":
            "The first non-null sell-side pool found scanning 15m -> 5m -> 3m -> "
            "1m. HIGHEST-TIMEFRAME-FIRST, not mathematically nearest to price.",
        "authority_class": LEGACY,
        "decision_influence": (TELEMETRY_ONLY,),
        "persistence": RECOMPUTED,
        "lifecycle": {
            "formation": "recomputed every scan by flattening the per-tf values",
            "mutation": "changes whenever the highest-timeframe pool changes",
            "invalidation": "n/a; recomputed",
        },
        "temporal": {"observation_time": "the scan"},
        "restart": "recomputed; no state",
        "late_start": "recomputed; no state",
        "consumers": [
            {"name": "ai_brain.brain_prompt",
             "believes": "an available sell-side pool",
             "influence": BRAIN_NARRATIVE},
        ],
        "limitations": (
            "Same flattening defect as the buy side. This field was also the "
            "source of the 2026-08-20 V13 forensic confusion, where a nearest-"
            "pool value was published as opposing external liquidity.",
        ),
        "certification_tests": (f"{T_EC}::TestLegacyFactsAreNotCertified",),
        "semantic_predicates": ("liquidity.sell_side_is_htf_first",),
        "scenarios": (MTF_DISAGREEMENT,),
    },
    {
        "fact_id": "liquidity.scale_hierarchy",
        "producer_owner": "structure.liquidity_scale",
        "representation": "structure.liquidity_scale.hierarchy()",
        "semantic_claim":
            "One liquidity PRICE with the set of timeframes that witness it, so "
            "a level seen on 3m and 5m is one pool with two witnesses rather "
            "than two pools.",
        "authority_class": ADVISORY,
        "decision_influence": (TELEMETRY_ONLY,),
        "persistence": RECOMPUTED,
        "lifecycle": {
            "formation": "computed from the per-timeframe pools",
            "mutation": "recomputed each scan",
            "invalidation": "n/a",
        },
        "temporal": {"observation_time": "the scan"},
        "restart": "recomputed; no state",
        "late_start": "recomputed; no state",
        "consumers": [],
        "limitations": (
            "CERTIFIED AS REPRESENTATION, NOT AS BRAIN AUTHORITY. It is not "
            "wired into the payload and no consumer reads it yet; "
            "OBJECTIVE-SCALE-PRESERVATION-1A shipped it behaviourally inert. "
            "Promotion to Brain authority is OBJECTIVE-SCALE-PRESERVATION-1B.",
        ),
        "certification_tests": (f"{T_SC}",),
        "scenarios": (MTF_DISAGREEMENT,),
    },
    {
        "fact_id": "liquidity.pool_lifecycle",
        "producer_owner": "NONE -- pools have price but no lifecycle",
        "representation": "ABSENT",
        "semantic_claim":
            "Whether THIS EXACT pool is still untaken, and when it was formed "
            "and consumed. THE ORGANISM CANNOT SAY THIS.",
        "authority_class": BLOCKED,
        "decision_influence": (TELEMETRY_ONLY,),
        "persistence": RECOMPUTED,
        "lifecycle": {
            "formation": "blocked -- pools carry no formation provenance",
            "mutation": "blocked",
            "invalidation": "blocked -- no consumed state exists",
        },
        "temporal": {"formation_time": "n/a while blocked"},
        "restart": "n/a",
        "late_start": "n/a",
        "consumers": [],
        "limitations": (
            "BLOCKED pending LIQUIDITY-POOL-LIFECYCLE-1. Neither 'this pool is "
            "untaken' nor 'this pool is consumed' may be claimed. A pool that "
            "reappears at the same price after being swept is indistinguishable "
            "from one that was never touched.",
        ),
        "certification_tests": (f"{T_EC}::TestCapabilityMatrix",),
        "scenarios": (REPEATED_PRICE, NEW_LIFE_SAME_PRICE),
    },
]

# ══ DEALING RANGE ═══════════════════════════════════════════════════════════
_DEALING_RANGE = [
    {
        "fact_id": "dealing_range.bounds",
        "producer_owner": "structure.market_context._dealing_range",
        "representation": "market.dealing_range.high / .low",
        "semantic_claim":
            "The operative auction range: the last swing high and low of the "
            "highest timeframe that has both.",
        "authority_class": ADVISORY,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RECOMPUTED,
        "lifecycle": {
            "formation": "derived from structure each scan",
            "mutation": "moves with the source timeframe's swings",
            "invalidation": "n/a; recomputed",
        },
        "temporal": {"observation_time": "the scan"},
        "restart": "recomputed; no state",
        "late_start": "recomputed; no state",
        "consumers": [
            {"name": "ai_brain.brain_prompt",
             "believes": "where price sits in the broader auction; location "
                         "context, never direction",
             "influence": BRAIN_NARRATIVE},
        ],
        "limitations": ("Says nothing about whether the range is still the "
                        "operative one -- see dealing_range.containment.",),
        "certification_tests": (f"{T_EC}::TestBrainPayloadCoverage",),
        "semantic_predicates": ("range.bounds_from_one_timeframe",),
        "scenarios": (MTF_DISAGREEMENT,),
    },
    {
        "fact_id": "dealing_range.containment",
        "producer_owner": "structure.market_context._dealing_range",
        "representation": "market.dealing_range.position / .zone",
        "semantic_claim":
            "Where price sits inside the range, and whether that is premium, "
            "discount or equilibrium. UNSOUND WHEN PRICE IS OUTSIDE THE RANGE.",
        "authority_class": BLOCKED,
        "decision_influence": (TELEMETRY_ONLY,),
        "persistence": RECOMPUTED,
        "lifecycle": {
            "formation": "position = (price - low) / (high - low), unclamped",
            "mutation": "recomputed each scan",
            "invalidation": "n/a",
        },
        "temporal": {"observation_time": "the scan"},
        "restart": "recomputed; no state",
        "late_start": "recomputed; no state",
        "consumers": [
            {"name": "ai_brain.brain_prompt",
             "believes": "premium/discount location",
             "influence": BRAIN_NARRATIVE},
        ],
        "limitations": (
            "NO CONTAINMENT CHECK. `market_context._dealing_range` computes "
            "position without clamping, so price above `high` yields position > "
            "1.0 and still reports zone 'premium', and price below `low` yields "
            "a negative position reported as 'discount'. Mean-threshold and "
            "midpoint authority are BLOCKED until ACTIVE-RANGE-CONTAINMENT-1 "
            "establishes whether the range is still operative.",
        ),
        "certification_tests": (f"{T_EC}::TestBlockedFactsStayBlocked",),
        "semantic_predicates": ("range.position_unclamped",),
        "scenarios": (MTF_DISAGREEMENT,),
    },
]

# ══ STARTUP / RECOVERY ══════════════════════════════════════════════════════
_RECOVERY = [
    {
        "fact_id": "recovery.session_state_completeness",
        "producer_owner": "market_state.session_recovery (KERNEL ONLY)",
        "representation": "not wired into production startup",
        "semantic_claim":
            "That the process holds the complete causal state of the current "
            "session regardless of when it launched. NOT TRUE IN PRODUCTION.",
        "authority_class": BLOCKED,
        "decision_influence": (TELEMETRY_ONLY,),
        "persistence": RECOMPUTED,
        "lifecycle": {
            "formation": "the kernel reconstructs from the canonical tape",
            "mutation": "n/a -- the kernel persists nothing",
            "invalidation": "n/a",
        },
        "temporal": {"observation_time": "each replayed snapshot is tagged with "
                                         "whether it is warmup or in-session"},
        "restart": "the kernel is deterministic across restarts",
        "late_start": "THE DEFECT IT ANSWERS: on 2026-08-25 production launched "
                      "at 10:31 ET and six protected-swing transitions that a "
                      "continuously running process would have held never "
                      "existed, because their evidence predated the process",
        "consumers": [],
        "limitations": (
            "BLOCKED as production authority. `session_recovery` is a certified "
            "deterministic KERNEL that persists nothing and that no production "
            "module imports -- a test enforces exactly that. Live startup still "
            "begins cold. Wiring it is STARTUP-RECOVERY-INTEGRATION.",
        ),
        "certification_tests": (f"{T_KR}::TestTheKernelHasNoAuthority",
                                f"{T_KR}::TestStartTimeIsNotAVariable"),
        "semantic_predicates": ("recovery.kernel_unwired",),
        "scenarios": (LATE_START, PROCESS_RESTART, WARMUP_HISTORY),
    },
]


# == SESSION PO3 =============================================================
# LUNA-SESSION-PO3-AUTHORITY-1. The first market fact in this registry that can
# REFUSE a trade outright, so it is also the one that most needed a contract
# before it was allowed to. Per-timeframe PO3 stays what it was -- uncertified
# texture at `delivery.po3_15m` -- and is deliberately NOT promoted here: this
# unit certified the session lifecycle built ON that evidence, not the evidence.
_SESSION_PO3 = [
    {
        "fact_id": "session_po3.phase",
        "producer_owner": "structure.session_po3.derive",
        "representation": "delivery.session_po3.phase",
        "semantic_claim":
            "The session's Power-of-Three phase, derived causally from the "
            "settled 1m tape: the controlling balance, whether price has left "
            "it, and whether that departure has since been PROVEN to be "
            "manipulation or distribution. UNKNOWN means no established balance "
            "exists -- an absence of evidence, never a claim of balance.",
        "authority_class": CERTIFIED,
        "decision_influence": (CANDIDATE_GENERATION, BRAIN_NARRATIVE),
        "persistence": RECOMPUTED,
        "lifecycle": {
            "formation": "a balance seeded by 3 settled 1m bars, corroborated by "
                         "per-TF PO3 accumulation on >=2 of 5m/3m/1m, ESTABLISHED "
                         "at 12 bars",
            "mutation": "a settled close beyond a boundary by the 1m displacement "
                        "floor opens an excursion; re-entry, acceptance or "
                        "neither resolves it",
            "invalidation": "recomputed from the tape every scan; a balance that "
                            "price accepts away from is replaced by the next one",
        },
        "temporal": {"observation_time": "the newest settled 1m bar",
                     "formation_time": "the first bar of the controlling balance"},
        "restart": "RECOMPUTED, not remembered. The phase is a pure function of "
                   "the settled series, so a cold process replaying the same "
                   "tape reaches the same phase; only the transition log is lost.",
        "late_start": "derives from whatever settled history the coherent window "
                      "holds; below 6 bars it reports UNKNOWN rather than guessing",
        "consumers": [
            {"name": "broker.luna_candidate_producer.produce",
             "believes": "a phase whose new_entry_allowed is False forbids "
                         "opening ANY new position, upstream of playbook and tool",
             "influence": CANDIDATE_GENERATION},
            {"name": "execution_gate.evaluate_gate",
             "believes": "the same, as a blocking factor on would_authorize",
             "influence": CANDIDATE_GENERATION},
            {"name": "ai_brain.brain_input",
             "believes": "the session's delivery phase and why it does or does "
                         "not authorize an entry",
             "influence": BRAIN_NARRATIVE},
        ],
        "limitations": (
            "Says nothing about a PRIOR session. Asia, London and NY-premarket "
            "delivery have no producer in this repository, so the phase is "
            "current-session only.",
            "Reads the 1m series only. A balance visible solely on 15m and never "
            "expressed in settled 1m closes is not seen.",
            "Corroboration comes from the per-TF PO3 texture score, which is "
            "itself uncertified.",
        ),
        "certification_tests": (f"{T_SP}::TestAccumulationRange",
                                f"{T_SP}::TestRestartAndReplay",
                                f"{T_SP}::TestEntryAuthorityIsEnforced"),
        "semantic_predicates": ("session_po3.recomputed_not_remembered",),
        "scenarios": (PROCESS_RESTART, LATE_START, WARMUP_HISTORY, SESSION_BOUNDARY),
    },
    {
        "fact_id": "session_po3.new_entry_allowed",
        "producer_owner": "structure.session_po3.entry_permission",
        "representation": "delivery.session_po3.new_entry_allowed",
        "semantic_claim":
            "Whether the session phase authorizes OPENING a new position. It "
            "says nothing about managing, protecting or closing an existing "
            "one, and it is never a directional opinion.",
        "authority_class": CERTIFIED,
        "decision_influence": (CANDIDATE_GENERATION, EXECUTION),
        "persistence": RECOMPUTED,
        "lifecycle": {
            "formation": "a single table keyed by phase; there is exactly one "
                         "place this is decided",
            "mutation": "changes only when the phase changes",
            "invalidation": "n/a; recomputed with the phase",
        },
        "temporal": {"observation_time": "the newest settled 1m bar"},
        "restart": "recomputed with the phase",
        "late_start": "permissive while the phase is UNKNOWN, which is what "
                      "keeps a genuine opening drive legal",
        "consumers": [
            {"name": "broker.luna_candidate_producer.produce",
             "believes": "False means raise NoCandidate('session_phase_blocks_entry') "
                         "before the thesis is read",
             "influence": CANDIDATE_GENERATION},
            {"name": "execution_gate.evaluate_gate",
             "believes": "False means would_authorize is False",
             "influence": EXECUTION},
        ],
        "limitations": ("Absence of the block is permissive: a snapshot built "
                        "without this authority is not converted into a "
                        "stand-down.",),
        "certification_tests": (f"{T_SP}::TestEntryLaw",
                                f"{T_SP}::TestEntryAuthorityIsEnforced"),
        "semantic_predicates": ("session_po3.block_binds_every_consumer",),
        "scenarios": (PROCESS_RESTART, LATE_START),
    },
    {
        "fact_id": "session_po3.range",
        "producer_owner": "structure.session_po3._segment",
        "representation": "delivery.session_po3.range",
        "semantic_claim":
            "The controlling balance: the high and low of every settled 1m bar "
            "the balance ABSORBED, its age in bars, and whether it reached "
            "establishment. A new extreme whose close returns inside WIDENS this "
            "range; it does not end it.",
        "authority_class": CERTIFIED,
        "decision_influence": (CANDIDATE_GENERATION, BRAIN_NARRATIVE),
        "persistence": RECOMPUTED,
        "lifecycle": {
            "formation": "seeded by SEED_BARS settled bars, then extended by "
                         "every bar whose close stays inside",
            "mutation": "widens on an absorbed extreme; re-accumulation widens it "
                        "to contain the excursion peak",
            "invalidation": "ends at the settled close that departs it",
        },
        "temporal": {"formation_time": "range.birth, the first absorbed bar",
                     "observation_time": "range.last_extension"},
        "restart": "recomputed from the settled series",
        "late_start": "bounded by the coherent window; a range older than the "
                      "window is not seen",
        "consumers": [
            {"name": "structure.session_po3.derive",
             "believes": "the boundary a settled close must clear to be an "
                         "excursion",
             "influence": CANDIDATE_GENERATION},
            {"name": "ai_brain.brain_input",
             "believes": "where the session's balance is",
             "influence": BRAIN_NARRATIVE},
        ],
        "limitations": ("Bounded by the coherent history window, so a balance "
                        "that began before it reports a later birth than the "
                        "market's.",),
        "certification_tests": (f"{T_SP}::TestAccumulationRange",
                                f"{T_SP}::TestNewExtremesDoNotResolve"),
        "semantic_predicates": ("session_po3.range_is_absorbed_bars",),
        "scenarios": (WARMUP_HISTORY, LATE_START, REPEATED_PRICE),
    },
    {
        "fact_id": "session_po3.excursion",
        "producer_owner": "structure.session_po3._segment",
        "representation": "delivery.session_po3.excursion",
        "semantic_claim":
            "A departure from an ESTABLISHED balance: which side, how far it "
            "reached, how many consecutive settled closes stayed outside, and "
            "whether price has closed back inside. It asserts only that price "
            "left -- never why, and never that it will hold.",
        "authority_class": CERTIFIED,
        "decision_influence": (CANDIDATE_GENERATION, BRAIN_NARRATIVE),
        "persistence": RECOMPUTED,
        "lifecycle": {
            "formation": "a settled close beyond a boundary by at least the 1m "
                         "displacement floor",
            "mutation": "peak, consecutive_outside and reentered advance with "
                        "each later settled bar",
            "invalidation": "dies when a new balance establishes",
        },
        "temporal": {"formation_time": "excursion.birth, the departing bar",
                     "observation_time": "the newest settled bar"},
        "restart": "recomputed from the settled series",
        "late_start": "an excursion from a balance that predates the window is "
                      "not seen; the phase reports UNKNOWN instead",
        "consumers": [
            {"name": "structure.session_po3.derive",
             "believes": "an unresolved excursion authorizes no new entry",
             "influence": CANDIDATE_GENERATION},
            {"name": "ai_brain.brain_input",
             "believes": "price is outside the balance and the outcome is open",
             "influence": BRAIN_NARRATIVE},
        ],
        "limitations": ("Cannot say at the instant of departure what the "
                        "excursion IS. That is the point of the state.",),
        "certification_tests": (f"{T_SP}::TestExcursionUnresolved",
                                f"{T_SP}::TestDistribution"),
        "semantic_predicates": ("session_po3.excursion_needs_establishment",),
        "scenarios": (PROCESS_RESTART, REPEATED_PRICE, WARMUP_HISTORY),
    },
    {
        "fact_id": "session_po3.manipulation",
        "producer_owner": "structure.manipulation_detector.detect_manipulation",
        "representation": "delivery.session_po3.manipulation",
        "semantic_claim":
            "The confluence detector's OWN verdict -- classification band "
            "(none / possible / confirmed) and direction -- republished here "
            "because both were previously computed and discarded: po3_engine "
            "consumed only the numeric score, and PO3's manipulation_direction "
            "was derived from sweep_direction instead.",
        "authority_class": ADVISORY,
        "decision_influence": (CANDIDATE_GENERATION, BRAIN_NARRATIVE),
        "persistence": RECOMPUTED,
        "lifecycle": {
            "formation": "confluence over a 10-bar window against 40 bars of "
                         "recent swing context",
            "mutation": "recomputed each scan from settled candles",
            "invalidation": "n/a; recomputed",
        },
        "temporal": {"observation_time": "the scan's settled window"},
        "restart": "recomputed; no state",
        "late_start": "needs 6 settled candles; below that it reports none",
        "consumers": [
            {"name": "structure.session_po3.derive",
             "believes": "ONLY a `manipulation_confirmed` band, directed "
                         "opposite the excursion and not conflicted across "
                         "timeframes, may resolve an excursion to manipulation",
             "influence": CANDIDATE_GENERATION},
            {"name": "ai_brain.brain_input",
             "believes": "what the confluence detector actually said",
             "influence": BRAIN_NARRATIVE},
        ],
        "limitations": (
            "The component weights and the 25/50 classification bands are the "
            "operator's initial specification and are UNVALIDATED -- which is "
            "why this is ADVISORY and why manipulation alone never sets the "
            "phase: an excursion and a re-entry and opposing ownership are all "
            "independently required.",
            "Timeframes can disagree on direction; that is published as "
            "`conflicted` and blocks confirmation rather than being resolved.",
        ),
        "certification_tests": (f"{T_SP}::TestManipulation",),
        "semantic_predicates": ("session_po3.band_not_score",),
        "scenarios": (MTF_DISAGREEMENT, REPEATED_PRICE),
    },
    {
        "fact_id": "session_po3.delivery_preference",
        "producer_owner": "structure.session_po3.derive",
        "representation": "delivery.session_po3.preferred_playbook_families / "
                          ".distribution_direction",
        "semantic_claim":
            "Which playbook families the resolved phase PREFERS, and the "
            "direction distribution is delivering. A preference is a ranking "
            "input, never a permission and never a trade.",
        "authority_class": ADVISORY,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RECOMPUTED,
        "lifecycle": {
            "formation": "a table keyed by the resolved phase",
            "mutation": "changes with the phase",
            "invalidation": "empty in every unresolved phase",
        },
        "temporal": {"observation_time": "the scan"},
        "restart": "recomputed with the phase",
        "late_start": "empty while the phase is UNKNOWN",
        "consumers": [
            {"name": "playbooks.playbook_classifier.classify_playbook",
             "believes": "a bounded score bonus that reorders near-ties; it "
                         "never creates a playbook that scored nothing",
             "influence": BRAIN_NARRATIVE},
        ],
        "limitations": ("Cannot make a trade exist. A confirmed manipulation "
                        "with no valid reversal location yields no candidate.",),
        "certification_tests": (f"{T_SP}::TestPlaybookRouting",),
        "semantic_predicates": ("session_po3.preference_is_not_permission",),
        "scenarios": (MTF_DISAGREEMENT,),
    },
]


# == CROSS-SESSION CONTEXT ===================================================
# LUNA-CROSS-SESSION-PO3-CONTEXT-1. The first facts in this registry about a
# session OTHER than the one being traded. They inform Luna and decide nothing:
# the mechanical phase authority has no parameter through which they could
# arrive, which is why the authority class below is ADVISORY rather than
# CERTIFIED -- not because the facts are weak, but because they are structurally
# barred from being the sole basis of anything.
_SESSION_CONTEXT = [
    {
        "fact_id": "session_context.window_facts",
        "producer_owner": "market_data.session_context.derive",
        "representation": "session_context.contexts.<CONTEXT>",
        "semantic_claim":
            "For each owner-defined strategic window of the CURRENT CME trading "
            "day (ASIA_CONTEXT 20:00-00:00, LONDON_KILLZONE 02:00-05:00, "
            "LONDON_SESSION 03:00-11:30, NY_PREMARKET 04:00-09:30 ET): its "
            "availability, and -- only when every venue-expected settled 1m "
            "bucket of the elapsed window is present -- its open/high/low/range, "
            "net travel, directional delivery, expansion state and whether it "
            "took the prior context's extreme. The windows OVERLAP by design and "
            "are not a partition of the tape.",
        "authority_class": ADVISORY,
        "decision_influence": (BRAIN_NARRATIVE,),
        "persistence": RECOMPUTED,
        "lifecycle": {
            "formation": "a window opens when the trading day reaches its start; "
                         "facts accumulate causally through the newest settled bar",
            "mutation": "IN_PROGRESS facts extend with each settled bar until the "
                        "window closes and the status becomes AVAILABLE",
            "invalidation": "recomputed every scan; the whole block turns over at "
                            "the 18:00 ET CME day boundary",
        },
        "temporal": {"observation_time": "coverage.as_of, the newest settled bar "
                                         "the facts are causal through",
                     "formation_time": "the window's resolved start"},
        "restart": "RECOMPUTED from the deep settled series; no state is carried, "
                   "so a cold process replaying the same bars reproduces it",
        "late_start": "a window whose elapsed history is incomplete reports "
                      "UNAVAILABLE_HISTORY and publishes NO facts -- the "
                      "load-bearing case on a machine that started this morning",
        "consumers": [
            {"name": "ai_brain.brain_input",
             "believes": "what Asia, London and premarket already did, with each "
                         "window's availability stated; an unavailable context "
                         "carries its reason, never a high/low that reads as known",
             "influence": BRAIN_NARRATIVE},
        ],
        "limitations": (
            "AUTHORISES NOTHING. It cannot set the session PO3 phase, cannot "
            "permit an entry, and cannot be passed to `session_po3.derive`, "
            "which has no parameter for it.",
            "Current CME trading day only. There is no prior-day or multi-day "
            "cross-session claim here.",
            "ET-anchored strategy windows. ASIA_CONTEXT is NOT the Tokyo cash "
            "session -- Japan does not observe DST, so the window drifts an hour "
            "against Tokyo across the DST boundary.",
            "Coverage is only as provable as the venue calendar: a KNOWN_SPECIAL "
            "date whose exact hours are not encoded yields UNAVAILABLE_HISTORY "
            "for every window on that day.",
            "18:00-20:00 and 00:00-02:00 ET belong to no named context and are "
            "reported as excluded rather than absorbed.",
        ),
        "certification_tests": (f"{T_CS}::TestC1_FullCoverage",
                                f"{T_CS}::TestC2_PartialHistoryIsRefused",
                                f"{T_CS}::TestSessionPo3IsUnreachable"),
        "semantic_predicates": ("session_context.exact_coverage_or_no_facts",
                                "session_context.cannot_reach_the_phase"),
        "scenarios": (LATE_START, PROCESS_RESTART, WARMUP_HISTORY,
                      SESSION_BOUNDARY),
    },
]

#: THE REGISTRY. Order is presentation only; `fact_id` is identity.
CONTRACTS = tuple(_PROTECTED_SWINGS + _OCCURRENCES + _ACTIVE_PATH +
                  _LIQUIDITY + _DEALING_RANGE + _RECOVERY +
                  _SESSION_PO3 + _SESSION_CONTEXT + _LIQUIDITY_SCOPE)


def by_id() -> dict:
    return {c["fact_id"]: c for c in CONTRACTS}


def get(fact_id) -> "dict | None":
    return by_id().get(fact_id)


def with_class(authority_class) -> list:
    return [c for c in CONTRACTS if c.get("authority_class") == authority_class]


def validate_registry() -> list:
    """Every structural problem across every contract, plus duplicate ids."""
    problems = []
    seen = set()
    for contract in CONTRACTS:
        problems.extend(validate(contract))
        fid = (contract or {}).get("fact_id")
        if fid in seen:
            problems.append(f"{fid}: duplicate fact_id")
        seen.add(fid)
    return problems
