# LOCAL-AUTHORITY-20261026 — complete engineering return (Missions 1–3)

DISABLED BY DEFAULT · OFFLINE TEST PROFILES ONLY · NO TRADING · NOT ACTIVATED

## 1. Identity

| | |
|---|---|
| Frozen parent | `ec8197ec5411fcbcae5b25ba5a4c395f82c122cc` (tree `f28923b6b758cff123cb661600fca14dff9fd503`), brain `brain:43569c8bd11004d7`, retrieval `retr:0c241bdb8234d1ba`, closure 49 |
| Mission 1 commit | `e49cd3a0013c056d6552d3c8193843572be2d59c` (tree `a4fb6fc43730aecd9f1932872c765f621813a711`), brain `brain:920427791c12a485`, closure 50 |
| Final commit | `6e30453b70022ee66240716b72683b798ad4f523` (tree `09429e544f9514754462a1950db19e854c706228`), brain `brain:5f43a3a434eec2eb`, retrieval `retr:0c241bdb8234d1ba` (unchanged), closure 50 |
| Branch | `review/local-authority-chronology-20261026` (two commits on the parent; no merge, no main/production change) |
| Protected pins | 32 / 32 unchanged at both commits (`tools/verify_engineering_ledger.py --require-clean` → LEDGER_VERIFIED, `protected_verified: 32`) |
| Ledger | entries `LOCAL_AUTHORITY_MEMBER_ORDER_20261026` (receipt `94aca33a…`) and `LOCAL_AUTHORITY_DELIVERY_CHANGE_COMPOSITION_20261026` (receipt `c6e8cd09…`), chained |

The Mission 1 commit was frozen and verified alone before any Mission 2 work
(focused + authority/fingerprint files at `e49cd3a` in an isolated checkout:
184 passed, 1 skipped). Missions 2–3 are one coherent second commit.

Disclosed correction: the full suite at an intermediate `1356f80` found that
`tests/test_authorization_source_closure.py::MUST_BE_BOUND` (the governance list of
closure members) had not been updated when Mission 1 bound `local_authority.py`.
The entry was added (test-only, one line) and the second commit amended to
`6e30453`; `src/` is byte-identical between `1356f80` and `6e30453`. The full
suite reported below ran at `6e30453`.

## 2. Policy domain and default-off configuration

* `ProductionScanCycle(..., local_authority_profile=None)` — the default — resolves
  to `DISABLED`: no witness, no adoption, no new snapshot field, no plan binding,
  no telemetry block. Only these exact module objects enable anything:
  * `OFFLINE_TEST_PROFILE_V1` (`local_authority_offline_test/v1`): member order +
    retained support + delivery change.
  * `OFFLINE_RETAINED_SUPPORT_TEST_PROFILE_V1` (…`_retained_support_test/v1`):
    no delivery change (so the 13:15 ET case is observable — see §5.3).
  * `OFFLINE_MEMBER_ORDER_TEST_PROFILE_V1` (…`_member_order_test/v1`): Mission 1
    alone (so the 12:23 ET same-minute case stays observable after 12:24 ET).
* A string, dict, look-alike dataclass or deep copy resolves to DISABLED
  (`unrecognized_profile_disabled`). Any truthy `EXECUTION_ENABLED`,
  `ALLOW_PAPER_ORDERS`, `AUTO_EXECUTION_ENABLED`, `TOPSTEPX_ARM_ORDERS` refuses
  every offline profile (`offline_profile_refused_execution_environment`).
* Nothing outside tests references a profile object. Activation and any
  operational/session authorization remain reserved to Maurice/Codex.
* Domain: AUTHENTIC UNBOUND / D0=a only. Both new bases are excluded from scoped
  D3-B at `campaign_scope_proof` (before B1), never adopted or kept while the
  custody holds a bound or pending campaign, and a local refinement under an
  ACTIVE continuing campaign reads `unresolved` (never relabelled UNBOUND).
  Existing D3 R (native bucket time) is unchanged.

## 3. Cause / source / caller / schema map

