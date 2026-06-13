# PO3 Independence Audit + AB-3 Authorization (read-only, `cddd5f2`)

Audit only — no code changed. Verdicts are evidence-backed (controlled
experiments + code trace), not assumed.

## 1. What PO3 consumes (per phase)

`src/structure/po3_engine.py` — `_score_phases()` scores 4 phases from four
pre-computed dicts; `analyze_po3()` then infers direction via `_directions()`.

| Phase | Inputs (file: po3_engine.py) | Structure used? |
|---|---|---|
| **accumulation** (53-65) | exp_state, compression(dir_eff,body_dom,exp_score), dir_eff, `struct.state∈{range_bound,neutral}` (+15), atr_trend, vol_state, sweep/disp | structure STATE only (informational, +15) |
| **manipulation** (68-76) | `sweep` (+40), `reclaim` (+25), `failed_breakout` (+25), sweep&reclaim (+10) | **NONE** — 100% liquidity |
| **distribution** (79-90) | displacement (+30/10), exp_state (+25), dir_eff (+20), vol_state (+10), exhaustion (+10), `struct.state∈{bullish/bearish_continuation}` (+15) | structure STATE only (informational, +15) |
| **transition** (93-101) | `mss` (+50), `bos`&(sweep|reclaim) (+30), exp_state&sweep (+25), `struct.state∈{*_reversal}` (+20) | **HEAVY** — MSS/BOS/state drive it |
| **direction** `_directions()` (109-125) | manip_dir = sweep_dir only; dist_dir = manip_dir **or `bias`** | **manip_dir: none. dist_dir: structure-bias FALLBACK (line 120)** |

## 2. Structure dependency trace

```
structure.bias ─(line 120, only if phase=distribution AND no sweep_dir)─→ distribution_direction ─→ AUTHORING
structure.bos/mss ─→ transition score (+50/+30) ─→ phase=transition  (transition is NOT an authoring source)
structure.state ─→ accumulation/distribution score (+15 each) ─→ phase magnitude (informational, non-directional)
```
- **Directional dependency:** `distribution_direction` via line 120 bias fallback. **This is the only directional structure dependency — and it is load-bearing.**
- **Informational dependency:** structure.state lifts accumulation/distribution scores (+15). Non-directional.
- **Required dependency:** transition phase requires MSS/BOS. But transition is not consumed as an authoring source by the firewall, so this is contained.
- **manipulation_direction:** zero structure dependency.

## 3. Independence experiments (evidence)

| Exp | Setup | Result | Verdict |
|---|---|---|---|
| **A1** | sweep below_low, `struct={}` | distribution@86, manip_dir=bullish, dist_dir=bullish | classifies + directs WITHOUT structure ✓ |
| **A2** | no sweep, `struct={}`, expansion only | distribution@86, dist_dir=**None** | phase from expansion; no false direction ✓ |
| **B1** | distribution, **no bos/mss**, bias bullish, NO sweep | dist_dir=**bullish (from structure bias)** | **CONTAMINATION** ✗ |
| **B2** | same, bias bearish | dist_dir=**bearish (from structure bias)** | **CONTAMINATION** ✗ |
| **C1/C2** | only sweep (above_high / below_low), `struct={}` | dist_dir=bearish / bullish | fully independent ✓ |
| **D1** | bias bullish CONFLICTS sweep above_high | dist_dir=**bearish** (sweep wins via manip_dir) | sweep overrides structure when present ✓ |

Unit proof: `_directions("distribution", None, "bullish") → (None, "bullish")`;
`(…, "below_low", "bearish") → ("bullish","bullish")` (sweep wins).

**Conclusion:** PO3 can classify distribution/manipulation/accumulation and
direct manipulation **without structure**. The single failure is
`distribution_direction` when **no sweep exists on that TF** — it falls back to
structure bias (B1/B2).

## 4. June 11 evidence (with archive limitation stated)

Raw `po3` is **not persisted** in `data/live_snapshots/` (confirmed — archives
carry the `ai_context.summary` PO3 phase text but not `distribution_direction`).
So provenance cannot be byte-traced from archives. What IS established:

- June 11 morning carried a live **`above_high@15m` sweep+reclaim** on the entry
  scans (narrative audit + ledger). With a sweep present, `manip_dir` is set and
  `dist_dir = manip_dir` (sweep-derived) — the bias fallback did **not** drive
  the 10:13–10:40 long-side reads; sweep semantics did. Experiment D confirms
  sweep dominates structure when both exist.
- The risk is the **no-sweep distribution** scan: a 5m/15m in distribution phase
  with no fresh sweep but a directional structure bias → `distribution_direction`
  = structure bias. This is exactly B1/B2 and is not visible in the archives.

So June 11's specific decisions were sweep-driven, but the engine **will** emit
structure-derived direction on no-sweep distribution scans — a latent path, not
a June-11-specific one.

## 5. Final classification

**B — Partially dependent.**
- Phase classification: independent enough (manipulation 100% independent;
  accumulation/distribution use structure state only as non-directional score;
  transition is structure-heavy but not an authoring source).
