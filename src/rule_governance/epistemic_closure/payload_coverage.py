"""EPISTEMIC-CLOSURE-CERTIFICATION-1 — what actually reaches Luna.

STRUCTURAL, NOT TEXTUAL. Coverage is computed by building a REAL Brain payload
with `ai_brain.brain_input.build_brain_input` and walking its actual key paths.
A grep over source would miss anything assembled conditionally and would break
on every refactor; the payload itself cannot lie about what it contains.

THE GATE IS THE FRONTIER, NOT THE BACKLOG. Every observed path must be
classified into exactly one lane. A path that matches nothing is a FAILURE --
that is what makes a newly added Brain fact fail closed instead of arriving
silently, which is the whole point of §7.

HONEST BOOTSTRAP. This framework arrives long after the payload did, so most
market paths do not yet have contracts. Pretending otherwise would mean either
marking them certified (a lie) or failing the gate permanently (useless). They
are instead enumerated in `KNOWN_UNCERTIFIED` -- visible, counted, and pinned.

    the set may SHRINK as contracts are written
    it may never GROW without a deliberate edit that appears in review

So the organism does not claim to have certified its whole payload. It claims
to know exactly which parts it has not, which is the claim it can actually back.
"""
from __future__ import annotations

from rule_governance.epistemic_closure.fact_registry import by_id

# ── LANES ───────────────────────────────────────────────────────────────────
MARKET_FACT = "market_fact"        # an assertion about the market; needs a contract
OPERATIONAL = "operational"        # how the scan went, not what the market did
DISPLAY = "display"                # legends, disclaimers, notes, role labels
WITNESS = "witness"                # published under an explicit non-deciding lock
MEMORY = "memory"                  # htf_memory: hard-locked context_only
UNCERTIFIED = "uncertified"        # a market fact with no contract YET

#: Paths that carry a market assertion AND have a registered contract.
CONTRACTED = {
    "active_path_state.owner": "active_path.owner",
    "active_path_state.load_bearing_structure": "active_path.load_bearing_structure",
    "liquidity.nearest_buy_side": "liquidity.brain.nearest_buy_side",
    "liquidity.nearest_sell_side": "liquidity.brain.nearest_sell_side",
    "market.dealing_range": "dealing_range.bounds",
    "protected_swings.by_timeframe": "protected_swing.registered_at",
    "protected_swings.protected_high": "protected_swing.level",
    "protected_swings.protected_low": "protected_swing.level",
    # LUNA-SESSION-PO3-AUTHORITY-1 -- the canonical session phase and the entry
    # ruling that belongs to it. Registered specifically rather than as one
    # prefix so the RANGE, the EXCURSION and the detector's verdict each answer
    # for themselves; the phase is the only one of them that decides.
    "delivery.session_po3.phase": "session_po3.phase",
    "delivery.session_po3.new_entry_allowed": "session_po3.new_entry_allowed",
    "delivery.session_po3.range": "session_po3.range",
    "delivery.session_po3.excursion": "session_po3.excursion",
    "delivery.session_po3.manipulation": "session_po3.manipulation",
    "delivery.session_po3.preferred_playbook_families": "session_po3.delivery_preference",
    "delivery.session_po3.distribution_direction": "session_po3.delivery_preference",
    # LUNA-CROSS-SESSION-PO3-CONTEXT-1 -- what Asia, London and premarket did.
    # One claim per context block; the availability status is inseparable from
    # the facts it guards, so they answer under one contract rather than two.
    "session_context.contexts": "session_context.window_facts",
}

#: How the scan went. Never a claim about the market.
OPERATIONAL_PATHS = (
    "conflicts", "degraded", "warnings", "session", "timestamp",
    # Whether the phase authority ran at all -- an operational condition, and
    # deliberately distinct from what it concluded.
    "delivery.session_po3.available",
    # Whether the cross-session producer ran, which trading day it resolved, and
    # the settled bar its facts are causal through. Operational scaffolding
    # around the claim, not the claim.
    "session_context.available", "session_context.trading_day",
    "session_context.as_of",
    "governance_context.regime", "position.position_open",
    "MTF_MARKET_STATE.schema_version", "MTF_MARKET_STATE.timestamp",
    # The whole MTF block collapses to a bare leaf when the producer had
    # nothing to publish -- seen on the degraded 2026-08-10 session. An outage
    # is an operational condition, not a new market fact.
    "MTF_MARKET_STATE",
    # The Brain's own prior stances -- what WE said, never what the market did.
    "stance_history",
    # A whole block collapses to a bare leaf when it is absent. That is an
    # operational condition (the producer had nothing to publish), and it must
    # still be classified or an outage would read as an unclassified new fact.
    "active_path_state",
    "active_path_state.state_available", "active_path_state.unavailable_reason",
    "active_path_state.session", "active_path_state.last_reset_reason",
    "active_path_state.ownership_changed_this_scan",
)