| Concern | Producer (source) | Seal / issuer | Consumers |
|---|---|---|---|
| Member-order witness (`member_order_witness/v1`) | `local_authority.member_order_witness` from the canonical settled 1m prefix + current chronology rows | `LocalAuthority.advance` before `CampaignScopeCustody.advance`; `seal()` binds the issue to the custody publication lineage | `narrative_continuity._same_direction_successor_proof` (`authenticated_member_order`), `build_narrative_continuity` (`member_order_dependent` ⇒ current or `unresolved`), plan binding (`mof:` stable fact id) |
| Delivery change (`delivery_change_packet/v1`, family `raid_reclaim_delivery_change`, composite `DELIVERY_CHANGE_CONFIRMED`) | `delivery_change_packet` + `body_open_break` (`settled_body_open_break/v1`) over the premise inventory (5m/15m INTACT lives), canonical sweeps with immutable life association, `STRUCTURE_BREAK` rows, settled buckets | `LocalAuthority.advance` → `ActivePath.adopt_local_generation`; revalidated each cutoff (`release_local_generation` when the cited graph no longer holds); `market_proof_id` = `ldc:`digest of stable identities | `_authoritative_opposing_origin` (family-specific, requires the issued proof id), `_transfer_proof(..., snapshot)` → `local_authority_route` in the proof; Lifecycle/Draw/tool/CandidateProducer unchanged and independently necessary |
| Retained support (`retained_support_revalidation/v1`) | `retained_support_adoption` (native post-failure origin by source order or current witness, later progression, no contradiction, exact INTACT raid-associated life; latest registration, ties refused) | `ActivePath.adopt_support` (zero ladder credit, `adoption` block), revalidated each cutoff, `withdraw_adopted_support` | as above (`retained_support` route) |
| Scoped exclusion | — | — | `campaign_scope.campaign_scope_proof` returns `local_only_authority_excluded_from_scoped_d3_b` before B1 |
| Plans (`local_authority_binding`) | `local_authority.plan_binding` | — | `conditional_plan_authority.capture` (payload key only when present), `validate` (brainless trigger; reversal recheck now passes the snapshot), `validate_final_quote` (reauthenticated on the authenticated trigger snapshot — the UNBOUND `campaign_scope_binding=None` alone is not accepted) |
| Telemetry (`local_authority_route.v1`) | `local_authority.route_evidence` | — | `candidate_decision_record.participation_evidence` adds `local_authority_route` {routes, proof ids, current_source, authenticated, first_refusal} only when a local route is present |

Not changed: risk, economics, sizing, frequency, execution, Draw/Lifecycle
rules, the Brain prompt (no prompt edit was made: the composite is exposed to
the Brain only as typed facts inside `active_path_state.origin`; the packet
carries no `bias`/opinion field), retrieval, any of the 32 protected sources.

## 4. Mission 1 — constituent member order (real Friday tape)

* Default cycle (accepted parent behaviour): at 11:49 ET the native 5m parent raid
  bucket opens 11:40 and the local failure is the 1m 11:43 bar, so the successor
  refuses (native R <= D). Unchanged.
* Offline profile: the producer's witness reads the complete settled 1m members of
  the 11:40 bucket; the first strict crossing of the 29218.75 reference is the
  11:44 bar, after the failure settled (11:44). The successor is admitted with
  `order_basis=constituent_member_order_witness`; native ids/bucket times/D3 R
  unchanged; later progression and support must follow the proved crossing.
* 12:23 ET: the crossing shares the failure minute -> `NOT_ESTABLISHED`
  (`first_crossing_not_after_settled_failure`); refused. No intraminute order.
* Refusal relations each tested alone with a positive control: wrong origin/
  bucket/timeframe/failure, tampered/removed witness, gaps, duplicates, foreign
  contract, unsettled bucket/failure, opening beyond the reference; copied
  snapshot, revoked issue, stale cutoff, duplicate cutoff, cold restart
  (identical witness), history revision (retired and re-derived); constructed
  mirror both cases. Under the FULL profile the 12:24 ET delivery change
  supersedes the forming bullish hypothesis, so no bullish successor follows the
  12:23 failure (asserted). Disarmed loop, both ECU modes: default never reaches a
  candidate; offline reaches the disarmed candidate boundary at 11:57 ET after its
  own stop/reward refusals; the actual CandidateProducer refuses copied/revoked
  authority.

## 5. Mission 2 — delivery change and retained support

### 5.1 DELIVERY_CHANGE_CONFIRMED — Friday 12:24 ET (16:24 UTC open cutoff, first settled 12:25 ET)

Exact packet (`evidence/walk_delivery_change_real_1610_1650.txt`, test
`test_the_composite_is_adopted_at_the_first_settled_cutoff`):

