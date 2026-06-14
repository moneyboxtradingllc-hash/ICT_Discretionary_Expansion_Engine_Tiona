# AB-6B — Playbook Classification Audit

**Evidence only. No code, ownership, ECU, prompt, playbook, or tool change.**

AB-6A recorded 26 playbook selections, **100% liquidity_sweep_reversal (LSR)**.
This audit asks *why*: did the ECU genuinely observe only LSR conditions
(A — objectively correct), or is it collapsing multiple narratives into one
classification (B — over-classification)?

Method: used the AB-6A reconstruction records first; then ran one observe-only
probe (`ab6b_probe.py`) over **June 11 09:30–11:00** at 5-min resolution to
capture the one field AB-6A did not store — the Brain's **raw
`playbook_family`** — alongside `opportunity_type`, the classifier's
`selected_playbook`, and the six mechanical playbook scores. No production code
was touched. Raw probe: `data/ab6b_june11_probe.json`.

## Bottom line (answer to A vs B)
**Neither A nor a clean B — the 100% concentration is substantially a
*harness + routing artifact*, and AB-6A therefore cannot prove the Brain
collapses genuinely-distinct live narratives.** Three compounding structural
causes force LSR; none of them is "only LSR conditions were present." Detail
below. This is the honest, evidence-first conclusion — and the reason the
"Most Important Rule" (determine why before fixing) matters here: a naive read
of AB-6A would have blamed the Brain's reasoning, but the dominant cause is
upstream of the reasoning.

---

