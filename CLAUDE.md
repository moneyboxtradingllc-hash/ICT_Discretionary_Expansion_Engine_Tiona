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

## Which code is live — check before touching code

*As of 2026-10-02 (after PROD-20261002).*

| | Branch | Commit | Brain fingerprint |
|---|---|---|---|
| **Production (deployed, authorized)** | `feature/latency-1-preauthorized-plans` | `cbfaddb` (LATENCY-1) | `brain:0ec4ef07c75dbcef` |
| This docs branch | `claude/admiring-darwin-9ninpx` | NEWS-2 `95170d8` + docs | `brain:3a09895222765f22` |
| `main` | `main` | `a1614ae` (2026-09-03) | stale; not used for production |

- Production and this branch **split at `49550b5`**. Production has Session-PO3
  demotion, final-quote economics and LATENCY-1. It does **not** have NEWS-2
  (`95170d8`). This branch has NEWS-2 and these docs, but not the production code.
- **Code work starts from the production branch**, not from this docs branch.
- Maurice authorizes an **exact SHA + model + fingerprint + session date**. Any
  code, config, model, fingerprint, account or contract change voids that and
  needs fresh review. Open defects waiting on his rulings: `docs/PROJECT_CONTEXT.md` §12.

## Non-negotiables

1. **Orders stay disarmed unless explicitly authorized.** `TOPSTEPX_ARM_ORDERS`
   defaults to false and the launcher pins it false. Arming requires a durable,
   account-bound session authorization (`src/broker/topstepx_session_authorization.py`),
   not a flag. Never weaken this, never auto-arm, never add a "just this once" path.
   A 24/24 `--final` preflight makes a session *eligible* to arm; arming itself is a
   separate, explicit ARM / GO from Maurice.
2. **Risk constants have one owner each; change them only on a written ruling.**
   Production lane: `src/broker/topstepx_combine_risk.py` (preferred stop 35 pt,
   absolute stop 50 pt, max 15 contracts, max $350 risk) and
   `src/broker/topstepx_session_authorization.py` (daily loss budget $725,
   2 trades/session, 1 attempt per trade mission, window 09:00–14:00 ET).
   Guards compare against the owner module — never copy a literal.
3. **Brain contract fingerprint.** 30 source files (`_CONTRACT_SOURCES` at
   `src/ai_brain/production_model.py:164`, plus `_CONTRACT_SOURCES_REPO` for
   `tools/topstepx_production_session.py`) and the resolved retrieval policy are
   hashed into `brain:<16 hex>`. Editing any of them changes the fingerprint and
   **invalidates existing session authorizations** (they fail closed and must be
   re-issued). If you touch one, say so in the commit message with the old and new value.
   Production value: `brain:0ec4ef07c75dbcef` (`cbfaddb`). Chain since the
   NEWS-2 split: `3a09895222765f22` (`49550b5`) → `0cf842782313d826` (`a8ba9d5`) →
   `0ec4ef07c75dbcef` (`3f90e2d`; `cbfaddb` unchanged).
   **Only compute it with the pinned dependencies installed.** Without them the
   retrieval-contract import fails, gets hashed as `retrieval<missing>`, and you
   get a wrong value with no error.
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
  when editing it; don't "fix" it to UTF-8. To build a venv, convert a scratch copy:
  `iconv -f UTF-16LE -t UTF-8 requirements.txt | sed 's/\r$//; 1s/^\xEF\xBB\xBF//' > /tmp/req.txt`
  then `pip install -r /tmp/req.txt pytest==9.1.1`.
- Fingerprint check (with that venv):
  `python -c "import sys; sys.path.insert(0,'src'); from ai_brain import production_model as PM; print(PM.brain_contract_fingerprint())"`
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