| Element | Identity / time |
|---|---|
| Released incumbent failure | bullish 1m `PROTECTED_SWING_VIOLATED … 16:23 … low@29238.0 (swing_low:29238 registered 16:21)`, knowable 16:24 UTC |
| Earlier rejected raid | 5m `LIQUIDITY_SWEEP … 16:00` above 29294.5, association observed 16:04 |
| Retained life | 5m `swing_high:29294.5` registered 15:59 UTC (INTACT, eligible), basis buy_side_raid_rejected |
| Body-open break | 5m bullish run 15:45–15:55 (3 buckets, anchor open 29231.75, extreme 29306.0 in the 16:00 bucket); the 16:20 bucket closes 29215.25 < anchor; available 16:25 |
| Structure | 5m `STRUCTURE_BREAK … 16:24 bearish@29216.25`, source bucket 16:20, available 16:25 |
| Completion | 16:25 UTC > failure 16:24 -> adopted at the 16:24 open cutoff |
| market_proof_id | `ldc:ab91dc4625e26a0a602d05bdfd25886e35a9dc4101412c3ce490a2d1b193e96b` |

Earlier prefixes refuse (16:20–16:23: `body_open_break_superseded:new_extreme_before_break`
etc.). The adopted generation is revalidated with the SAME proof id every cutoff
16:25–16:45; a native registration replaces the adopted support at 16:45; the
leg dies natively at 16:46 (`delivery_change_ended_natively`). Whole session: the
only adoption on the real tape is 12:24 ET (`events_full_session_real.txt`).
Constructed mirror: bullish adoption at 16:24 (`events_full_session_mirror.txt`).
5m and 15m body-open-break definitions are tested both directions on constructed
buckets (positive, forming, equal close, unproved run start).

Refusal families (each changes one input of the captured live inputs, unaltered
inputs reproduce the live packet): matched retracement / no failure; failure of
the same direction; failure not settled; confirmation not after the failure;
forming bucket; equal close; wick-only; gap inside the run (`tape_gap` — a real
defect found and fixed during this work: a gap previously shortened the run and
moved the anchor); duplicate member; no / wrong-side structure; missing
association; certificate FAILED; life replaced (not eligible); same price
different life; stale registration; non-campaign timeframe (3m); changed
contract / session / revision; raid observed in the future; rolling eviction of
the run. A cited generation withdraws when its graph changes.

Composite discipline: the origin is `DELIVERY_CHANGE_CONFIRMED` / family
`raid_reclaim_delivery_change`, never a raid; the earlier raid keeps its 16:00
source time; nothing is appended to the canonical occurrence history; support
keeps its registration identity and instant with `ladder_credit: 0` and an empty
favourable ladder; later ladder rungs only from new real producer events.

Consequence to disclose: after adoption the native ActivePath continues from the
adopted state (the forming bullish hypothesis at 12:21 ET is superseded, as the
contract allows for an unconfirmed hypothesis), so offline-profile paths after
12:24 ET diverge from the default until the next native release. Default paths
never change (§7).

### 5.2 C2 adjudication

`evidence/c2_adjudication.txt` (isolated ledgers). After the C2 local failure
(03:06) the bearish native origin is the 03:00 bucket (old source time, observed
after death): the native successor rule refuses it; retained support refuses
(`origin_not_post_failure_in_source_order`); the delivery-change packet refuses
(`no_exact_current_supporting_life_and_raid`: only an intact 5m LOW exists, no
current supporting high). No scenario name or threshold is used. Separately
disclosed: under the offline profile the pre-C2 RF incumbent itself becomes a
delivery-change adoption (bullish, after its 02:21 bearish failure) — a lawful
packet under the contract — and it dies natively at 03:06.

### 5.3 Retained support — the 13:15 ET high

At 17:15 UTC (13:15 ET) a native bearish generation (1m raid 17:09 after the
bullish 17:08 failure, 1m structure 17:15) rests on nothing. The producer
revalidates the exact INTACT raid-associated 5m `swing_high:29294.5` (registered
11:59 ET — birth precedes failure and ownership) as its support, zero ladder
credit, authenticated route; withdrawn at 17:41 when the leg is contested
(`new_owner_contradiction`). Refusals: no failure, origin before failure without
witness, no later progression, contradiction, violated / replaced life, same
price different life, stale registration, missing association, ambiguous equal
registration, changed revision, foreign contract. Shown with the
`OFFLINE_RETAINED_SUPPORT_TEST_PROFILE_V1` component profile because under the full
profile the 12:24 ET adoption changes the later native path (§5.1).