#: Labels and legends. They explain the payload; they assert nothing.
DISPLAY_PATHS = (
    "market.price_path_legend", "market.price_path_schema",
    "liquidity.capability_legend", "STRUCTURE_WITNESS._disclaimer",
    "active_path_state.notes", "playbook_toolbox.note", "volume_witness.note",
    "protected_swings.roles", "MTF_MARKET_STATE.roles",
    # Prose that explains a ruling already declared elsewhere. Carries no market
    # claim of its own: `block_reason` restates the phase, `transition_reason`
    # restates the evidence that produced it.
    "delivery.session_po3.block_reason", "delivery.session_po3.transition_reason",
    # A standing disclaimer, not a market claim: it tells the reader the block
    # authorises nothing.
    "session_context.note",
)

#: Published under an explicit, tested non-deciding lock. `STRUCTURE_WITNESS`
#: carries its own disclaimer and had its directional fields removed as the
#: AB-5A-S leak; `volume_witness` declares `decision_authority` in-band.
WITNESS_PREFIXES = ("STRUCTURE_WITNESS.", "volume_witness.")

#: `htf_memory` is hard-locked AUTHORITY_LEVEL="context_only", and a test already
#: forbids any execution/gate/decision module from reading it. That lock is not
#: weakened here, and re-litigating it is out of scope.
MEMORY_PREFIXES = ("htf_memory.",)

#: MARKET FACTS WITHOUT CONTRACTS -- the bootstrap debt, pinned.
#:
#: Each of these is a genuine market assertion that predates this framework.
#: They are listed so that (a) the debt is countable, (b) nothing new can hide
#: among them, and (c) writing a contract is a visible deletion from this tuple.
KNOWN_UNCERTIFIED = (
    # multi-timeframe state -- the largest single block
    "MTF_MARKET_STATE.price", "MTF_MARKET_STATE.synthesis",
    "MTF_MARKET_STATE.timeframes",
    # delivery / PO3
    "delivery.confidence", "delivery.continuation_intact",
    "delivery.exhaustion_present", "delivery.po3_15m", "delivery.po3_alignment",
    "delivery.state",
    # price and volatility
    "market.candles", "market.current_price", "market.execution_price",
    "market.expansion_state", "market.realtime_volatility",
    "market.settled_price_basis", "market.volatility_state",
    "market.volatility_state_temporal_class",
    # liquidity beyond the two legacy fields
    "liquidity.active_draw",
    # Both spellings: the `[]` form when rows exist, the bare form when the list
    # is empty. One fact, two shapes.
    "liquidity.evaluation[]", "liquidity.evaluation",
    "liquidity.events[]", "liquidity.events",
    "liquidity.sensors",
    # playbook / toolbox
    "playbook_toolbox.active_direction", "playbook_toolbox.active_playbook",
    # Both list shapes: the `[]` form when rows exist, the bare form when empty.
    "playbook_toolbox.bearish[]", "playbook_toolbox.bearish",
    "playbook_toolbox.bullish[]", "playbook_toolbox.bullish",
    "playbook_toolbox.mechanical_direction_recommendation",
    "playbook_toolbox.mechanical_playbook_recommendation",
    # active path fields with no contract yet
    "active_path_state.adverse_replacements", "active_path_state.forming_direction",
    "active_path_state.last_invalidated", "active_path_state.origin",
    "active_path_state.progression", "active_path_state.status",
    "active_path_state.transfer_evidence",
    # protected swing summary fields
    "protected_swings.protected_high_status", "protected_swings.protected_low_status",
    # Structure flips carry swing_id, price and lifecycle_state -- a market
    # assertion, not an operational counter. Both list shapes.
    "structure_flips[]", "structure_flips",
)

#: The tool catalog is execution-bearing and entirely uncontracted. It is
#: matched by prefix because its rows are dicts in a list, so its paths are
#: `authorized_tool_catalog[].{field}` and enumerate the toolbox's whole schema.
UNCERTIFIED_PREFIXES = ("authorized_tool_catalog[].",)

#: The catalog itself, when it is empty and collapses to a bare leaf.
UNCERTIFIED_BARE = ("authorized_tool_catalog",)


