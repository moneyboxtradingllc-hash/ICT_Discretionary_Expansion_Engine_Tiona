# Stage 5 owner A/B return: completion package

This package answers CLAUDE_FAILURE_RETURN.md at evidence commit 892d9df.
Claims are labelled as follows:

- VERIFIED-RUN: executed, with the log in this package.
- VERIFIED-CODE: read from source.
- INFERRED or UNKNOWN.

Nothing here is an owner decision. Current cognition, historical archive
certification, sealed owner annotations, corpus and thresholds, Stage 4 owner
acceptance and controlled observation remain UNPROVEN or reserved.
Production is disarmed and untouched.

## 1. Identity

- **Final frozen source:** 5d18b4b41b45e7f895aa6b1d3aa1fd5966c40e03, tree
  87cbf50e354e729627748f38a16de759ab5e8cbb, on the new branch
  `engineering/stage5-ab-completion-20261020`. Every push was a fast-forward
  of a new ref; there were no resets or force-pushes. This package is
  committed in the next, docs-only commit on the same branch.
- **Parent:** the owner audit source 201c60c2bc8cb1fb8944248b4055d625edeabf5c
  (audit/stage5-ab-owner-20261020). The A/B repairs are kept byte-for-byte.
- **Received:** CLAUDE_FAILURE_RETURN.zip, 252,099 bytes, sha256 cee45d30...
  All 29 manifest entries verify. `git bundle verify` of OWNER_AB_REPAIRS.bundle
  reports the requirement c962a3d and the head 201c60c, which equals the
  remote.
- **Frozen refs, unchanged** (`identity/remote_refs.txt`):

  | Ref | Commit |
  |---|---|
  | main | a1614ae |
  | feature/latency-1-preauthorized-plans | cbfaddb |
  | review | a41c552 |
  | audit corrections | 51eb3e1 |
  | submission branch | 976d0c1 |
  | owner audit | 201c60c |
  | failure return | 892d9df |

- **Changed files vs 201c60c:**
  - src/recognition_validation/child.py
  - tests/test_recognition_child_portability.py (new)
  - docs/recognition_validation/ENGINEERING_LEDGER.md
- **Production source changed vs c962a3d: none** (VERIFIED-RUN,
  `identity/production_src_changed_vs_c962a3d.txt` is empty).
- **Ledger:** `tools/verify_engineering_ledger.py` reports LEDGER_VERIFIED at
  5d18b4b. It checks:
  - the receipt chain, with the new entry OWNER_AB_PORTABILITY_20261020 and
    receipt 2b2484e1...;
  - the 32 protected sources (unchanged);
  - the 48-file Brain/retrieval closure (unchanged);
  - the fingerprints brain:3d9878ad3ff57f1f and retr:0c241bdb8234d1ba.
- **Network requests:** 0.

## 2. Supported runtime, and the ten failures diagnosed

Runtime (VERIFIED-RUN, `identity/RUNTIME_IDENTITY.json`, `pip_freeze.txt`):

- Linux x86_64 (glibc 2.39), CPython 3.12.3, git 2.43.0.
- requirements.txt (a UTF-16 file) pins 47 packages: 47 of 47 match exactly.
  Python itself is not pinned by the repository.
- Runner: env -i allowlist, disarmed flags, proxy refused at 127.0.0.1:9,
  isolated runtime roots, no .env.

The ten failing nodes were run under the same conditions on the exact parent
and the owner source (VERIFIED-RUN, `before_after/ten_nodes_*`):

| Source | Result |
|---|---|
| c962a3d (submitted) | 10 passed, 0 failed |
| 201c60c (owner A/B) | 10 passed, 0 failed |

So all ten are host-portability failures, not A/B or strategy regressions.

The owner host is Windows 11 with Python 3.14.5, where 33 of the 47 pins
differ. The repository is Windows-operated (the `.ps1` launchers and the
UTF-16 requirements.txt), so the defect was repaired rather than declaring
Windows unsupported. There were two causes:

1. **Git not found** (VERIFIED-CODE, plus Codex's VERIFIED-RUN on Windows).
   `child_environment` built PATH as the interpreter directory plus
   `/usr/local/bin:/usr/bin:/bin`. The Windows child could not find Git, so
   `source_identity` raised FileNotFoundError, WinError 2.
2. **WinError 10106 after the Git fix** (INFERRED). The environment never
   carried SYSTEMROOT, and the child-side allowlist refuses it. Python's
   subprocess documentation requires a valid SystemRoot in an explicit
   Windows env. Without it Winsock cannot initialise and reports WinError
   10106, which matches Codex's asyncio/_overlapped failure with Git supplied.
   It was not executed on Windows here.

Reproducer (VERIFIED-RUN, `before_after/child_env_repro_*.json`,
`tools/parent_repro.py`). On c962a3d, a Windows host whose Git lives in
`C:\Program Files\Git\cmd` gets:

- a child PATH of interpreter, /usr/local/bin, /usr/bin and /bin;
- no SYSTEMROOT;
- no Git directory;
- an allowlist that refuses SYSTEMROOT.

On 5d18b4b it gets the interpreter, `C:\Windows\System32` and the Git
directory, with SYSTEMROOT set. The POSIX allowlist still refuses SYSTEMROOT.

## 3. Repair (src/recognition_validation/child.py only)

- **POSIX unchanged:** the POSIX environment and allowlist are byte-identical
  to the submission. The resolved Git directory is appended only when the OS
  directories lack it.
- **Windows additions:** `env_allowlist("nt")` admits exactly SYSTEMROOT, TEMP,
  TMP and USERPROFILE. The child carries:
  - the parent's SYSTEMROOT;
  - `%SYSTEMROOT%\System32`, in place of the Unix directories;
  - TEMP and TMP set to the scratch TMPDIR, and USERPROFILE set to the
    scratch HOME.
- **Nothing else inherited:** no credential, operator PATH, APPDATA or
  USERPROFILE value enters the child, and no SYSTEMROOT is invented when the
  parent has none.
- **Refusals unchanged:** the child-side refusals are as before. They cover
  the allowlist, credential names, the marker, preload, fresh roots, dotenv,
  source identity and the network deny.
- **Not touched:** credential access, isolation, network and refusal checks
  were neither weakened nor broadened.

## 4. Controls (tests/test_recognition_child_portability.py, VERIFIED-RUN)

- **Healthy, no POSIX regression:** in both ECU lanes the POSIX builder equals
  a transcription of the submitted builder, and the POSIX allowlist equals
  the submitted 24 names.
- **Repair:** the constructed Windows parent environment includes
  OPENAI_API_KEY, TOPSTEPX_API_KEY, APPDATA, an operator PATH and
  USERPROFILE. In both ECU lanes the child gets exactly the Windows
  allowlist, with only SYSTEMROOT inherited. A Git outside the OS
  directories is reachable on POSIX. Nothing is invented without SYSTEMROOT
  or Git.
- **Reachable consumer:** the real CLI child launch uses the builder in both
  ECU lanes. The fresh child completes, and CHILD_STATUS `env_names` equals
  the built names.
- **Activated negative control:** a SYSTEMROOT injected into a real POSIX
  child is refused with CHILD_ENV_NOT_ALLOWLISTED. The healthy control
  completes.
- **Activated mutants:** 5 of 5 killed (`portability/PORTABILITY_MUTANTS.json`):
  - SYSTEMROOT dropped;
  - Git directory dropped;
  - POSIX allowlist widened;
  - parent environment inherited;
  - Unix directories used on Windows.
- **A/B preserved:** all 29 owner audit cases pass. These are the receipt and
  manifest tampering refusals (A) and the timing diagnostic separation (B).

## 5. Focused and full suites at 5d18b4b (VERIFIED-RUN)

**Focused** (`focused/`): 132 passed, 0 failed. It covers portability,
owner_ab, contracts, rule_coverage, process_isolation, quote_wake_trigger and
scoring_cli.

**Full** (`full_suite/`): a fresh clone from the remote at 5d18b4b, one
`--collect-only`, and 12 file-disjoint shards whose union equals the
collection.

| Measure | Result |
|---|---|
| Unique cases collected | 9,694 |
| Passed | 9,111 |
| Skipped | 583 |
| Failed or errors | 0 |
| JUnit testcases | 9,694, equal to the collection |

The 9,694 cases are the original 9,659, plus Codex's 29 audit cases, plus 6
portability cases.

Against the c962a3d full run: 35 added, 0 removed, no status changes, and an
identical set of 583 skips. Skips are not passes. They are the existing
operator, archive and optional-dependency skips and exclusions, listed per
case in `full.junit.xml`. Codex's superseded 5c6962f run is not used.

## 6. Remaining limits

- **Windows not run here:** no Windows host was available, so a healthy fresh
  Windows child launch is NOT claimed. `OWNER_HOST_CHECK.md` gives the
  owner-host command. Any further Windows-only failure after SYSTEMROOT stays
  UNPROVEN until that run.
- **Python version:** the repository does not pin it. The owner host's
  Python 3.14.5, with 33 differing pins, is not the verified runtime.
- **Unchanged and reserved:** D11 to D14 (WATCHING/refusal, `.env`, wall clock,
  delivery vocabulary) and the B combined opportunity-timing
  criterion/threshold are untouched and reserved to Maurice.
- **No trading authority:** Mode A/B and fake transports do not certify
  current cognition. Nothing here confers trading authority.

## 7. Manifest

`MANIFEST_SHA256` inside the archive lists every file. The archive and its
sha256 sit next to this report.
