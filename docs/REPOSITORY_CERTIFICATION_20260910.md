# Repository contract recertification — 2026-09-10

Audited baseline: `ce95a26b0f402414cfea5db6fd845c1620504d92`, branch
`claude/optimistic-turing-bxpw5k`. The interrupted implementation left no
repository edits. This mission is certification hygiene, not a strategy change
or operational permission to trade.

## Finding and intent

Classification: **stale certification after intentional telemetry corrections,
plus a fingerprint algorithm portability defect**. No unexplained source drift
was found in the audited closure. The former expected value was reproduced,
not guessed or discarded.

| Source checkpoint | LF-source fingerprint | Former CRLF-source fingerprint |
| --- | --- | --- |
| `0f972d363caac419e0353276c1aa94bdd2b0721a` | `brain:28f76437b382b798` | `brain:255412c75252aec0` |
| `75c3a57c07932549570f7342d4313679580a0e01` | `brain:bde99d7b96c17072` | Not needed for certification |
| `b1fff438de8228fd33168a5792bc7ce5b67deb4a` through `ce95a26` | `brain:d532190cab2f3d73` | `brain:465722910c6feaa9` |

`0f972d3` introduced the old test expectation in
`tests/test_combined_safety_readiness.py`, with the objective-catalog reference
semantics repair. Its actual diff adds reference metadata to the candidate
producer and explains that metadata in the prompt; its accompanying tests prove
settled/executable reference separation and refusal after a price crossing.
The exact expected digest is obtained from that commit's 30 sources converted
to CRLF. Their committed blobs are LF. Thus the test encoded a checkout
representation, not a platform-independent contract.

Every later closure-source change, verified against the actual diffs:

1. `75c3a57c07932549570f7342d4313679580a0e01` —
   **PROD-20260908: resolve the startup risk limits instead of restating them**.
   Only `tools/topstepx_production_session.py` changed within the closure.
   Startup text resolves doctrine instead of printing stale literals. This is
   a telemetry bug fix/instrumentation change, not a strategy or risk-law
   change. The commit explicitly records the LF fingerprint transition and the
   need for fresh authorization; it deliberately leaves the already-failing
   certification test untouched.
2. `b1fff438de8228fd33168a5792bc7ce5b67deb4a` —
   **PROD-20260908: configuration is not a signed term, and neither is effective**.
   The same file distinguishes configured defaults, a verified authorization's
   signed budget, and the governor's effective cap. Missing authority is displayed
   as unresolved. Its startup call site remains unchanged. Again this is a
   telemetry bug fix, not strategy, sizing or authorization-law modification.
   Tests cover a differing signed budget, missing budget, prior realized losses,
   and authoritative-constant drift. The commit explicitly states no
   certification pin was updated.

No other commit in `0f972d3..ce95a26` changes a closure member. The other 29
files are byte-identical Git blobs across that range. Closure membership, the
hash implementation and retrieval-policy/embedding modules also remained
unchanged. In particular, the break-even repair at `ce95a26` changed **zero**
closure sources. The history therefore supports the intended current contract;
the two corrections were deliberate but had not advanced this test's pin.

## Exact closure and hashing rule

The following order is significant. Labels are hashed as UTF-8 immediately
before each file's bytes. Paths are relative to the repository root here; the
implementation resolves the first 29 under `src/` and the last under the root.

```text
prompt                  src/ai_brain/brain_prompt.py
schema                  src/ai_brain/brain_schema.py
validator               src/ai_brain/brain_validation.py
input                   src/ai_brain/brain_input.py
protected_swings        src/narrative_authority/protected_swings.py
swing_structure         src/narrative_authority/swing_structure.py
liquidity_scope         src/market_data/liquidity_scope.py
sweep_occurrence        src/market_data/sweep_occurrence.py
liquidity_engine        src/structure/liquidity_engine.py
manipulation_detector   src/structure/manipulation_detector.py
direction_vote          src/structure/direction_vote.py
session_po3             src/structure/session_po3.py
po3_config              src/structure/po3_config.py
snapshot_builder        src/market_data/snapshot_builder.py
production_scan_cycle   src/live_scan/production_scan_cycle.py
regime_features         src/regime_classification/regime_features.py
regime_classifier       src/regime_classification/regime_classifier.py
mtf_market_state        src/market_state/mtf_market_state.py
structure_flip          src/structure/structure_flip.py
candidate_producer      src/broker/luna_candidate_producer.py
risk_doctrine           src/broker/topstepx_combine_risk.py
daily_loss_budget       src/broker/daily_loss_budget.py
tool_geometry           src/toolbox/price_levels.py
tool_inventory          src/toolbox/toolbox_engine.py
history_capability      src/broker/topstepx_live_session.py
history_acquisition     src/data_feed/topstepx_provider.py
history_fitness         src/data_feed/startup_history_authority.py
continuity_law          src/data_feed/candle_continuity.py
timeframe_construction  src/data_feed/timeframe_builder.py
production_entrypoint   tools/topstepx_production_session.py
```

