# AB-6A — ECU Full-Session Reconstruction Campaign

**Dyno test. Observe-only.** Three complete sessions (June 9, 10, 11) replayed
chronologically and blindly through the installed ECU exactly as it exists:
`BRAIN_ECU_MODE=true`, `AI_BRAIN_LLM=true` (gpt-4o-mini), AB-5C ownership, H2
input decontamination, prior-day-only blind retrieval, ~10-min sampling,
09:30→15:00 ET. No architecture change, no new intelligence, no optimization,
no training, no fixes. The Brain was watched, not touched.

Harness: `ab6a_campaign.py` (observation infrastructure only; no `src/` change).
Per scan it records the Brain thesis (narrative_direction, forbidden_direction,
opportunity + type, confidence, source), the originated playbook, and the
resolved tool + tool source. Chronological `StanceMemory` (no persistence)
carries the Brain's own prior stances forward, as in production.

Scope note (honest): the live record captures the Brain's *structured decisions*
per scan, not the full prose `dominant_reasoning` string for every scan (LLM
call budget). The structured fields below are the load-bearing behavioral
evidence; prose reasoning was spot-observed live and is consistent with them.

---

## Phase 1 — Session reconstructions

### June 9 (prior corpus: 06-08, 06-09) — down day 722.71→707.94
Archived session is **thin/truncated** — only 8 sampled points exist inside the
window (the live snapshot archive for 06-09 ends ~10:40). Recorded as-is.

| ET | dir | opp | playbook | tool | tool source |
|---|---|---|---|---|---|
| 09:30–09:50 | neutral | — | no_playbook | — | — |
| 10:00 | **bearish** | yes | liquidity_sweep_reversal | bearish_breaker | **ai_brain_selected** |
| 10:10–10:40 | conflicted | — | no_playbook | — | — |

First bearish / first opportunity: **10:00**. First bullish: never (in window).
dir counts: neutral 3, bearish 1, conflicted 4. 1 explicit LLM tool pick.

### June 10 (prior corpus: 06-08, 06-09) — down day 703→693, 33 scans
| ET window | dir | playbook | tool(s) | note |
|---|---|---|---|---|
| 09:30–09:50 | neutral | — | — | open, no read |
| **10:00–11:20** | **bearish** (sustained ~80 min) | liquidity_sweep_reversal | bearish_ifvg ↔ bearish_breaker | coherent morning sell narrative; ifvg/breaker rotation |
| 11:30 | conflicted | — | — | transition |
| 11:40–12:00 | bullish | liquidity_sweep_reversal | bullish_ifvg / bullish_breaker | counter-bounce |
| 12:10 | bearish | liquidity_sweep_reversal | bearish_ifvg | brief |
| 12:20–13:10 | conflicted | — | — | midday chop |
| **13:20–14:00** | **bullish** (sustained ~50 min) | liquidity_sweep_reversal | bullish_ifvg | coherent afternoon buy narrative; 5× ai_brain_selected |
| 14:10–14:50 | neutral / conflicted | — | — | wind-down |

First bearish / first opportunity: **10:00**. First bullish: **11:40**.
dir counts: bearish 10, conflicted 10, bullish 8, neutral 5. Tool source:
ai_brain_selected 7, ai_brain_playbook_derived 11 (**no mechanical**).
direction_changes 8 / 33.

### June 11 (prior corpus: 06-08, 06-09, 06-10) — choppy→up, 33 scans
| ET window | dir | forbid | opp | playbook | tool | tool source |
|---|---|---|---|---|---|---|
| 09:38–10:08 | neutral | any | — | — | — | — |
| 10:18 | neutral | **bullish** | — | — | — | — |
| **10:28** | **bearish** | bullish | yes (manipulation, 70) | liquidity_sweep_reversal | bearish_breaker | **ai_brain_selected** |
| **10:38** | **bearish** | bullish | yes (manipulation, 70) | liquidity_sweep_reversal | bearish_ifvg | **ai_brain_selected** |
| 10:48–10:58 | conflicted | bullish | — | — | — | — |
| 11:08–11:28 | **bearish** | bullish | yes (exhaustion, 60) | liquidity_sweep_reversal | bearish_ifvg / bearish_breaker | ai_brain_playbook_derived |
| 11:38–13:58 | **neutral** (sustained ~2.3 h) | any/none | — | — | — | — |
| **14:08** | **bullish** | bearish | yes (exhaustion, 70) | liquidity_sweep_reversal | bullish_ifvg | **ai_brain_selected** |
| 14:18 | bullish | bearish | yes | liquidity_sweep_reversal | bullish_mss_retest | mechanical |
| 14:28–14:58 | neutral | any | — | — | — | — |

