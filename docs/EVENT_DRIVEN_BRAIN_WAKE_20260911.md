# Event-Driven External Brain Wake Controller — 2026-09-11

## Deployment decision

The mechanical organism remains continuous. Only the paid external Brain may
sleep. The feature defaults to `BRAIN_WAKE_MODE=OFF`; `ENFORCE` is not approved
for live deployment by this work.

The requested PROD-20260908, PROD-20260909, and PROD-20260910 pre-provider
replay bundles are absent from this checkout. Therefore:

**HISTORICAL ACCEPTANCE NOT YET PROVEN.**

No historical call-reduction percentage is reported. Synthetic tests establish
software behavior, not historical recall or economics.

## Production call graph

The inspected production path is:

```text
tools/topstepx_production_session.py::run_production_scans
  -> broker/topstepx_production_loop.py::ProductionLoop.scan_once
     -> ProductionLoop._scan_once
        -> reconcile_missions                         continuous venue truth
        -> manage_open_position                       continuous protection / BE
        -> entry-authority-exhausted gate
        -> candle fetch, continuity repair, coherent window
        -> live_scan/production_scan_cycle.py::ProductionScanCycle.scan
           -> build_timeframes + HTF context
           -> candle continuity + history/derived revision convergence
           -> one executable quote capture
           -> market_data/snapshot_builder.py::build_snapshot
           -> sweep occurrence accounting
           -> active-path synthesis
           -> state transition + setup lifecycle
           -> shared context + council
           -> retrieval and retrieval telemetry
           -> structure-flip registry update
           -> ai_brain/narrative_brain.py::run_narrative_brain
              -> build_brain_input
              -> authorized objective/invalidation catalogs
              -> retrieval/adaptive context attachment
              -> BrainWakeController.observe          final pre-provider gate
              -> _call_llm                            existing provider path
              -> existing normalize/repair/fallback path
           -> optional two-Brain shadow only if primary cognition ran
        -> explicit brain_sleep_hold short-circuit
        -> CandidateProducer.produce                  sovereign LLM only
        -> existing daily-loss, sizing, mission, risk, and execution path
```

Everything through structure-flip update runs before the non-ECU wake decision.
Candidate production, risk sizing, mission creation, token spending, and order
submission remain after sovereign Brain cognition.

## ECU finding

`ai_brain/ecu.py::ecu_enabled` defaults `BRAIN_ECU_MODE` to false. The tracked
TopstepX production entry point does not override it, so the repository-defined
production default is ECU off. An external runtime environment can override the
value, and the legacy `launch_paper_session_fc.ps1` explicitly sets it true.

When ECU is on, `market_data/snapshot_builder.py::build_snapshot` calls
`ecu.produce_thesis`, which calls `run_narrative_brain`, before qualification,
playbook, risk, toolbox, executable-price publication, later active-path state,
setup lifecycle, retrieval, and structure-flip updates exist. Those later facts
cannot honestly be used to claim that the earlier ECU provider call was
avoidable.

The controller therefore returns `WAKE` with
`unsupported_pipeline_state:ecu_pre_provider` for every ECU observation. One
common component covers both modes safely, but only non-ECU can earn `HOLD` in
this version.

## Controller contract

`src/ai_brain/wake_controller.py` is deterministic and owns no provider, model,
direction, candidate, risk, order, or execution behavior. Its input is the
already-built snapshot and exact Brain payload at the final non-ECU pre-provider
boundary. Its structured result includes:

```json
{
  "decision": "WAKE | HOLD",
  "reasons": [],
  "mode": "OFF | AUDIT | ENFORCE",
  "semantic_fingerprint": "wake:...",
  "previous_fingerprint": "wake:...",
  "changed_dimensions": [],
  "seconds_since_last_provider_call": 0,
  "last_provider_call_scan": 0,
  "would_suppress": false,
  "provider_call_suppressed": false,
  "wake_kind": "bootstrap | event | safety | maximum_silence",
  "evidence_integrity": {"ok": true, "issues": []}
}
```

State is process-local and scoped by session, contract, and pipeline. Losing
that state produces a bootstrap `WAKE`; it does not reconstruct certainty from
disk.

## Semantic wake projection