## Phase 1 — Playbook opportunity audit (alternatives per LSR scan)
For every scan the six playbooks were scored by the *unchanged* mechanical
scorers (the Brain's choice was never replaced — alternatives only evaluated).
Representative pattern (June 11 probe, identical shape across all LSR scans):

| Playbook | Typical score | PRIMARY / SECONDARY / NOT_PRESENT |
|---|---|---|
| liquidity_sweep_reversal | 15 (no live sweep) or 73 (sweep+reclaim) | PRIMARY when sweep present; otherwise weak |
| **failed_breakout_reversal** | **45–60 (every scan)** | **SECONDARY — and often out-scores LSR** |
| range_expansion | 45 (every scan) | SECONDARY |
| manipulation_to_distribution | 0–30 | NOT_PRESENT→partial |
| trend_continuation | **0 (every scan)** | NOT_PRESENT |
| opening_drive | **0 (every scan)** | NOT_PRESENT (hard session gate) |

Finding: **LSR was frequently NOT the top mechanical score.** On the many scans
where no fresh sweep was in the window, LSR scored 15 while
failed_breakout_reversal scored 45–60 and range_expansion 45. Under pure
mechanical classification the distribution would **not** be 100% LSR. The 100%
comes from the ECU branch overriding the score whenever the Brain asserts an
opportunity (by design — Brain owns selection) — see Phase 3.

## Phase 2 — Missed-classification analysis (full / partial / zero across Jun 9–11)
Counts use the mechanical scorers as a neutral "conditions present" yardstick
(full ≥60, partial 30–59, zero <30), applied to the reconstruction inputs:

| Playbook | full | partial | zero | observed-selected |
|---|---|---|---|---|
| liquidity_sweep_reversal | on sweep scans | rest | — | **26 (100%)** |
| failed_breakout_reversal | **frequent (45–60)** | frequent | rare | **0** |
| range_expansion | 0 | **frequent (45)** | some | 0 |
| manipulation_to_distribution | 0 | occasional (≤30) | most | 0 |
| trend_continuation | 0 | 0 | **all** | 0 |
| opening_drive | 0 | 0 | **all** | 0 |

- **failed_breakout_reversal** partially-to-fully matched on essentially every
  scan yet was **never selected** — the strongest "missed classification."
- **trend_continuation** and **opening_drive** scored **zero everywhere** —
  not because the market lacked trends/opens, but because the reconstruction
  input never encoded the evidence they need (see Phase 5 / cause A).

## Phase 3 — Narrative compression audit (the mechanism)
The Brain is **not** authoring four distinct stories that get squeezed into LSR;
the evidence shows the stories never reach the classifier as distinct keys.
Three compounding causes, each documented from the probe:

**Cause A — Single-template reconstruction input (AB-6A harness `mk()`).**
The dyno snapshot hardcodes, every scan: `po3.phase="manipulation"`,
`liquidity.sweep_detected/reclaim_detected=True` (when a sweep string exists),
`expansion="early_expansion"`, `exhaustion_present=True`,
`ai_context.directional_bias="neutral"`, and **never** sets `session` or
`po3.alignment`. Consequence in the probe's mechanical scores:
`trend_continuation=0` (needs a directional_bias) and `opening_drive=0` (hard
`session=="ny_open"` gate) on **every single scan**. The input is a
manipulation/reclaim template — it physically cannot present a clean-trend,
opening-drive, distribution, or range-break story. **The Brain could not
classify what it was never shown.**

**Cause B — `opportunity_type` → playbook collapse (`_PHASE_TO_PLAYBOOK`).**
`playbook_classifier.py:425-431` maps **manipulation, reversal, AND exhaustion
→ liquidity_sweep_reversal** (only continuation→trend, distribution→m2d differ).
In the probe **`opportunity_type` was `exhaustion` on every directional scan**
(bullish early, bearish later — direction flipped, type never did). Three
distinct narrative phases funnel into one playbook by construction.

**Cause C — LLM rarely emits a valid playbook key.** Probe `playbook_family`
values were only ever `liquidity_sweep_reversal`, `none`, or `exhaustion`
(the last is an opportunity_type word, not a playbook). It **never** emitted the
other five keys. When the value is not a valid scorer key, the classifier falls
back to Cause B. So:
- 09:43 / 09:53 / 10:28 / 10:38 — LLM said `liquidity_sweep_reversal` → used.
- 09:48 / 10:33 — LLM said `none` → routed to LSR by exhaustion.
- 10:13 / 10:18 / 10:43 — LLM said `exhaustion` → routed to LSR by exhaustion.

**Quoted Brain reasoning (verbatim, probe):**
- 10:28 bearish: *"persistent bearish delivery evidenced by declining price
  action, successful liquidity sweeps above highs, and the absence of buy-side
  liquidity… The protected high at 703.53 remains a key resistance level."*
- 09:43 bullish: *"The presence of a bullish delivery state combined with
  liquidity sweeps reinforces a bullish narrative, but the associated exhaustion
  raises caution."*
- 10:38 bearish: *"the inability of price to sustain above recent highs,
  indicating weakness and the potential for a corrective move back towards
  sell-side liquidity."*

The reasoning is **always a sweep/exhaustion-reversal story** — consistent with
the input it was given. It never reasons about continuation, distribution after
delivery, or a range break, because the input never describes those. So the
compression is real, but it originates **upstream of the Brain's reasoning**
(input template + phase-map vocabulary), not from the Brain discarding stories
it actually saw.

## Phase 4 — June 11 deep classification review (09:30–11:00)
1. **Was LSR the best classification?** For the *given input*, LSR or
   failed_breakout_reversal — they trade places; FBR out-scored LSR (45–60 vs 15)
   on every no-fresh-sweep scan. LSR is defensible only on the sweep+reclaim
   scans (score 73). So "best" is **not clearly LSR**.
2. **Could manipulation_to_distribution have been equally valid?** Partially —
   it scored ≤30 (input set phase=manipulation but never alignment=
   manipulation_to_distribution, which is the 35-pt trigger). Plausible story,
   structurally under-fed.
3. **Could trend_continuation have been equally valid?** **No, as fed** — scored
   0 every scan because `directional_bias` was hardcoded neutral. Cannot judge
   the real market; the input vetoed it.
4. **Did the Brain explicitly discuss expansion after delivery?** No. Reasoning
   centered on sweeps, exhaustion, protected highs/lows, and "no liquidity
   taken." Expansion-after-delivery (the continuation story) was never narrated.
5. **Did it recognize continuation behavior separately from reversal?** No — every
   directional read was framed as reversal/corrective ("corrective move back
   towards sell-side liquidity"), never as continuation of a trend.
6. **One story or multiple overlapping?** **One story, repeated:** sweep →
   exhaustion → reverse. Direction flipped (bullish 09:43–09:53 → bearish 10:13+,
   LLM run-to-run variance on ambiguous open data) but the *narrative shape* and
   the playbook never varied. Playbook was pinned to LSR regardless of direction.

## Phase 5 — Canonical playbook reachability (three distinct senses)
| Playbook | reachable in **theory** (code) | reachable in **practice** (this harness/prompt) | **observed** (Jun 9–11) |
|---|---|---|---|
| liquidity_sweep_reversal | ✅ | ✅ | ✅ 26 |
| trend_continuation | ✅ (AB-5C test) | ❌ input pins bias=neutral → score 0; LLM never names it | ❌ 0 |
| manipulation_to_distribution | ✅ | ⚠️ only via LLM naming key or phase=distribution (never fed) | ❌ 0 |
| failed_breakout_reversal | ✅ | ⚠️ scores high but ECU branch needs the LLM to *name* it (it doesn't) | ❌ 0 |
| opening_drive | ✅ | ❌ hard `session=="ny_open"` gate never set by harness | ❌ 0 |
| range_expansion | ✅ | ⚠️ scores 45 but ECU branch overrides to LSR via phase map | ❌ 0 |

**The distinction is the headline:** all six are reachable in code (AB-5C proved
it), but under the current prompt + `_PHASE_TO_PLAYBOOK` + AB-6A reconstruction
input, **only LSR is reachable in practice**, and only LSR was observed. "Reachable
in code" ≠ "reachable in practice" ≠ "observed."

## Phase 6 — MAP-6B
1. **Is LSR overrepresented?** Yes — 100% of selections; mechanically it was
   often not even the top score.
2. **Is the Brain collapsing classifications?** Yes, but **mostly not in the
   LLM's reasoning** — the collapse is in (B) the phase-map vocabulary and (C)
   the LLM never emitting non-LSR keys, on top of (A) a single-template input.
3. **Which playbooks are underrepresented?** failed_breakout_reversal (scored
   high, never picked), range_expansion, manipulation_to_distribution.
4. **Which were genuinely absent Jun 9–11?** None can be called genuinely absent
   from the *market* — they were absent from the *reconstruction input* and from
   the *routing*. trend_continuation & opening_drive were structurally vetoed
   (score 0) by the harness, not by the market.
5. **Market-data limitation?** Partly — but it's the **reconstruction** data
   (harness `mk()` template), not live market data. AB-6A inputs only encoded
   manipulation/sweep/reclaim.
6. **Reasoning limitation?** Minor. The LLM reasons coherently *within* the
   sweep/exhaustion frame; it doesn't fabricate. It simply never narrates the
   other stories because the input doesn't contain them.
7. **Prompt limitation?** Yes — the prompt lets `recommended_playbook_family`
   come back as `none`/`exhaustion`; the model defaults to LSR-flavored language
   and rarely commits to a concrete non-LSR key.
8. **Classification-framework limitation?** Yes, and **most decisive on the
   routing side**: `_PHASE_TO_PLAYBOOK` funnels manipulation/reversal/exhaustion
   (3 of 5 phases) into LSR, and `opportunity_type` was `exhaustion`/`manipulation`
   on every scan. So even a correct phase read collapses to one playbook.
9. **Most likely explanation?** **A compound artifact:** single-template
   reconstruction input (A) starves 2 playbooks to score 0 and never presents
   the others' evidence; the LLM never emits a non-LSR key (C); and the
   phase-map collapses the phases that *are* present into LSR (B). LSR is the
   only practically-reachable playbook in this configuration — independent of
   whether the live market had other setups.
10. **Evidence supporting that conclusion?**
    - Mechanical scores: `trend_continuation=0`, `opening_drive=0` on **all 17**
      probe scans; `failed_breakout_reversal=45–60` (> LSR's 15) on most.
    - Raw `playbook_family` only ever `liquidity_sweep_reversal | none |
      exhaustion`; **zero** instances of the other five keys.
    - `opportunity_type=exhaustion` on **every** directional probe scan;
      `_PHASE_TO_PLAYBOOK[exhaustion]=liquidity_sweep_reversal`.
    - Verbatim reasoning is uniformly a sweep/exhaustion-reversal story; no
      continuation/distribution/range/opening narration ever appears.
    - Direction flipped run-to-run (bullish open → bearish) while the playbook
      stayed LSR — playbook is pinned independent of the directional read.

---

## What this does NOT claim (integrity notes)
- It does **not** claim the live market only offered LSR setups — AB-6A's input
  cannot support that claim (single template).
- It does **not** claim the Brain's LLM reasoning is broken — it reasons
  coherently within what it's shown.
- A *clean* classification audit would require feeding the Brain genuinely
  varied, faithfully-reconstructed narratives (trend days, opening drives,
  range days) and/or capturing live production snapshots — **out of AB-6B
  scope, and explicitly NOT done here** (no fixes, no harness redesign).

## Deliverables
Playbook opportunity audit ✓ · alternative classification report ✓ · narrative
compression report (3 causes + quoted reasoning) ✓ · June 11 classification
review (6/6) ✓ · canonical reachability report (theory/practice/observed) ✓ ·
MAP-6B (10/10) ✓. Raw probe `data/ab6b_june11_probe.json`. No production change.
**STOP after evidence collection.**