The only algorithm change is `source_bytes.replace(b"\r\n", b"\n")` before
hashing each textual source. The previous implementation hashed raw bytes.
No comments, arbitrary whitespace, lone carriage returns, escaped literals or
other source content are discarded. There is no AST reduction or exclusion.
Unchanged error handling contributes `<missing>` for an unreadable source.

After the sources, SHA-256 receives `retrieval` and the resolved retrieval
fingerprint as UTF-8. That fingerprint is the first 16 hexadecimal digits of
SHA-256 over the policy's sorted, compact JSON, prefixed by `retr:`. The audited
resolved value is `retr:0c241bdb8234d1ba`, with embedding manifest
`emb:302bc462381fdcfd`. Its existing failure marker remains
`retrieval<missing>`. The final result is `brain:` plus the first 16 hexadecimal
digits of the accumulated SHA-256, now **`brain:d532190cab2f3d73`**.

The hasher itself remains outside the closure to avoid a self-referential
digest. No closure membership or retrieval rule was changed.

### Authorization compatibility boundary

Authorization verification still demands exact current contract identity.
There is no legacy alias, automatic migration, re-signing or rewritten durable
authorization. Previously minted CRLF-specific or older-contract approvals
will fail closed and need fresh operator issuance before subsequent use with
this build. Already-canonical approvals for the unchanged LF contract retain
their identity. This recertification does not authorize deployment or a live
session and must not be represented as an in-session migration.

## Dependency and test harness truth

PyYAML is a runtime dependency: `run_instance.py` imports `InstanceContext`,
which imports `InstanceConfig`; its configuration load/save methods call
`yaml.safe_load` / `yaml.safe_dump`. It is not merely an incidental pytest
import. `PyYAML==6.0.3` follows the existing exact-pin convention and supports
the validation interpreter, CPython 3.14, including a Windows x86-64 wheel
([maintainer release metadata](https://pypi.org/project/PyYAML/6.0.3/)).

The existing `requirements.txt` is UTF-16LE with BOM and CRLF, preserved since
its initial repository commit. Pip successfully parsed it before this change.
That encoding and every previous pin are retained; the only textual change is
the PyYAML line. No second dependency manifest is introduced. Pytest 9.1.1 is
installed separately as the validation runner, not as a runtime dependency.

The two former grep guards search the same `src` and `tools` trees, recursively,
with case-sensitive `.py` suffixes and identifier matches. Nested symlinks are
not followed. Results retain relative path, line number and full line content;
the quarantine and `getenv`/`retrieval.py` filters and final assertions are
unchanged. Sorting and explicit UTF-8 remove platform/locale dependence.
Unreadable/missing roots now fail visibly rather than masquerading as no hits.

Regression tests cover an empty PATH and prohibited subprocess invocation,
search scope, extension case, nested sources, UTF-8/CRLF input, unchanged
forbidden conditions, all-source LF/CRLF/mixed representations, and actual
content changes under both source anchors. Existing closure mutation and
authorization-refusal tests remain in force.

## Mission boundary

No strategy, risk, entries, exits, break-even rules, candidate qualification,
model selection, call frequency, or cognition architecture is changed. Higher
model usage on a two-trade day is not evidence of inefficiency. The usage audit
remains observability only. No wake gate or model-cost optimization is part of
this certification.

## Acceptance result

Full normal-discovery run in a newly created, system-site-packages-disabled
CPython 3.14.5 virtual environment, installed with:

```text
python -m pip install --no-cache-dir -r requirements.txt pytest==9.1.1
python -m pip check
python -u -m pytest -ra --tb=short -p no:cacheprovider --basetemp <local-temp> --junitxml <local-report>
python -m compileall -q src tests tools run_instance.py vector3_june15_replay.py
git diff --check
```

`pip check`, compilation and whitespace checks all returned success. The full
suite collected **7,838 tests: 7,255 passed, 0 failed, 583 skipped, 9 warnings**,
in 735.60 seconds. No paths, `-k` filters or additional discovery exclusions were
supplied. The repository's existing prerequisite collection/skip rules were
unchanged. No Git grep was added to PATH.

The 583 skipped test identities exactly match the prior `ce95a26` run: no new
skips and no formerly skipped cases reclassified. Most require undistributed
operator evidence or credentials; existing corpus/capability prerequisites also
remain. The nine warnings are seven class-scoped fixture deprecations, one
`websockets.legacy` deprecation, and one `datetime.utcnow()` deprecation. They
are not masked or repaired in this mission.

Twenty new regression cases account for the increase from 7,818 to 7,838 tests.
The three formerly failing checks now pass for the audited reasons above.
Focused closure/certification/harness validation separately passed 210 tests
with five unchanged prerequisite skips.