Honest finding: in the disarmed loop the retained-support route produces NO
admission delta on Friday — default and offline outcomes are identical minute by
minute (the accepted native route already admits this bearish leg; candidate at
13:15 ET in both, the unchanged protected risk rule `stop_distance_above_cap`
refuses otherwise). It changes what is published and authenticated, not who
participates. A cold start at 13:00 ET replays a different native generation
already resting on the 1m 29263 high — pre-existing replay behaviour, recorded.
1m lives carry no raid association or certificate in the existing producers, so
only the certified 5m/15m lives are citable; no new certificate/watch manager
was introduced.

### 5.4 Scoped domain

* `campaign_scope_proof` returns `local_only_authority_excluded_from_scoped_d3_b`
  for both bases with a hypothetical B2/B3-passing row (labelled table/predicate
  control). Activated control: blinding only that exclusion while letting B1
  authenticate the route yields a route-B proof for both bases — proof that the
  shared B1 would otherwise expand scoped acceptance.
* With a bound campaign in custody the producer never adopts
  (`local_refinement_not_considered: campaign_scope_not_unbound`).
* Existing scoped positives/refusals are unchanged: the full suite (§9) includes
  the accepted D3 activation/transfer, suspended/unavailable, newborn Draw and
  formation-retirement tests, all passing, and the default-off projection is
  identical to the parent.

## 6. Mission 3 — whole composition, plans, final quote, telemetry

Real `ProductionLoop` (disarmed, venue writes raise), real cycle, CONTROLLED
Brain replies and CONTROLLED quotes (not natural model evidence; the archived
Friday replies were stand-down and are not represented as intent):

* Both ECU modes, real tape: default — no candidate 12:22–12:27 ET (Lifecycle
  refuses); offline — first refusal at 12:24 ET (newborn Draw named by the first
  intent), disarmed QUALIFIED candidates at 12:25/12:26/12:27 ET (decision edge
  16:26 UTC — the lab's reported point), zero orders/tokens/attempts. Brain input
  carries the typed composite (no `bias` field). Actual CandidateProducer refuses
  a copied snapshot and a revoked issue. Constructed mirror: bullish candidates.
* Conditional plan (both ECU modes): a controlled `watching` reply authors a plan at
  12:25 ET with `local_authority_binding` {routes.delivery_change ldc:…, custody
  lineage, process, contract, session, revision}; the real brainless trigger at
  12:26 ET (controlled in-zone quote, real WakeRegistry) reaches the disarmed
  candidate; the trigger candidate's evidence carries the same binding;
  `validate_final_quote` on the runner's own candidate passes; after revoking the
  issuer between trigger and final quote it refuses
  `conditional_plan_local_authority_changed` while the UNBOUND scope binding is
  unchanged. Same market facts under another custody lineage -> trigger refuses
  `conditional_plan_local_authority_changed`; current proof withdrawn -> trigger
  refuses.
* v2 telemetry: every decision record that saw a local route carries
  `local_authority_route.v1` {routes + proof ids, current_source (cutoff, revision,
  contract, session, process), authenticated, first_refusal {code,
  observed_gate_reason}}; refused records name `campaign_lifecycle_refused`
  first; created candidates carry `first_refusal: null`; default records carry no
  block. Missing evidence stays UNKNOWN.

Two harness defects fixed (tests only): the loop harness authorized the
non-production window `09:30-16:00` (production is `09:00-14:00
America/New_York`), which made plan capture refuse; and the harness now arms the
real WakeRegistry and, like `scan_once`, makes no Brain call while a plan is
armed.

## 7. Default-off invariance against the parent

`default_off/` — a DEFAULT cycle (no profile argument; the parent has none)
walks the whole Friday tape (509 settled cutoffs, 09:30–17:58 UTC) on the parent
`ec8197e` and on `6e30453`, digesting 10 decision-bearing surfaces per cutoff
(active path, premise shadow, premise catalog, scope custody + shadow,
Lifecycle, protected swings, formation view, derived state, narrative
continuity). Only the random per-process custody lineage, the ids/digests
derived from it, and the catalog row order those ids impose are normalised.

| Comparison | real tape | constructed mirror |
|---|---|---|
| parent vs final | 0 differences / 509 cutoffs | 0 / 509 |
| parent vs parent (control) | 0 / 509 | 0 / 509 |

Before row-order normalisation the parent differed from ITSELF in the same way,
so that ordering is pre-existing nondeterminism, not a change. Default records,
plans and snapshots carry no new key.

## 8. Activated break-one-invariant mutants

`mutants/` — each copies the frozen tree, applies ONE source edit and runs the
named tests (must turn red). 15/15 killed:

M01 profile accepts look-alike · M02 route ignores the current issue · M03
incumbency launders a revoked route · M04 no scoped exclusion · M05 adopts beside
a bound campaign · M06 unproved body-run start · M07 gap inside the run ignored ·
M08 confirmation before failure admitted · M09 ladder credit inherited · M10
adopted generation not revalidated · M11 retained support ignores contradiction ·
M12 plan trigger skips the local binding · M13 final quote trusts the UNBOUND
scope · M14 telemetry omits the route · M15 same-minute member order admitted.

Disclosed: M10's first formulation (`if False:`) SURVIVED pass 1 because it
crashed into the fail-closed revocation path, which still refused. It was
restated as "keep the cited generation without revalidation"; that mutant is
KILLED (the brainless trigger then reached a candidate after the proof was
withdrawn). Both results are in `mutants/`. Mutants ran on `1356f80`, whose `src/`
is byte-identical to `6e30453`.

## 9. Complete isolated offline suite at the final SHA

Fresh clone at `6e30453`; credential-free isolated runtime roots (`env -i`,
HOME/ledger/brain/retrieval/replay dirs in a fresh temp root, sockets to a
sinkhole proxy, execution switches false); one `--collect-only`, 16
file-disjoint shards, 4 workers (`suite/shard_suite.py`, `suite/merge_shards.py`,
`suite/run.sh`).

| | |
|---|---|
| Collected | 9,976 tests in 364 files (`suite/collect.txt`) |
| JUnit test cases | 9,976 unique = collection (files equal, shards disjoint; `suite/union.json`) |
| Passed / skipped / errors | 9,391 / 583 / 0 |
| Failed in the concurrent run | 2 — `test_latency1_final_quote_zone.py::test_verified_conditional_final_quote_inside_inclusive_zone_reaches_mint[inside]` and `[upper_edge]` (shard 00) |

The two failures raised `session_authorization_invalid:AuthorizationRefused` at
plan capture during the 4-worker run. Rerun ONCE, the identical shard-00 file
list passes in isolation at `6e30453` (540 passed, 84 skipped) and at the parent
`ec8197e` (540 passed, 84 skipped); the file alone passes on both (16/16). No code
was changed for this. I could not prove the concurrent cause from the captured
output (the refusal text is swallowed); it is reported as an unexplained
concurrent-only failure, not as a flake, and all four rerun logs are in `suite/`.
Skips are the repository's own platform/optional-dependency skips (listed per
test in the JUnit files).