The projection reads existing detector and catalog outputs. It does not build a
second ICT detector stack. Its dimensions are:

- session and contract identity;
- candle continuity, derived-state revision/currentness, and executable-quote
  availability/freshness;
- session/PO3 phase and manipulation category;
- setup identity and lifecycle category;
- active-path owner, forming direction, origin, load-bearing structure,
  progression, transfer evidence, and invalidation;
- exact liquidity/sweep identities and active draw;
- protected-swing identity, replacement/violation state, and ordinal sequence;
- structure-flip identities and lifecycle;
- MTF synthesis and categorical timeframe state;
- qualification status/direction;
- authorized tool membership, eligibility, and detector-owned location state;
- authorized objective and invalidation identity/validity;
- categorical regime, volatility, and expansion state;
- retrieved memory identity/authority, not prose or similarity noise.

Raw bid, ask, last trade, quote age, current price, distance-to-zone, and
penetration percentages are excluded from the semantic fingerprint. A one-tick
quote move alone does not wake cognition. Existing toolbox `price_relation` and
`entered_zone` transitions do, so a mechanically established zone crossing can
wake without inventing a competing proximity detector.

## Hard WAKE behavior

`HOLD` cannot be earned on bootstrap/reset, session or contract change,
sequence gap/reordering, non-increasing or malformed observation time, missing
or malformed required evidence, unproven candle continuity, stale derived
state, missing/stale/malformed executable quote, catalog-construction failure,
tainted/degraded Brain input, unsupported pipeline state, invalid maximum
silence configuration, previous unattempted provider request, previous
non-sovereign Brain result, controller exception, or maximum-silence expiry.

Bad evidence is never installed as the next comparison baseline. The next clean
observation bootstraps and wakes again.

## Modes and HOLD semantics

- `OFF`: does not invoke the controller and preserves the previous provider path
  and return shape.
- `AUDIT`: records what would wake or hold, but every existing provider request
  still occurs. There is no second model call.
- `ENFORCE`: an earned `HOLD` returns source `brain_sleep_hold` before `_call_llm`.
  It issues no primary request, no repair request, no Brain archive, no stance
  mutation, and no new thesis.

`brain_sleep_hold` is not neutral cognition, degraded cognition, fallback, or an
outage. `ProductionLoop` treats it as an ordinary no-new-candidate outcome,
clears any prior candidate, and returns before CandidateProducer, risk, mission,
token, or execution code. `ProductionScanCycle` also prevents a held primary
from entering optional two-Brain adjudication.

Reconciliation and deterministic open-position management run before the scan
and before this HOLD branch. Protective-stop discovery, emergency flatten,
break-even, OCO ownership, position lifecycle, EOD behavior, and future trailing
logic therefore remain outside the cognition scheduler.

## Maximum silence

`BRAIN_WAKE_MAX_SILENCE_SECONDS` is a positive finite number. The repository
template uses 300 seconds as a conservative, configurable backstop, not a final
accepted value. Replay defaults to evaluating 60, 180, 300, and 600 seconds.

The backstop uses the last counterfactual scheduled wake. In `AUDIT`, calls that
occur only because auditing cannot suppress them do not reset the hypothetical
silence clock.

## Durable accounting

Each `AUDIT` or `ENFORCE` observation attempts to append one compact row to:

```text
data/replay_sessions/<session>/memory_retrieval/brain_wake_decisions.jsonl
```

Rows contain identity, mode, decision, reasons, fingerprints, timing, actual and
counterfactual suppression, primary/repair request counts, wake kind, and
evidence-integrity status. They contain neither snapshots nor Brain payloads.
Writing is best-effort and cannot change or cancel a scan.

## Replay bundle v2

`tools/pre_brain_wake_shadow.py` retains its historical filename but now imports
and executes the production `BrainWakeController`. It neither reimplements the
projection nor calls a provider.

One JSON bundle represents one complete session:

