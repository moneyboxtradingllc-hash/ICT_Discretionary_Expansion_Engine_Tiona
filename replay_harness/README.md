# Offline replay harness — Layer A and Layer B

Scope authorised by the owner: an offline, isolated replay of recorded
decisions (Layer A) and a mission / submission / fill crosswalk (Layer B) for
the seven Combine sessions of 30 October to 10 November 2026.

This directory is the whole change. The branch was cut from the frozen commit
`5f5d4c4a2b88304bd28cdef50890bbd68e9a3f0a` and adds files here only. No
existing file is edited, moved, renamed or reformatted, and no evidence is
committed.

## What it is not

It does not call a model provider, open a venue connection, read a live quote,
place or simulate an order, run on the operator machine, or change production
source, configuration, prompts, schemas or any adaptive-learning component.
It does not rebuild market snapshots from candles (Layer C is out of scope).
A passing run is evidence for review. It authorises nothing.

## How it stays honest

| Guarantee | Mechanism |
|---|---|
| Runs the frozen logic, not a copy | `frozen.py` recomputes the git blob hash of every file under `src/` against `frozen_src_manifest.json` (341 files at the frozen commit), then imports `CandidateProducer`, `build_record`, the session-window rule and the mission state machine from that source. |
| Reads exactly the approved evidence | `evidence.py` pins the SHA-256 of the five packets, checks each one, checks every file inside against the packet's own manifest, and reads straight from the zip. |
| Offline | `guard.block_network()` makes every connect and name lookup raise. Credential-looking environment variables are dropped. |
| No lookahead | Four rules, each a gate that raises with its own name: `T_MARKET`, `T_QUOTE`, `T_ANSWER`, `T_OUTCOME`. Every recorded input of every scan is passed through the first two. The decision step is released only at the recorded answer time. Outcome files cannot be opened until the decision pass has finished and its output has been written and hashed. |
| The tests can fail | `planted.py` plants one violation per rule (plus a network attempt) beside a legal control, and alters a real model answer three ways to prove the comparison reports `DEFECT`. |
| Deterministic | Outputs carry no wall-clock time and no absolute path. `compare_runs.py` compares the hashes of two complete runs. |

## Bins

Layer A, one scan with a model answer and a decision row:

* `MATCH` — every compared field of the rebuilt decision record equals the recorded row.
* `DEFECT` — they differ and every input was present.
* `LIMITATION` — they cannot be compared because a named input is not in the record.
* `NOT_ATTEMPTED` — conditional-plan trigger rows and held rows: no snapshot was recorded.

Timeout fallbacks and the degraded record have no model answer and no decision
row. They are checked for consistency only (`CONSISTENT` / `INCONSISTENT`) and
are never counted as `MATCH`.

## Reconstructed inputs

Five inputs to the decision step are not recorded as such and are
reconstructed. They are named in the header of `layer_a.py` (A-NOW, A-WINDOW,
A-INPUT, A-LASTBAR, A-CONTRACT) so a reviewer can challenge each one.

## Running it

Python 3.12 with the frozen commit's pinned requirements (the frozen
`requirements.txt` is UTF-16):

    iconv -f UTF-16 -t UTF-8 requirements.txt | tr -d '\r' > /tmp/req.txt
    python3.12 -m venv /tmp/replay-venv && /tmp/replay-venv/bin/pip install -r /tmp/req.txt

Place the five packet zips, under their original names, in one directory:

    EVIDENCE_20261102_203550.zip   EVIDENCE_20261105_135250.zip
    EVIDENCE_20261108_173324.zip   EVIDENCE_20261109_164537.zip
    EVIDENCE_20261110_191144.zip

Then, from the repository root, with two new empty output directories outside
the repository:

    /tmp/replay-venv/bin/python replay_harness/run_replay.py --evidence-root <packets> --out <run1>
    /tmp/replay-venv/bin/python replay_harness/run_replay.py --evidence-root <packets> --out <run2>
    /tmp/replay-venv/bin/python replay_harness/compare_runs.py <run1> <run2>

Exit status 0 means integrity, populations, planted failures and both layers
are clean. Anything else is a failure and the reason is in the output files.

## Output files

| File | Content |
|---|---|
| `01_integrity.json` | Frozen-source check; packet and per-file hash check |
| `02_planted_failures.json` | Planted no-lookahead failures, network refusal, comparison controls |
| `03_layer_a_decision_pass.jsonl` | One line per Brain record: times, lookahead audit, rebuilt decision record |
| `04_populations.json` | Populations and denominators counted from the packets, per session and in total |
| `05_layer_a_comparison.jsonl` | One line per Brain record: bin or consistency verdict, differences |
| `06_layer_a_summary.json` | Layer A counts, hash of the sealed decision pass, non-matching scans |
| `07_layer_b_crosswalk.json` | Missions, submissions, fills, terminal-state checks, later-stage rows |
| `08_coverage.json` | Every population that was not replayed, and why |
| `OUTPUT_HASHES.json` | SHA-256 of every file above |

## Independent verification

A verifier should not trust any number in this directory. `populations.py`
keeps the previously reported figures only to compare against after counting;
they are never an input. The simplest independent check is to recount the
populations directly from the packets with separate code, then run the harness
and compare.