## 10. Measured fingerprints and protected checks

| | parent `ec8197e` | `e49cd3a` | final `6e30453` |
|---|---|---|---|
| Brain | `brain:43569c8bd11004d7` | `brain:920427791c12a485` | `brain:5f43a3a434eec2eb` |
| Retrieval | `retr:0c241bdb8234d1ba` | unchanged | unchanged |
| Closure | 49 | 50 (+ `market_data/local_authority.py`) | 50 |
| Protected | 32 | 32 unchanged | 32 unchanged |

The seven literal expectations (3 recognition-validation examples, 4 tests), the
closure-count literal and the closure governance list are updated. Prior
session/authorization is not reusable after these fingerprint changes.

## 11. Remaining owner-dependent limits (accurate, not blockers to this engineering)

* Activation is reserved. Nothing references an offline profile outside tests;
  enabling a route for any operator session, and any subsequent operational /
  session authorization, is Maurice/Codex's decision.
* The doctrine itself (earlier-raid / later-delivery-change family, retained
  support semantics, the body-open-break fact contract) is implemented as the
  proposed, versioned contract; it is not ratified trading policy here.
* No prompt edit: the Brain sees the composite only as typed facts. Whether a
  narrow prompt description is wanted is an owner choice.
* Controlled replies and quotes prove wiring and admission only — no natural
  recognition, intent, fill or performance claim. The archived Friday replies
  were all stand-down.
* Retained support shows no admission delta on Friday (§5.3); only certified
  5m/15m lives are citable (1m lives carry no association/certificate today).
* A restart re-derives the composite at the first live cutoff with no ladder
  credit; a same-SHA cold start at a different minute can replay a different
  native generation (pre-existing).
* No paid/model/provider/venue call, pricing, credentials, risk/economics/
  management change, merge, deployment, rebind, arming or order occurred.