```json
{
  "schema": "pre_brain_wake_bundle.v2",
  "session_id": "PROD-20260909",
  "evidence_kind": "recorded_pre_provider",
  "provenance_independently_verified": true,
  "expected_scan_count": 542,
  "provider_call_coverage": "complete",
  "candidate_label_coverage": "complete",
  "trade_label_coverage": "complete",
  "observations": [
    {
      "session_id": "PROD-20260909",
      "contract_id": "<exact contract id>",
      "scan_id": "<exact snapshot/scan identity>",
      "sequence": 1,
      "observed_at": "2026-09-09T13:00:00+00:00",
      "capture_stage": "pre_provider_after_catalogs",
      "pipeline_mode": "non_ecu",
      "catalogs_ok": true,
      "snapshot": {"<exact pre-provider snapshot>": "..."},
      "brain_input": {"<exact pre-provider Brain payload>": "..."}
    }
  ],
  "provider_calls": [
    {
      "session_id": "PROD-20260909",
      "contract_id": "<same exact contract id>",
      "scan_id": "<same exact scan identity>",
      "call_id": "<durable request identity>",
      "role": "primary",
      "sovereign_result": true
    },
    {
      "session_id": "PROD-20260909",
      "contract_id": "<same exact contract id>",
      "scan_id": "<same exact scan identity>",
      "call_id": "<durable repair request identity>",
      "role": "json_repair"
    }
  ],
  "candidate_origins": [
    {
      "session_id": "PROD-20260909",
      "contract_id": "<same exact contract id>",
      "scan_id": "<exact origin scan>",
      "candidate_id": "<exact candidate id>"
    }
  ],
  "trade_origins": [
    {
      "session_id": "PROD-20260909",
      "contract_id": "<same exact contract id>",
      "scan_id": "<exact candidate/trade origin scan>",
      "candidate_id": "<exact linked candidate id>",
      "trade_id": "T1",
      "opportunity_scan_ids": ["<first exact lead-in scan>", "<origin scan>"],
      "direction": "bullish",
      "quantity": 7,
      "planned_entry": 29407.5,
      "stop": 29386.5,
      "target": 29451.75
    }
  ]
}
```

Allowed repair roles are `json_repair`, `family_repair`,
`invalidation_repair`, and `other_repair`. Every observation must have exactly
one primary-call ledger row for these historical polling sessions. T1 and T2
must both appear with their known direction, quantity, entry, stop, and target.
Each trade must join to its candidate and origin scan exactly. Its explicit
`opportunity_scan_ids` must be ordered and end at the origin; timestamp
proximity is never used as a substitute.

The report includes total scans, primary and repair calls, hypothetical WAKE and
HOLD scans, longest HOLD run and duration, reason counts, candidate-origin
recall, exact trade-origin recall, T1/T2 lead-in timing, and uncertainty. An
earlier unrelated wake cannot rescue a held trade-origin scan.

Provider-call reduction is emitted only when the bundle is recorded, complete,
and independently provenance-verified. Synthetic or incomplete evidence leaves
all reduction fields null. Any trade-origin miss rejects the replay regardless
of reduction.

## Exact replay commands

From the repository root, place exported bundles at the shown paths and run:

```powershell
.\.venv\Scripts\python.exe tools\pre_brain_wake_shadow.py --session PROD-20260908 --bundle data\wake_replay\PROD-20260908.json --max-silence-seconds 60 180 300 600
.\.venv\Scripts\python.exe tools\pre_brain_wake_shadow.py --session PROD-20260909 --bundle data\wake_replay\PROD-20260909.json --max-silence-seconds 60 180 300 600
.\.venv\Scripts\python.exe tools\pre_brain_wake_shadow.py --session PROD-20260910 --bundle data\wake_replay\PROD-20260910.json --max-silence-seconds 60 180 300 600
```

Exit code 0 means a complete provenance-verified recorded replay had no origin
miss (or a no-trade day completed waste measurement). Exit code 1 means
synthetic/unverified evidence or a recall rejection. Exit code 2 means missing,
invalid, or incomplete evidence. Every report keeps
`production_authorized: false`; live authorization remains a separate explicit
deployment act.

## Remaining ENFORCE blocker

Export and independently verify all three real pre-provider bundles, run the
same-controller matrix above, and prove exact-origin recall for both September 9
trades at every candidate maximum-silence value. Until then use `OFF`, or
`AUDIT` for live counterfactual accounting. Do not enable `ENFORCE`.