def payload_paths(payload) -> list:
    """Every leaf path in a real Brain payload, list rows collapsed to `[]`."""
    out = []

    def walk(node, prefix=""):
        if isinstance(node, dict):
            if not node:
                out.append(prefix)
                return
            for key, value in node.items():
                walk(value, f"{prefix}.{key}" if prefix else str(key))
        elif isinstance(node, list) and any(isinstance(r, dict) for r in node):
            keys = sorted({k for r in node if isinstance(r, dict) for k in r})
            for key in keys:
                out.append(f"{prefix}[].{key}")
        else:
            out.append(prefix)

    walk(payload)
    return sorted(set(out))


def _ancestors(path) -> list:
    """Every declarable key for a path, longest first.

    LONGEST-PREFIX, NOT FIXED-DEPTH. A fixed depth-2 key cannot classify
    `market.candles.15m.recent[].close`, whose meaningful owner is
    `market.candles` four levels up -- and the payload nests to different depths
    in different branches. Matching longest-first also lets one specific path be
    declared separately from its parent without the parent swallowing it.

    List markers stay attached to their segment, so `liquidity.events[]` is a
    declarable key distinct from `liquidity.events`.
    """
    parts = path.split(".")
    return [".".join(parts[:i]) for i in range(len(parts), 0, -1)]


def classify(path) -> tuple:
    """(lane, fact_id or None) for one payload path.

    Returns lane None when nothing claims it -- which the verifier treats as a
    failure, because an unclaimed market path is exactly how a new fact would
    otherwise reach Luna uncertified.
    """
    if any(path.startswith(p) for p in WITNESS_PREFIXES):
        return WITNESS, None
    if any(path.startswith(p) for p in MEMORY_PREFIXES):
        return MEMORY, None
    if any(path.startswith(p) for p in UNCERTIFIED_PREFIXES):
        return UNCERTIFIED, None
    for key in _ancestors(path):
        if key in CONTRACTED:
            return MARKET_FACT, CONTRACTED[key]
        if key in OPERATIONAL_PATHS:
            return OPERATIONAL, None
        if key in DISPLAY_PATHS:
            return DISPLAY, None
        if key in KNOWN_UNCERTIFIED or key in UNCERTIFIED_BARE:
            return UNCERTIFIED, None
    return None, None


def coverage(payload) -> dict:
    """Classify a whole payload. `unclassified` non-empty means FAIL."""
    lanes = {MARKET_FACT: [], OPERATIONAL: [], DISPLAY: [], WITNESS: [],
             MEMORY: [], UNCERTIFIED: []}
    unclassified = []
    facts = set()
    # WHICH PATH CARRIES WHICH FACT. The bootstrap-expansion check needs this to
    # tell "the debt still occupies its frozen path" from "the debt has spread".
    path_to_fact = {}
    for path in payload_paths(payload):
        lane, fact_id = classify(path)
        if lane is None:
            unclassified.append(path)
            continue
        lanes[lane].append(path)
        if fact_id:
            facts.add(fact_id)
            path_to_fact[path] = fact_id
    return {
        "lanes": {k: sorted(v) for k, v in lanes.items()},
        "counts": {k: len(v) for k, v in lanes.items()},
        "unclassified": sorted(unclassified),
        "contracted_facts": sorted(facts),
        "path_to_fact": path_to_fact,
        "uncertified_debt": len(lanes[UNCERTIFIED]),
        "total_paths": sum(len(v) for v in lanes.values()) + len(unclassified),
    }


def validate_manifest() -> list:
    """The manifest's own integrity, independent of any payload."""
    problems = []
    registry = by_id()
    for path, fact_id in CONTRACTED.items():
        if fact_id not in registry:
            problems.append(f"payload path {path!r} maps to unregistered fact "
                            f"{fact_id!r}")
    declared = (set(CONTRACTED) | set(OPERATIONAL_PATHS) | set(DISPLAY_PATHS)
                | set(KNOWN_UNCERTIFIED))
    if len(declared) != (len(CONTRACTED) + len(OPERATIONAL_PATHS)
                         + len(DISPLAY_PATHS) + len(KNOWN_UNCERTIFIED)):
        # One path in two lanes would make classification order-dependent.
        seen, dupes = set(), set()
        for group in (CONTRACTED, OPERATIONAL_PATHS, DISPLAY_PATHS,
                      KNOWN_UNCERTIFIED):
            for path in group:
                if path in seen:
                    dupes.add(path)
                seen.add(path)
        problems.append(f"payload paths claimed by more than one lane: "
                        f"{sorted(dupes)}")
    return problems
