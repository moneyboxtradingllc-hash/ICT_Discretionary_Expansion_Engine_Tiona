# DECON-3 — Forensic Hardening (black-box flight recorder)

Date: 2026-07-02

If the organism acts, the persisted record now tells the whole story: what it
saw, believed, chose, what blocked it, what mutated it, what sized it, what
vetoed it, what the broker received and returned.

## Writer

`src/live_scan/snapshot_store.py::save_snapshot` — single call site
(`scan_loop.py`, after execution / stops / EOD / reconciliation / management /
rule governance have all resolved). DECON-3 makes post-runtime timing a
**contract**: save_snapshot raises `forensic write refused — runtime
incomplete` when any of `decision_authority / execution_gate /
paper_execution / position_monitor / trade_reconciliation` is absent. No
partial snapshots.

## Old gaps closed (previously NOT persisted)

adaptive_policy, adaptive_mutation, adaptive_live_authority, adaptive_block,
adaptive_confidence, adaptive_size, adaptive_live_consumption,
market_commander, rule_governance, council, regime_permissions,
thesis_lifecycle + thesis_state, position_supremacy, trade_management,
thesis_monitor, pending_entry_order, eod_authority, scar_writer, ai_shadow,
per-timeframe volatility states, structure alignment, broker payload/response,
structured block reasons, confidence/qty original→final.

## New unified truth traces (pure derivations, zero authority)

- **block_trace** — list of `{layer, reason, field}` for every veto:
  risk_governor, regime_authority, decision_authority, execution_gate (per
  failed named check), narrative_authority, council, rule_governance,
  adaptive_live_authority, position_supremacy, intent_score,
  execution_engine (carries the ops:/supremacy:/adaptive:/EOD entry denials).
  No generic "blocked". The constitutional pre-gate
  `decision_trade_authorized=False` is explicitly NOT recorded as a veto.
- **mutation_trace** — original/new confidence, original/new qty,
  mutation_types, mutation_reasoning, trade_blocked, authority_level, posture,
  plus what was actually consumed live.
- **authority_trace** — named confidence owner and qty owner with
  original → final values.
- **broker_trace** — built at the execution seam
  (`execution_engine.py`): broker_called, adapter, exact request payload
  (symbol/side/qty/type/entry/stop/decision_price/tif/bracket), raw broker
  response, error payload, latency_ms; `not_called_reason` on every path that
  never reached the broker.

## Journal symmetry fix

Submitted trade records now carry `execution_mode`, `decision_price`, and
`narrative` (previously only guard-rejected records did) — the FC-0B doctrine
audit trail survives on successful trades too.

## Tests

`tests/test_decon3_forensic_contract.py` (20 tests): post-runtime-only
refusal, symbol/decision/broker_called/order_status preservation, adaptive
policy + mutation + reasoning preservation, block-trace layer/owner/exact
reason, broker request/response/error/latency preservation, commander verdict
preservation, authority-trace values, trace builders pure on empty input.
Four older snapshot-store tests updated to model post-runtime-complete scans.

Suite: 1371 tests OK. Adaptive substrate hash-verified untouched.

No strategy added. No authority altered. Nothing promoted. Truth only.
