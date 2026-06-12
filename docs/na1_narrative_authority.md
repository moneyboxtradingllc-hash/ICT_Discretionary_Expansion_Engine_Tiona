# Phase NA-1 — Narrative Authority Layer

Status: IMPLEMENTED (2026-06-12). Enforced in `launch_paper_session_fc.ps1`;
code defaults are observe_only (rollback = env flip).

## What changed

The June 11 audits proved the directional narrative was monopolized by the
structure engine — which counts a swept high as a higher high — while the
AI, the delivery plane, and PO3 read the story correctly with no authority.
NA-1 inverts the hierarchy:

```
1. AI narrative        (external AI direction + confidence)      widest lens
2. Delivery            (PO3 distribution/manipulation direction)
3. Liquidity           (protected swings, draw-on-liquidity)     NEW organs
4. Structure           (witness, not king)                       demoted
```

## What this is NOT

AI does not place trades, size positions, override risk, or bypass the
gate, max trades, daily loss, stops, or Broker Supremacy. The synthesis is
deterministic code consuming AI *evidence*. The narrative layer adds one
gate check (`narrative_permits_trade`); every existing authority keeps its
jurisdiction.

## Modules

| Module | Role |
|---|---|
| `narrative_authority/protected_swings.py` | Stateful tracker: above_high raid + rejection → protected high (until close above); below_low mirror → protected low. The system's first persistent liquidity memory. |
| `narrative_authority/liquidity_objectives.py` | Draw-on-liquidity v1: direction-led draw toward the unspent pool; spent buy-side (protected high) implies sell-side objective. |
| `narrative_authority/narrative_engine.py` | Arbitration + full output schema (`narrative_direction/phase/confidence`, protected levels, draw, invalidation, allowed/forbidden directions, reasons/warnings/conflict_flags, per-lens audit record). |
| `execution_gate` | `narrative_permits_trade` check (enforce-mode only, fail-open). |
| `trade_journal` | `narrative_*_at_entry`, `protected_high/low_at_entry`, `liquidity_draw_at_entry` audit fields. |
| `snapshot_store` | persists `narrative_authority` + `protected_swings` per scan. |

## Arbitration constitution

1. **AI + Delivery agreement owns direction.** Opposing structure raises
   `structure_overruled` — a flag, not a veto. Opposite direction becomes
   `forbidden_trade_direction`.
2. **AI vs Delivery disagreement = conflicted, no trade.** Structure may
   not break the tie (the June 11 failure, verbatim).
3. **One wide lens vs opposing structure = conflicted** (downgrade, never
   a silent structure win).
4. **Wide lenses silent = witness mode**: structure direction passes
   through at confidence ≤ 40, trades stay allowed (legacy behavior — this
   is what makes observe_only rollback exact).
5. **Protected levels**: no longs into an unbroken protected high, no
   shorts into an unbroken protected low (proximity zone:
   `NARRATIVE_PROTECTED_ZONE_PCT`, default 0.30%).

## June 11 under NA-1 (replay-proven, tests T1–T10)

- 10:00 raid → protected high registered and *persisted* (the liquidity
  engine forgot it one scan later; the tracker does not).
- 10:05–10:20 → AI bearish + PO3 bearish manipulation = bearish narrative,
  `structure_overruled`, longs forbidden.
- 10:29 entry scan → AI bullish@65 vs Delivery bearish@25 =
  `ai_delivery_disagreement` → conflicted → **gate blocks the long**
  (independent of the FC-1 council/R-001 blocks).
- 11:04 below_low raid → protected low registered.
- 13:17 short with price 9¢ above the protected low →
  `short_into_protected_low` → blocked.

## Known v1 limits (honest)

- **Prior-session levels are not modeled.** The June 10 close → June 11
  open volume imbalance — the day's real draw — is invisible because the
  data plane carries no overnight reference levels. v2 scope: prior-day
  high/low/close + opening gap levels in the data feed, fed to
  `liquidity_objectives` as draw candidates.
- **Confirmation drag is reduced, not solved.** Narrative direction can
  now form from AI+Delivery minutes after a raid (e.g., bearish by ~10:05
  on June 11), but *setup generation* (qualification→playbook→toolbox)
  still follows structure bias, so the system can refuse wrong-direction
  trades long before it can construct right-direction ones. v2 scope:
  narrative-seeded playbook selection (bearish narrative instantiates the
  bearish tool set without waiting for two completed swing legs).
- AI flip-flop sensitivity: gpt-4o-mini changed direction scan-to-scan on
  June 11; the arbitration treats sub-threshold AI (< 55 conf) as silent
  rather than directional, and disagreement as conflicted (safe side).
  Fable 5 (FC-3 ladder) is the designated successor narrative AI.

## Env flags / rollback

```
NARRATIVE_AUTHORITY=observe_only|enforce      (default observe_only)
NARRATIVE_AI_MIN_CONF=55
NARRATIVE_DELIVERY_MIN_CONF=25
NARRATIVE_PROTECTED_ZONE_PCT=0.3
NARRATIVE_PROTECTED_BUFFER_PCT=0.05
```
`NARRATIVE_AUTHORITY=observe_only` restores legacy gate behavior exactly
(test T9 proves the archived June 11 snapshot re-authorizes under it).