- Direction: `manipulation_direction` independent; **`distribution_direction`
  carries a directional structure-bias fallback (line 120).**

Not "A independent" (the fallback is real and directional). Not "D
structure-authored in disguise" (manipulation + sweep-present distribution are
genuinely independent; structure only fills the no-sweep vacuum). Precisely B.

## CRITICAL finding — the leak is already live in AB-2A

`generation_firewall.nonstructure_direction()` reads
`po3.distribution_direction` **first** (authorship.py:68-71), before sweep
semantics. Therefore, in the no-sweep-distribution + directional-bias case,
**AB-2A's firewall currently authors `qualification.direction` from structure
bias, mislabeled `delivery_protected`.** AB-2A's claim "structure cannot author
direction" has this one hole. It is narrow (requires distribution phase, no
15m/5m sweep, directional bias) but it is live.

## AB-3 Authorization Gate

**Can AB-3 begin safely? → YES.**

Reasoning: AB-3 is retrieval/embeddings/similarity/memory only — it does NOT
author trades, does NOT make `distribution_direction` load-bearing, and does
NOT wire authority. The PO3 leak is a generation/authority defect; it cannot be
triggered by retrieval. AB-3 may proceed in parallel.

Two conditions attached (neither blocks AB-3 start):
1. **Hard blocker for AB-4** (must fix before delivery/narrative becomes
   load-bearing): neutralize the `_directions` line-120 structure-bias fallback
   so `distribution_direction` is sweep/displacement-derived only (return None
   when no sweep_dir, even in distribution). Recommend a small **AB-2C** patch
   before AB-4. Until then the AB-2A hole stands.
2. **AB-3 retrieval hygiene** (in-scope, minor): retrieval feature vectors key on
   `qualification.direction` / `playbook.direction`, which can inherit the leak.
   AB-3 must (a) tag snapshots whose `direction_source` is structure-derived and
   (b) prefer sweep/delivery-confirmed direction as a retrieval feature, so
   analog matching is not polarized by a tainted direction label.

## AB-2C UPDATE (SHIPPED) — leak closed

The line-120 fallback is removed. `po3_engine._directions` now returns
`(manip_dir, manip_src, dist_dir, dist_src)`; `distribution_direction` derives
ONLY from the sweep-derived manipulation direction (no structure-bias fallback).
Every PO3 directional output carries provenance
(`manipulation_direction_source`, `distribution_direction_source`,
`delivery_direction`/`delivery_direction_source`) ∈ {sweep_semantics,
liquidity_reclaim, protected_swing, explicit_po3_transition, fallback_none}.

The firewall (`nonstructure_direction`) now accepts a PO3 direction ONLY when
its `*_source` is a valid non-structure source; missing or structure-tainted
provenance is rejected. Experiments re-run: B (structure bias only) now returns
`distribution_direction=None`, `delivery_direction_source=fallback_none`. The
AB-2A firewall hole is closed. Tests: `tests/test_phase_ab2c_po3_provenance.py`.
Regression 959 passed. **PO3 status after fix: independent for direction
(structure cannot author through PO3).**

### AB-3 implementation plan (retrieval only)

- **AB-3.1 — Embedding feature builder.** New `src/memory_retrieval/` (parallel
  to the categorical `memory_search`, not a replacement). Build a numeric/text
  feature vector per snapshot from: delivery state+confidence, protected-swing
  state, liquidity draw, narrative phase, regime, session, volatility/expansion,
  sweep events — **excluding raw structure bias**; include `direction_source`
  as a tag, not a polarity.
- **AB-3.2 — Vector store.** Local embeddings over archived snapshots + closed
  trades + blocked/missed trades; cosine similarity retrieval. Observe-only
  store; no authority. Persist to `data/ai_retrieval/`.
- **AB-3.3 — Historical analog retrieval API.** `retrieve_analogs(snapshot, k)`
  → top-k prior contexts with outcomes (win/loss/R, what happened next, whether
  structure lagged, whether delivery led). Feeds the AB-1 brain's
  `memory_matches[]` slot (currently empty) — observe-only.
- **AB-3.4 — Narrative-context retrieval.** Retrieve prior AI-brain narratives
  for similar contexts (once AB-1 brain has logged enough) — observe-only.
- **AB-3 acceptance:** retrieval returns analogs with outcomes; feature vectors
  contain no raw structure bias; tainted-direction snapshots are flagged;
  retrieval output is consumed by nobody with authority (observe-only); full
  regression green.
- **AB-3 explicitly excludes:** authority wiring, generation/playbook/toolbox
  replacement (AB-4/AB-5).

## Deliverable summary
- Dependency map — §1/§2. Proof tests — §3 (experiments A–D + unit). June 11 —
  §4 (sweep-driven on the key scans; archive can't byte-trace dist_dir; latent
  no-sweep path proven in code). Classification — **B, partially dependent**.
- **AB-3 go/no-go — GO**, with an AB-2C pre-AB-4 blocker and AB-3 retrieval
  hygiene conditions.
