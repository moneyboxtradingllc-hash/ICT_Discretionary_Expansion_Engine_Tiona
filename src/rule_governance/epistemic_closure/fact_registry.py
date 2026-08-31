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


# ══ PROTECTED SWINGS ════════════════════════════════════════════════════════
# CERTIFIED as of PROTECTED-SWING-CAUSAL-TIME-1. Before that unit the semantic
# contract below was FALSE: the producer re-stamped `registered_at` on every
# reaffirmation while every consumer read it as a birth time.
_PROTECTED_SWINGS = [
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
                  _SESSION_PO3 + _SESSION_CONTEXT)


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
