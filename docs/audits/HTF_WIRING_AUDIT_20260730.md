# HTF WIRING AUDIT — 2026-07-30

*Mission C2a of the Context-Intelligence Era roadmap. Read-only audit: does the
HTF memory organ (HTF-MEM-1, `market_data/htf_memory_engine.py`) actually reach
the organism's judgment, on every lane? No code changed.*

## Verdict

**HALF-WIRED.** The organ is wired at the data level on the QQQ lane only, and
starved at the meaning level everywhere. Four defects found, one of them touching
every Brain measurement ever taken.

## The wiring map (verified line by line)

### QQQ live lane — data flows, meaning doesn't

```
scan_loop.py:774   htf_engine.update(candles_1m)          ✅ written every scan
scan_loop.py:804   build_snapshot(htf_context=...)         ✅ passed
snapshot_builder.py:275  snapshot["htf_memory"] = ctx      ✅ stored
brain_input.py:211  payload["htf_memory"] included         ✅ reaches the payload
narrative_brain.py:222-238  prompt addenda                 ❌ NO HTF CLAUSE
```

**Defect 1 — no prompt mandate.** `_call_llm` appends conditional system-prompt
addenda for news_context, volume_witness, adaptive_learning_context,
adaptive_friction_report, and commander mode — and nothing for `htf_memory`. The
Brain (gpt-4o-mini) receives the multi-day context as an unexplained JSON blob:
never told the field exists, what `memory_age` bounds mean, or how to weigh
`htf_bias` against intraday evidence. Every other witness organ got its clause;
this one never did.

**Defect 2 — `htf_conflict_flags` are decorative.** `snapshot_builder.py:326-334`
computes htf-vs-narrative conflict flags; repo-wide grep finds **zero readers**.
(The flags do ride inside the payload blob, but per Defect 1 they are unexplained
there too.) Computed-and-read-by-nothing — the exact pattern VOLUME-WITNESS and
WIRE-AUDIT existed to kill.

### Replay engine — HTF absent entirely

**Defect 3 — the walker never feeds HTF.** `replay_session.py:208` calls
`build_snapshot(...)` **without** `htf_context`. Therefore `snapshot["htf_memory"]`
was absent from every replayed scan — which means **every Brain measurement on
record (the 12% recorded-era sovereignty, the 40–55% live-study arms, every
ablation and lab) measured a Brain with no multi-day context.** Two consequences:
(a) those baselines are honest but describe an HTF-blind Brain; (b) no HTF repair
can be validated by replay until the walker feeds it — this is the prerequisite
for all other HTF work.

### MNQ / TopstepX era — the organ does not exist

**Defect 4 — the money venue has no multi-day memory at all.**
`data/htf_memory/` contains only `QQQ.json` — **5 daily records, frozen since
2026-07-09** (memory_age=5 caps htf_confidence at 60; the 20-day design depth has
never been reached). No MNQ file exists. The deterministic lane
(`integrations/topstepx/deterministic/`) references neither the engine nor any
prior-day concept — `facts_provider.py` has zero PDH/PDL/yesterday facts. The
20-condition author on the venue where real money will trade has no concept of
yesterday. (The lane never calls the Brain by design, so this is a mechanical-facts
gap, not payload starvation.)

### Clarification recorded

`narrative_builder.py`'s "HTF" is **15m intraday structure**, not the multi-day
memory — the mechanical narrative has never consumed HTF-MEM-1 (consistent with
its `context_only` doctrine, but worth naming so nobody assumes otherwise).

## Repair map (each one variable; ordered)

1. **HTF-REPLAY** — walker builds htf_context from archived prior-session candles
   and passes it to `build_snapshot`. Pure replay infrastructure, zero live
   impact, campaign-safe. Prerequisite for measuring everything below. Bonus:
   replay can construct *deeper* memory than live's self-accumulation (real
   archived candles = legitimate backfill under the no-synthetic-bars doctrine).
2. **HTF-PROMPT** — `HTF_MEMORY_ADDENDUM` clause, presence-gated exactly like
   `VOLUME_WITNESS_ADDENDUM` (explain memory_age bounds, bias-vs-intraday
   weighing, conflict flags). Changes live Brain judgment → validate via
   HTF-REPLAY A/B first, ship behind a launcher flag.
3. **HTF-MNQ-ACCUM** — start accumulating MNQ daily records now (passive write on
   the MNQ feed path), so memory exists when the Brain era reaches that venue.
   Campaign-safe: write-only telemetry.
4. **HTF-FLAGS** — give `htf_conflict_flags` a reader (funnel/Mission Control
   telemetry) or delete them. Decorative state is forbidden state.
5. *(Deferred to C2b/c)* Depth semantics: PWH/PWL, monthly extremes, IPDA
   20/40/60-day lookbacks, multiple candidate draws with distance + alignment.

## Standing corrections to the record

- Roadmap Part I.5 said HTF "exists, wiring unverified" — now verified: wired on
  QQQ data path, unexplained to the Brain, absent from replay and from the MNQ era.
- All existing Brain-study baselines should be read as **HTF-blind Brain**
  baselines. When HTF-PROMPT ships, its replay A/B against those baselines is the
  first measured test of whether multi-day context improves thesis quality.
