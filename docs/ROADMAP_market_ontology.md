# Roadmap — finishing the market ontology

Authored 2026-08-11 by the operator, recorded verbatim in intent. Base release
**v14 `02dbb80`**, trading **DISARMED**.

## The destination

> A discretionary AI trader that understands where price is in its delivery
> sequence, reasons from truthful market facts, selects an appropriate
> playbook/tool, defines why the trade is wrong and where price is drawing, then
> lets deterministic risk/execution machinery decide whether that idea is
> executable.

## The reframe

We are not trying to make the bot take better trades. We are building the
**market ontology** that lets Terra understand what the market is doing and why.
Only once that ontology is truthful do we find out how good the Brain actually is.

The organs mostly exist — Terra's reasoning, MTF factual roles, protected
structure, the FVG/IFVG/OTE toolbox, risk, execution, durable lifecycle. What is
unfinished is the **semantic nervous system between them**. The organism does not
yet consistently distinguish:

```
a low  ≠  a swing low  ≠  liquidity  ≠  the active draw
                       ≠  a local objective  ≠  an external objective
an entry invalidation  ≠  a narrative invalidation
```

…nor the phase of price delivery connecting all of them.

### Semantic law

> A candle low is not automatically a swing low.
> A swing low is not automatically liquidity.
> Liquidity is not automatically the active draw.
> A draw is not automatically the external objective.

### Constitutional law

> **Absence may never masquerade as continuity.**

## Where we are

**Execution chassis — trustworthy.** v14 closed the mission-lifecycle holes: ACK
identity, spent-token semantics at the venue boundary, authoritative post-submit
reconciliation, restart recovery, terminal progression. 4,550 tests, 16/16
lifecycle mutations caught, doctrine unchanged (40/35/$250/15/1R). Execution
plumbing is no longer the primary intellectual problem.

**Terra — genuine reasoning, untested premise.** At 11:03 it independently
reasoned raid → extension → reclaim → protected high → sell-side objective →
explicit failure condition, and handled MTF conflict intelligently rather than
obeying the 1m witness. But it was missing ~20 minutes of history containing the
whole accumulation → manipulation through 29,800 → rejection → distribution
sequence.

> We do **not** know that Terra cannot understand Po3. We know the bot never gave
> Terra the complete Po3 to understand. Those are worlds apart. That experiment
> has never been run under clean conditions.

**Known defects, ranked:** candle continuity (foundational) · liquidity semantics
· objective identity + hierarchy · invalidation scope · toolbox validation gap ·
big-figure absence.

**Toolbox — closer to the vision than expected.** It exposes; Terra selects; it
cannot substitute. Only the validation half is missing.

**ECU — not the next switch.** Philosophically aligned with the destination, but
turning it on now gives more authority to a Brain with incomplete history,
questionable liquidity semantics, a flat objective architecture, no big-figure
context and undifferentiated invalidation. **Finish the eyes and ears before
promoting the cortex.**

## The path — strictly ordered, never combined into one mission

1. **Freeze v14, stay DISARMED.** No intelligence tuning from the V13 loss. No
   stop tweak, no target tweak, no ECU. v14 is the engineering base.
2. **Canonical candle continuity.** Startup REST backfill, continuity
   verification, runtime/reconnect gap detection and backfill, deterministic
   higher-TF construction from canonical history, explicit degradation and
   fail-closed cognition when history cannot be repaired. Prove a restart across
   10:41–11:01 no longer deletes those minutes.
3. **Audit and repair primitive market semantics — liquidity first.** Trace what
   populates `lows`, why 29,752.50 entered `nearest_sell_side`, what distinguishes
   a bar low from swing liquidity, and what deterministic facts would identify the
   29,722.25 pool. Build vocabulary for `price_low` / `swing_low` /
   `protected_low` / `liquidity_pool` / `liquidity_state` / `active_draw` —
   **without hardcoding the chart answer.**
4. **Reconstruct the 10:40–11:03 tape through production detectors.** Only after
   continuity exists. Ask solely what deterministic facts emerge. No
   counterfactual "Terra would have won."
5. **Objective identity and hierarchy.** IDs must identify market facts, not list
   positions. Separate structural references from liquidity objectives. Create
   internal/intermediate/external scope where structure genuinely supports it.
   **Expose the hierarchy; never force Terra to target the farthest level.**
6. **Execution-vs-narrative invalidation semantics.** A level should say what it
   invalidates. Local 1m/3m structure can invalidate an entry expression without
   invalidating the narrative. **Expose both; never tell Terra "always use the
   wider one."**
7. **Close the toolbox validation gap.** Terra may select only a genuinely
   detected executable tool for its direction/playbook. `FORMING` is visible
   context but **not** executable evidence. Absent tool → named veto
   (`TOOL_NOT_DETECTED` / `TOOLBOX_DEFERRED`). **Never substitute.**
8. **Big-figure facts as context.** 00/50/major figures, excursion, acceptance,
   rejection, distance. Pure evidence, no directional authority. Never
   "29,800 means short" — only "this event occurred relative to a major
   reference." Terra interprets significance.
9. **The real Market Narrative experiment.** With continuous data and truthful
   facts, replay this exact 2026-08-11 sequence and ask Terra fresh — without
   feeding it the human interpretation — what phase it sees, where manipulation
   occurred, what the active draw is, what playbook applies, what tool it selects,
   and what invalidates that expression. First fair test of whether Terra
   independently reconstructs the Po3.
10. **Only then revisit ECU.** Audit original intent against the clean organism;
    compare downstream-Terra vs upstream-ECU-Terra offline on identical complete
    evidence. The question is **not** "does ECU generate more trades." It is:
    does moving narrative authorship upstream produce more coherent, stable,
    temporally aware market understanding without sacrificing deterministic truth
    and veto authority?
11. **Finish with production proving, not launch.** Regression + mutation tests,
    clean historical replay, malformed-data tests, restart tests, objective and
    invalidation identity tests, toolbox non-substitution tests, final preflight.
    After any material production change: **READY_TO_LAUNCH — DISARMED.** Only a
    fresh operator `GO LIVE` arms it.

## Evidence pointers

- `data/integration/topstepx/AUDIT_V13_market_reality_objectives_PO3.md`
- `data/integration/topstepx/AUDIT_terra_narrative_cognition_V13.md`
- `data/integration/topstepx/AUDIT_playbook_toolbox_authority_V13.md`
- `data/integration/topstepx/FORENSIC_execution_lifecycle_PROD-20260811-V13.md`
