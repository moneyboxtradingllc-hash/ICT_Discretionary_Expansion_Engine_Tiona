# CLAUDE.md

Guidance for Claude Code (and any engineer) working in this repository.
Read this first, then `docs/PROJECT_CONTEXT.md` for the full picture.

## What this repo is

An automated **MNQ (Micro E-mini Nasdaq-100) futures bot** that trades a
**TopstepX / ProjectX** account (practice, then Combine). Two lanes share one
codebase (details in `docs/PROJECT_CONTEXT.md`):

1. **Production Brain lane** — mechanical organism + an external LLM "Brain"
   (production model `gpt-6-luna`) that owns direction. Entry point:
   `tools/topstepx_production_session.py`.
2. **Deterministic lane** — brain-off, rules only, no LLM. Entry point:
   `launch_topstepx_mnq_deterministic.sh` → `integrations.topstepx.deterministic.loop`.

Roles: **Tiona (Nas)** is the operator who runs sessions. **Maurice** is the
architect who issues written rulings that govern doctrine and risk. Do not
invent doctrine; if a rule is unclear, say so and ask.

## Non-negotiables

1. **Orders stay disarmed unless explicitly authorized.** `TOPSTEPX_ARM_ORDERS`
   defaults to false and the launcher pins it false. Arming requires a durable,
   account-bound session authorization (`src/broker/topstepx_session_authorization.py`),
   not a flag. Never weaken this, never auto-arm, never add a "just this once" path.
2. **Risk constants have one owner each; change them only on a written ruling.**
   Production lane: `src/broker/topstepx_combine_risk.py` (preferred stop 35 pt,
   absolute stop 50 pt, max 15 contracts, max $350 risk) and
   `src/broker/topstepx_session_authorization.py` (daily loss budget $725,
   2 trades/session, 1 attempt per trade mission, window 09:00–14:00 ET).
   Guards compare against the owner module — never copy a literal.
3. **Brain contract fingerprint.** 30 source files are hashed into
   `brain:<16 hex>` (`_CONTRACT_SOURCES`, `src/ai_brain/production_model.py:164`).
   Editing any of them changes the fingerprint and **invalidates existing session
   authorizations** (they fail closed and must be re-issued by the operator).
   If you touch one, say so in the commit message with the old and new value.
   Last recorded value: `brain:3a09895222765f22` (commit `49550b5`).
4. **Production model is single-authority**: `src/ai_brain/production_model.py`.
   No aliases, no silent fallback model. A response served by a different model
   fails closed (`provider_model_mismatch`).
5. **Fail closed, never silent.** "No" and "cannot tell" are different answers and
   must stay different (e.g. `BUDGET_EXHAUSTED` vs `GOVERNOR_UNPROVEN`). Every
   dropped candidate needs a recorded reason. Missing evidence is never read as
   "calm" or "empty".
6. **Secrets.** `.env` is gitignored; only `.env.template` (placeholders) is
   committed. The TopstepX username and API key are credentials. Use
   `src/broker/topstepx_redaction.py`; never print them or commit them.
7. **Never skip, disable, or quarantine a test to get green.**

## Run and test

- **Python 3.12+ is required.** The source uses PEP 701 f-string syntax; Python
  3.11 fails at import (`luna_candidate_producer.py`, `SyntaxError`). The repo was
  certified on CPython 3.14.5 and verified here on 3.13.
- `requirements.txt` is **UTF-16LE with CRLF** (exact pins). Preserve that encoding
  when editing it; don't "fix" it to UTF-8.
- Tests (from repo root, no `PYTHONPATH` needed):
  `python -m pytest -q -p no:cacheprovider`
  Focused example: `python -m pytest -q tests/test_production_brain_model.py`.
  The full suite takes on the order of 10–15 minutes. About 580 tests skip because
  they need operator evidence or credentials — that is expected.
- Deterministic lane (orders disarmed by default): `./launch_topstepx_mnq_deterministic.sh`
  (macOS/Linux) or `launch_topstepx_mnq_deterministic.ps1` (Windows). Needs a
  `.env` copied from `.env.template`.
- Production lane, read-only proof (no orders): `python tools/topstepx_production_session.py --proof`.
  Arming: `--arm --mission-id <id>` **and** a valid authorization
  (`tools/topstepx_issue_session_authorization.py`, `tools/verify_authorization.py`).

## Conventions

- **Commit messages**: `MISSION-NAME: what changed`, then a body that explains the
  *defect and why*, states what did **not** change (strategy, risk, sizing,
  execution…), reports the Brain fingerprint (changed/unchanged), and gives test
  counts (focused + full suite).
- **Tests model produced shapes.** A fixture that agrees with a buggy validator
  proves nothing (`ed810ec`: 7,464 green tests, a gate that could not gate).
- **Evidence over claims.** Don't state edge, profitability, or "model X is better"
  from replay or small samples. See `docs/model_selection_doctrine.md`.
- **Observe-only first.** New intelligence layers ship as `observe_only` /
  `brain_input=False` until a ruling promotes them (e.g. `src/news/factual`).
- New design/mission docs go in `docs/`, named by mission.
- Line endings: the contract hash normalizes CRLF→LF; commit LF.

## Repo map

| Path | What |
|---|---|
| `src/broker/` | TopstepX client/adapter, production loop, execution runner, risk, protection (break-even, trailing), authorization, mission state/recovery |
| `src/ai_brain/` | Brain prompt/schema/validation, production model authority, wake controller, ECU, two-brain shadow |
| `src/integrations/topstepx/deterministic/` | Brain-off deterministic lane (loop, author, risk, session, funnel) |
| `src/structure/`, `src/market_state/`, `src/narrative_authority/`, `src/regime_*` | ICT structure, liquidity, PO3, order blocks, swings, regime (observe-only) |
| `src/toolbox/`, `src/playbooks/` | Tool library, price levels, playbook classification |
| `src/news/` | NEWS-1 layer (off by default) and `news/factual` (NEWS-2, observe-only) |
| `src/risk/`, `src/execution_gate/`, `src/decision_authority/` | Risk governor, Topstep limits, gate, decision engine |
| `tools/` | Operator tools: session runner, authorization, audits, postmortems, replay |
| `tests/` | ~320 test files; certification tests pin the Brain fingerprint |
| `docs/` | ~70 mission/audit/doctrine docs (index in `docs/PROJECT_CONTEXT.md`) |

## Where to look next

- `docs/PROJECT_CONTEXT.md` — architecture, doctrine, history, current state, open items.
- `docs/REPOSITORY_CERTIFICATION_20260910.md` — exact Brain-contract closure + hashing rule.
- `docs/EVENT_DRIVEN_BRAIN_WAKE_20260911.md` — wake controller (OFF / AUDIT / ENFORCE).
- `docs/model_selection_doctrine.md` — why model choice is decided live, not by replay.
- `docs/topstepx_integration.md` — venue facts, account pinning, read-only preflight.
- `git log` — commit bodies are unusually detailed and are the best record of *why*.
