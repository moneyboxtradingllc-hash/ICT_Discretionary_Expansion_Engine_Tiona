# PROD-20260807 — Session Report

**Sealed 2026-08-07.** First production session with GPT-5.6 Terra and durable
descriptive memory. It placed no orders and it is the most valuable session the
project has produced, because it broke in four places at once and left enough
evidence to prove each one.

---

## 1. Identity

| | |
|---|---|
| Session | `PROD-20260807` · MNQ · `CON.F.US.MNQ.U26` |
| **Runtime HEAD** | **`d167b20`** — the commit that actually ran |
| Post-session repair HEADs | `bd19660`, `f19cf97`, `a9329b5`, `8f5fb46` |
| Model | `gpt-5.6-terra` |
| Brain contract live | `brain:a99e936b00dea7b0` |
| Brain contract now | `brain:b942f2e94c2ec41c` |
| Window | 09:30 – 14:00 ET |
| Account | fingerprint only — no raw account id appears in this archive |

The runtime HEAD is recorded separately from every repair. A fix is never
allowed to be recorded as the thing that ran; the archive keeps the runtime
truth even where that truth is a defect.

## 2. What happened

| | |
|---|---|
| Scan span (wall clock ET) | **09:30:51 → 13:11:17** |
| Scans | 171 |
| Brain artifacts | 171 |
| Retrieval telemetry records | 171 |
| Terra direction | bearish 84 · conflicted 58 · bullish 19 · neutral 10 |
| Terra action | stand_down 146 · **propose_entry 23** · wait 2 |
| Bot candidates / attempts / orders / fills / round trips | **0 / 0 / 0 / 0 / 0** |
| Final positions / working orders | 0 / 0 |

Terra was not refusing to trade. It proposed 23 entries and produced 0
candidates.

### Timestamp semantics — no scan gap

Four different clocks were being confused. They mean different things:

| | |
|---|---|
| Last Brain artifact, wall clock (filename) | **13:11:17 ET** |
| Last Brain artifact, market-data timestamp | 13:09:00 ET (last closed bar) |
| Last retrieval telemetry | 13:10:56 ET |
| Launcher termination | ≈13:11 ET |

**`NORMAL MARKET-DATA TIMESTAMP SEMANTICS` — no scan gap.** 171 scans, median
interval 78 s, **zero gaps over 180 s**, and telemetry is 1:1 with Brain
artifacts (171 = 171). A market-data timestamp trails its wall clock because it
names the last *closed* bar.

The previously reported end of `12:42:50` was a mid-session reading taken while
the session was still running; 23 further scans followed it. The evidenced span
is 09:30:51 → 13:11:17 ET, and no proposed memory segment may fall outside it.

## 3. The four defects

**1 — Prose objective binding.** The join between what Terra chose and what the
engine knew was English. `classify_draw()` returned `None` on 17 of 23
proposals. Worse, at 09:47:03 Terra named 29493.25; prose classification reduced
that to a *kind*, side-filtering left one survivor, and the engine bound
29452.50 — a different level, directionally valid, and therefore silent.
Accidental correctness is not correctness. Repaired by `f19cf97`.

**2 — Retrieval liquidity shape.** Retrieval read timeframe-keyed pools while
the snapshot published a flattened structure, so every scan saw `no_pools`. The
market had two-sided pools on 142 of 151 scans. Result: 1237 contradiction-gated
records and 2 analogs surfaced across the entire session.

**3 — Delivery vocabulary.** Taken from `po3_engine._po3_alignment` instead of
the authoritative `shared_market_context._delivery`. 30 scans carried a state
the v2.1 vocabulary did not contain. Repaired by the v2.2 migration (`a9329b5`).

**4 — Telemetry scoping.** `ProductionLoop` never passed `session_id`, so all
171 telemetry records landed under `UNSCOPED/`. Repaired by `bd19660`.

A fifth, found while sealing: a blank `REGIME_AUTHORITY_MODE=` resolved to
`enforce`. Blank now means unset.

## 4. Retrieval — read this before citing any number below

> **August 7 retrieval behaviour occurred under the PRE-REPAIR adapter and the
> v2.1 vector space. It is not evidence about the repaired v2.2 system.**

| | |
|---|---|
| Retrieval enabled | 171 / 171 scans |
| Queries scored | 125 |
| Queries refused (missing mandatory block) | 46 |
| Mean query completeness | 0.9522 |
| Contradiction-gated records | 1237 |
| **Analogs presented** | **2** |
| Stage accounting reconciled | 171 / 171 |
| Authority | `CONTEXT_ONLY` throughout |

## 5. Balance attribution

Two questions, answered separately — an unexplained dollar figure must not cast
doubt on a clean bot record.

