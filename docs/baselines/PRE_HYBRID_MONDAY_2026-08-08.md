# Baseline — Pre-Hybrid Monday, 2026-08-08

**Known-good production baseline before the two-Brain hybrid authority
experiment.** This is the rollback point.

```
git switch baseline/pre-hybrid-monday-2026-08-08
```

| | |
|---|---|
| Known-good production code commit | `b9e000e` |
| Baseline tag | `pre-hybrid-monday-2026-08-08` |
| Rollback branch | `baseline/pre-hybrid-monday-2026-08-08` |
| Experiment branch | `experiment/two-brain-hybrid` |
| Production authority | **UNCHANGED** |

---

## What this baseline IS

The exact production wiring prepared for Monday, with the external Brain
authoritative and every current authority law intact:

- deterministic/mechanical architecture as it stands (present, and **not**
  production-reachable — see below)
- external-AI production architecture, `gpt-5.6-terra`
- canonical objective / invalidation bridge, ids required for propose-entry
- `CandidateProducer` validation chain and its authority laws
- **`wrong_model` and `fallback_not_authoritative` still enforced**
- qualification, risk and sizing doctrine unchanged
- TopstepX execution path unchanged
- memory / retrieval at v2.2, `CONTEXT_ONLY`
- session lifecycle and closure classes unchanged
- `raw_snapshot` observational archiving (the last change before the freeze)

## What this baseline is NOT

It contains **none** of the hybrid work:

- no hybrid production authority
- no deterministic-author promotion
- no Terra material-reject veto
- no strict-congruence authority
- no two-Brain execution routing

The two-Brain experiments that produced this decision were **research only** —
scratchpad harnesses, never committed, never wired to production.

---

## Runtime doctrine fingerprint

Code-owned constants (the authority; `.env` cannot raise these):

| Setting | Value |
|---|---|
| `PRODUCTION_MODEL` | `gpt-5.6-terra` |
| Brain contract fingerprint | `brain:b942f2e94c2ec41c` |
| `PRODUCTION_MAX_RISK_USD` | 250.00 |
| `PRODUCTION_MAX_CONTRACTS` | 15 |
| `PREFERRED_MAX_STOP_POINTS` | 35.0 |
| `ABSOLUTE_MAX_STOP_POINTS` | 40.0 |
| `MIN_QUALIFICATION_R` | 1.5 |
| `allow_prose_objective_fallback` | **False** |
| Embedding | `descriptive.embedding.v2.2` / 58d / `emb:d432f37dfdd816cd` |
| Descriptive schema | `descriptive.v2.2` |
| `MAX_ANALOGS` / per-session / min-similarity | 5 / 2 / 0.6 |
| Retrieval authority | `CONTEXT_ONLY` |
| `regime_authority_mode()` | `observe_only` |

Environment doctrine (non-secret values recorded; secrets recorded only as
present/absent):

| Setting | Value |
|---|---|
| `AI_BRAIN_ENABLED` | `true` |
| `AI_BRAIN_MODEL` | `gpt-5.6-terra` |
| `BRAIN_JSON_MODE` | `on` |
| `AI_RETRIEVAL_ENABLED` | `true` |
| `EXECUTION_ENABLED` | `true` |
| `MAX_TRADES_PER_DAY` | 2 |
| `RISK_PER_TRADE_DOLLARS` | 500 |
| `DAILY_LOSS_LIMIT_DOLLARS` | 500 |
| `NT_INSTRUMENT` | `MNQ SEP26` |
| `OPENAI_API_KEY` | `<PRESENT>` |
| `TOPSTEPX_API_KEY` | `<PRESENT>` |
| `TOPSTEPX_USERNAME` | `<PRESENT>` |
| `TOPSTEPX_ACCOUNT_ID` | `<PRESENT>` |
| `TOPSTEPX_ACCOUNT_FINGERPRINT` | `<PRESENT>` |

No key, token, password, account identifier or authorization secret is recorded
here in any form.

### Two notes worth carrying forward

**`.env` risk values are not the production ceiling.** `RISK_PER_TRADE_DOLLARS`
and `DAILY_LOSS_LIMIT_DOLLARS` are `500`, but MNQ production is bounded by the
code-owned `PRODUCTION_MAX_RISK_USD = 250.00`. Code wins. The `500` values, and
the `PAPER_ACTIVATION_*` / `PAPER_ACTIVATION_SYMBOL=QQQ` block still present in
`.env`, are residue from the retired QQQ paper lane under the TopstepX-only
doctrine. Recorded as observed, not corrected in this freeze.

**The production window** is not an `.env` setting at this baseline; the
09:30–14:00 America/New_York window is applied by the production path.

---

## State of the two brains at this baseline

| | |
|---|---|
| Deterministic author | **PRESENT** — `narrative_brain._deterministic()`, independently invokable, measured at 72 directional proposals over 400 archived snapshots, 0 errors |
| Production reachability | **BLOCKED** — a deterministic thesis carries no `model`, so `_check_brain` raises `wrong_model` |
| Terra | authoritative author for every production candidate |

That block is **current doctrine, deliberately preserved in this baseline.** The
hybrid experiment exists to decide whether it should change — not to route
around it.

---

## Rollback

If the hybrid experiment fails, return to the exact Monday-ready system:

```
git switch baseline/pre-hybrid-monday-2026-08-08
```

No reconstruction, no undoing individual changes. If the hybrid succeeds, it is
promoted deliberately from `experiment/two-brain-hybrid` — this baseline is
never overwritten either way.