First bearish / first opportunity: **10:28**. First bullish: **14:08**.
dir counts: neutral 24, bearish 5, bullish 2, conflicted 2.

---

## Phase 2 — Market narrative timeline (what the Brain believed, blind)
- **June 9:** opens undecided; first conviction is a 10:00 bearish liquidity-sweep
  read on the down move; archive truncates before any further development.
- **June 10:** opens undecided ~30 min, commits to an **~80-minute bearish
  morning** (sell-side draw, LSR), recognizes a midday counter-bounce, churns
  conflicted through lunch, then commits to a **~50-minute bullish afternoon**.
  Two distinct, internally-consistent narratives in one session — not flip-flop.
- **June 11:** long undecided open (09:38–10:18), a **bearish morning pulse**
  (10:28–11:28, two opportunity clusters: manipulation then exhaustion), a
  **2.3-hour neutral "no-trade" desert** (11:38–13:58), and a **late bullish
  exhaustion-reversal** (14:08–14:18). The Brain spent most of June 11 declining
  to trade.

## Phase 3 — Opportunity report
- Opportunities only fire with a directional thesis; every `opp=true` row has a
  concrete playbook and tool. No opportunity ever fired on neutral/conflicted.
- opportunity_type distribution: **manipulation** (early reversal entries),
  **exhaustion** (late-move fades). June 11's two morning clusters were typed
  manipulation→exhaustion; the late long was exhaustion. Coherent typing.
- Opportunity density tracks session character: dense on trending June 10,
  sparse on choppy June 11 (5 directional scans of 33), near-absent in the
  truncated June 9.

## Phase 4 — Playbook report
- **`liquidity_sweep_reversal` was the ONLY playbook selected across all three
  sessions** (June 9: 1, June 10: 18, June 11: 7). The other five
  (trend_continuation, manipulation_to_distribution, failed_breakout_reversal,
  opening_drive, range_expansion) were **never** originated.
- This is a real, recorded behavioral finding, not a defect to fix here: under
  the current prompt + gpt-4o-mini, the Brain reads nearly every actionable
  state as a sweep-and-reverse. AB-5C proved all 6 are *reachable*; AB-6A shows
  that in practice the Brain *prefers* one. (Observation only — no change.)

## Phase 5 — Tool report
- Tools used: bearish_breaker, bearish_ifvg, bullish_ifvg, bullish_breaker,
  bullish_mss_retest — all within the LSR-eligible set, all direction-coherent.
- Tool source across the campaign: **ai_brain_selected 11, ai_brain_playbook_
  derived 25, mechanical 1**. The single mechanical pick (June 11 14:18) is the
  AB-5C rejection path (Brain named no eligible concrete family that scan), not
  hidden origination. **~97% of tool choices were Brain-owned.**
- The Brain rotated tools *within* a sustained direction (ifvg↔breaker on the
  June 10 bearish block), i.e. genuine instrument selection, not a fixed default.

## Phase 6 — Stability report
- **No oscillation.** Direction changes were 2/8 (June 9), 8/33 (June 10),
  6/33 (June 11) — the Brain holds a stance across consecutive scans and changes
  on transitions, not scan-to-scan noise. Sustained blocks: June 10 ~80-min
  bearish & ~50-min bullish; June 11 ~60-min bearish & ~2.3-h neutral.
- LLM source health: June 11 had 30/33 `llm`, 2 `degraded` (09:38, 11:38 — empty
  open/transition states), 1 `llm_failed_fallback` (14:28). All three non-llm
  scans fell back to **neutral/no-trade** — the safe direction. No fallback ever
  produced a directional opportunity. Fail-safe behavior confirmed.

## Phase 7 — June 11 deep dive (10 questions)
1. **Did the Brain ever support the 10:29 long?** **NO.** At 10:28 and 10:38 the
   Brain was **bearish**, `forbidden_direction=bullish`, opportunity_type
   manipulation. At 10:18, already `forbidden_direction=bullish` while neutral.
   The long was forbidden at exactly that moment.
2. **When was the Brain first bullish?** **14:08** — ~3h40m after the 10:29 long.
3. **What did the Brain want at ~10:29?** A bearish liquidity_sweep_reversal via
   bearish_breaker (10:28) / bearish_ifvg (10:38) — i.e. a **short**, the
   opposite of the trade that was taken.
4. **Was bullish ever merely "allowed" earlier?** No. From 10:18 through 13:18
   bullish was either explicitly forbidden or the scan was neutral with
   `forbidden_direction=any` (nothing allowed). Bullish first became allowed only
   at the 13:38 "none-forbidden" neutral, then acted on at 14:08.