**Bot attribution: `BOT_ACTIVITY_ABSENT`.** 0 bot-generated order ids, 0 bot
fills. Every order and fill in the window is untagged and therefore not the
bot's. Proven from venue records via `Trade.orderId → Order.id`, because this
venue does not carry `customTag` on trade records.

**Balance change: `BALANCE_CHANGE_ATTRIBUTION_UNRESOLVED`.** The reported
$50,042.96 → $50,029.66 (−$13.30) does not match any prefix of the venue trade
sequence (nearest cumulative points −1.80, +3.90, +2.10), and manual trading did
not begin until 12:54 ET — after the reading was taken. The account also
continued moving afterwards, so the two remembered figures do not bracket a
closed set of records. Not asserted as manual merely because manual trading was
reported.

## 6. Fact parity

**14 required facts × 4 representative windows = 56 fact observations** (early
bearish move, reversal, mid-morning rally, later bearish move). An earlier draft
of this report said "56 facts × 4 windows", which would imply 224 observations
and was wrong.

| Status | Count |
|---|---|
| `PARITY` | 40 |
| `INTENTIONAL_DIFFERENCE` | 8 |
| `DEFECT` | 8 — all the missing objective/invalidation catalogs, repaired by `f19cf97` |
| **Outstanding** | **0** |

`INTENTIONAL_DIFFERENCE` covers market regime (observe_only, reaches Terra as
narrative not as a gate) and volatility (consumed by the deterministic
qualification lane).

**Objective catalog parity: PASS** on all four windows — the catalog published
to Terra is identity-equal to `enumerate_objectives()`, every entry carries an
id and a source, enumeration is stable, and every invalidation carries an id.
One canonical objective universe.

## 7. Qualification — a permanent limitation

**LIVE QUALIFICATION: NOT FULLY RECONSTRUCTABLE.** `candidate_decisions.jsonl`
did not exist during this session. Where qualification was not persisted it is
gone, and no later schema can recover it.

Replay through the canonical bridge:

```
Terra proposals                     23
old prose binding                    2
canonical-ID binding                 8
recovered solely by binding          6
```

These 8 are **QUALIFICATION-CONDITIONAL REPLAY CANDIDATES**. They are not missed
trades, not would-have-traded setups, and not winning trades. Live qualification
is not exercised in this replay.

## 8. Archive

| | |
|---|---|
| Path | `data/replay_sessions/PROD-20260807/` |
| Files | 179 |
| Bytes | 12,528,205 |
| Manifest SHA-256 | `118c926f0bf68652d7fb1eff2feaaeddc4ca3cdaa277e5610d44d956aeb33724` |
| Integrity | **PASS** |
| Classification | **`INTEGRITY_SEALED`** |

**Not `STRONGLY_IMMUTABLE`.** Every file verifies against a manifest, so silent
corruption is detectable — but `tools/seal_session_archive.py --reseal` can
deliberately delete and regenerate that manifest, and it re-copies the Brain
artifacts from `data/ai_brain/`. The seal is therefore replaceable by an
explicit operator action. It is not append-only and it is not cryptographically
immutable. Nothing can overwrite the evidence *silently*, which is why the
archive system is not being redesigned here — but the word "immutable" should
not be used for it.

Contents: 171 Brain artifacts (byte-for-byte), 171 retrieval telemetry records,
`PROVENANCE.json`, `CANDIDATE_DECISIONS_PROVENANCE.json`,
`runtime_identity.json`, `session_ledger.json`, `fact_parity.json`,
`activity_reconciliation.json`, `SHA256SUMS.txt`, `manifest.json`.

**Provenance.** Telemetry was recovered from `UNSCOPED/`; the archive records
that original location and does **not** backfill the blank `contract` field. A
recovered session association is not an original value. Membership was proven
per record from its own `scan_id`/`timestamp_et` — 171 adopted, 0 left behind.

**Not adopted.** `UNSCOPED/candidate_decisions.jsonl` holds rows with scan ids
`snap-N` and market timestamps of 2026-08-06, written by the post-session
offline replay of the August 6 archive. Sharing a directory is not evidence of
belonging to a session; 0 adopted.

## 9. Memory

`PROD-20260807 MEMORY: HELD.` No descriptive memory was authored from this
session. The live corpus remains 10 records, all `PROD-20260806`, all
`descriptive.embedding.v2.2` / 58d / `CONTEXT_ONLY`, 0 `outcome_validated`.

The evidence had to be sealed first, and the repaired normalisers and Brain
contract reviewed independently of the faulty live retrieval lane. The next step
is a fresh August 7 descriptive-memory **dry run** under the corrected v2.2
normalisers, compared against this immutable raw market evidence — after which
it can be decided whether those records deserve to enter memory.
