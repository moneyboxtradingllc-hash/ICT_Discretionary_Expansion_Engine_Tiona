"""EPISTEMIC-CLOSURE-CERTIFICATION-1 — governance of what the organism CLAIMS.

`rule_governance` governs RULES: predicates that gate candidates, with a
shadow/promoted lifecycle and mutable runtime state under `data/`. This
sub-package governs FACTS: what the organism asserts about the market, who owns
each assertion, what it means, how it is born and dies, which clocks it carries,
who reads it, and what it cannot say.

It lives HERE rather than as a second top-level package because governance has
one home. The conventions are the ones `rule_registry` established -- declaration
as data, logic as code, an explicit status lifecycle, quarantine rather than
raise -- with one deliberate difference: fact contracts are SOURCE, not `data/`.
Rule status is runtime state a session mutates; a fact contract is a claim about
what the code means, and it must be reviewable in a diff and identical on every
machine. A verifier that passes because a file is missing would be worse than no
verifier at all.

    fact_contract        what a contract must declare, and what makes it invalid
    fact_registry        the contracts themselves
    bootstrap_debt       authority that predated this gate, frozen
    capability_matrix    the negative space: what we cannot express
    payload_coverage     which payload paths are claimed by which lane
    semantic_predicates  meanings as executable checks against real tape
    authority_ast        authority read structurally, not lexically
    closure_verifier     the release gate
    pre_live_report      what mechanics believes, for a human, before a session

NOTHING HERE DECIDES ANYTHING. No production module imports this package; a test
enforces that. It observes, and it refuses.
"""