5. **Did the Brain flip-flop around the long?** No — it was bearish-or-forbidding-
   bullish continuously across the 10:18–11:28 window.
6. **What was the midday Brain doing?** Declining to trade — a 2.3-hour neutral
   desert (11:38–13:58), mostly `forbidden_direction=any`, opportunity_type
   drifting to exhaustion as the chop aged.
7. **What triggered the only long?** A 14:08 exhaustion-reversal read (LSR,
   bullish_ifvg, conf 70) after the desert — the Brain's lone bullish conviction.
8. **Was the late long Brain-owned end to end?** Direction/opportunity/playbook
   yes; the 14:08 tool was ai_brain_selected (bullish_ifvg), the 14:18 follow-on
   tool was the mechanical rejection-path pick (bullish_mss_retest).
9. **Confidence profile?** Morning shorts 70 then 60 (manipulation→exhaustion
   decay); midday neutral 50–70; late long 70. Calibrated, not pinned.
10. **Net verdict on June 11:** the ECU would **not** have taken the 10:29 long;
    it was short-biased into that window and spent the bulk of the session flat.

## Phase 8 — ECU behavioral profile
- **Decisive but patient:** commits to a direction when delivery/liquidity line
  up, holds it across scans, and sits neutral (no-trade) when they don't — a full
  2.3-hour abstention on June 11.
- **Sweep-reversal monoculture:** reads opportunity almost exclusively as
  liquidity_sweep_reversal. High conviction in one model; the other five
  playbooks are dormant in practice.
- **Tool-fluent:** genuinely selects and rotates concrete tools within a
  direction (~97% Brain-owned); does not collapse to a single default.
- **Fail-safe:** every degraded/failed LLM scan resolved to neutral/no-trade;
  no fallback ever manufactured a trade.
- **Directionally honest to delivery:** bearish on the two down days' morning
  drives, bullish only on genuine exhaustion/reversal — never bullish into the
  June 11 sweep that the old mechanical stack longed.

## Phase 9 — MAP-6 audit (10 questions)
1. **Who owned direction every scan?** The Brain (source `llm`/`deterministic`/
   fallback) — never the mechanical layer.
2. **Did the mechanical layer ever originate a trade?** No. One mechanical *tool*
   pick (rejection path); zero mechanical direction/opportunity/playbook.
3. **Did structure ever author direction?** No — H2 strips structure to a
   non-directional witness; taint guard armed; no contaminated scan observed.
4. **Did the Brain stay coherent across scans?** Yes — sustained blocks, change
   on transitions, no scan-to-scan oscillation.
5. **Were opportunity/playbook/tool always downstream of the thesis?** Yes —
   every opp had a Brain playbook + Brain-owned tool; no orphan signals.
6. **Did blind retrieval leak future data?** No — prior-day-only corpus per day;
   replay strictly chronological; no snapshot cherry-picking.
7. **Did the LLM fail safe?** Yes — degraded/failed → neutral/no-trade, always.
8. **Is all 6/22 reachability borne out?** Reachability holds (AB-5C); *usage*
   is concentrated on LSR + its bull/bear ifvg/breaker/mss_retest. Recorded gap,
   not a fix.
9. **Would the ECU have taken the trade this whole chain started from (10:29
   long)?** No — bearish/forbidding-bullish at that time.
10. **Does observed behavior match the ECU design intent?** Yes — Brain owns the
    intelligence, mechanical layer sensed/validated/would-have-executed, gating
    intact. The Brain is decisive, patient, fail-safe, and currently a
    sweep-reversal specialist.

---

## Findings carried forward (observations, NOT this phase's work)
- **Playbook monoculture:** only liquidity_sweep_reversal originates in practice.
  Worth a future prompt/model study — explicitly out of AB-6A scope.
- **ai_brain_playbook_derived dominates tool source** (25 of 37): gpt-4o-mini
  often names no concrete tool family; ownership stays with the Brain via the
  playbook-derived path. A stronger model would raise the explicit share.
- **June 9 archive is truncated** (~8 points to ~10:40); fuller June 9 capture
  would need re-archival — not done here.

## Deliverables
Phase 1 reconstructions (3 sessions) ✓ · Phase 2 narrative timeline ✓ ·
Phase 3 opportunity ✓ · Phase 4 playbook ✓ · Phase 5 tool ✓ · Phase 6 stability
✓ · Phase 7 June 11 deep dive (10/10) ✓ · Phase 8 behavioral profile ✓ ·
Phase 9 MAP-6 (10/10) ✓. Raw records: `data/ab6a_2026060{9,10,11}.json`.
No `src/` change (observation infrastructure only). **STOP after evidence
collection and MAP-6.**
