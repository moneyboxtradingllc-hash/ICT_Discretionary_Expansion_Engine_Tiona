# Candidate Decision Evidence

`data/replay_sessions/<SESSION_ID>/memory_retrieval/candidate_decisions.jsonl`

One record per entry proposal. Schema `candidate_decision.v1`.

## Why it exists

PROD-20260807 produced 23 propose-entry decisions and 0 candidates, and nothing
persisted said why. Establishing that the objective binding was the killer took
offline archaeology across 171 Brain artifacts, and the live qualification
object was never written at all — for that session it is gone permanently.

## The terminal-disposition law

> Every `action = propose_entry` terminates in **exactly one** machine-countable
> disposition. No proposal disappears without one.

```
CANDIDATE_CREATED            QUALIFICATION_REJECTED
OBJECTIVE_ID_MISSING         OBJECTIVE_ID_UNKNOWN        OBJECTIVE_INVALID
INVALIDATION_ID_MISSING      INVALIDATION_ID_UNKNOWN     INVALIDATION_INVALID
GEOMETRY_REJECTED            REWARD_BELOW_QUALIFICATION  RISK_REJECTED
BRAIN_UNUSABLE               WINDOW_CLOSED               STOOD_DOWN
UNCLASSIFIED
```

`terminal_disposition()` maps the producer's own reason vocabulary rather than
renaming it, so replaying old evidence still works. A reason with no mapping
becomes `UNCLASSIFIED` — it is **counted, never dropped**.

Reconciliation:

```
terra_proposals == sum(all terminal dispositions)
```

Otherwise `reconcile()` returns `CANDIDATE_DECISION_ACCOUNTING_FAILURE`. It does
not quietly balance the books.

## Fields

Identity: `schema_version`, `session_id`, `scan_id`, `timestamp_et`,
`instrument`, `contract`, `direction`, `action`, `playbook`.

Objective: `requested_objective_id`, `objective_lookup_found`,
`resolved_objective_id`, `resolved_objective_type`, `resolved_objective_price`,
`objective_side_valid`, `objective_fresh`, `objective_resolution_status`,
`objective_rejection_reason`. Invalidation carries the same nine.

Validation: `qualification_result`, `qualification_reason`,
`direction_agreement`, `playbook_authorized`, `geometry_valid`,
`geometry_reason`, `reward_risk`, `reward_risk_floor`, `reward_risk_valid`,
`risk_dollars`, `contract_count`, `risk_valid`.

Terminal: `final_disposition`, `final_rejection_reason`, `detail`.

**Every field exists on every record.** A stage that was never reached is
`None`, not missing — otherwise "died earlier" is indistinguishable from
"passed".

## Evidence is not authority

- `CandidateProducer` writes `last_decision_trace` and never reads it back.
- The recorder swallows its own failures. A failed write cannot manufacture
  permission to trade, and cannot block a scan either.
- Writing a record cannot change what the producer decides: two identical
  `produce()` calls give identical outcomes and identical traces.

No secrets, credentials, or raw account identifiers are written here.
