# Handoff — context rescue (2026-10-02)

Paste this at the start of a new Claude Code chat on branch
`claude/admiring-darwin-9ninpx`. It is a status note, not a transcript.

> **Update (later 2026-10-02): partly superseded.** This note was written from the
> NEWS-2 branch (`95170d8`). Production actually runs **`cbfaddb` (LATENCY-1) on
> `feature/latency-1-preauthorized-plans`**, fingerprint **`brain:0ec4ef07c75dbcef`**,
> with two live sessions since (PROD-20261001/02). Open questions 1 (constants) and
> 4 (reissue authorization) are settled: the authorizations use the code values, and
> every session is freshly authorized. The current open items are the four defects
> waiting on Maurice's rulings. `CLAUDE.md` and `docs/PROJECT_CONTEXT.md` (§4a, §9a–b,
> §12) are current; trust them over this note.

## Situation

- The long-running session **"Maurice Phillips trading bot email"** (branch
  `claude/optimistic-turing-bxpw5k`) stopped responding. Its last turn failed with
  a **model safety-classifier flag** (`[reasoning_extraction]`) on a request to write a
  single giant handoff document. The error text says this can hit normal
  conversations and suggests changing model or starting a new session.
- **Nothing was lost.** All its code is pushed on that branch (HEAD `95170d8`,
  2026-09-28, "NEWS-2 foundation…"). Its conversation also still exists.
- This session rebuilt the context **from the repo only** and did not
  read that session's transcript.

## What this session did

1. Fast-forwarded `claude/admiring-darwin-9ninpx` to `95170d8` (it was 53 commits behind; no divergence).
2. Added `CLAUDE.md` (rules, run/test, conventions, repo map).
3. Added `docs/PROJECT_CONTEXT.md` (architecture, doctrine, history, current state,
   open items, glossary, doc index). Each claim is tagged `[code]`, `[doc]`, or
   `[unverified]`.
4. Added this handoff.

## Verified facts

- **Python 3.12+ is required.** Python 3.11 fails at import with a `SyntaxError`
  in `src/broker/luna_candidate_producer.py` (PEP 701 f-strings). Repo certified on
  3.14.5; verified here on 3.13. `requirements.txt` is UTF-16LE + CRLF — keep it.
- Focused tests (production model, model identity, provider identity, NEWS-2
  factual foundation): **136 passed, 1 skipped**.
- Full suite on this branch: **7,649 passed, 585 skipped, 0 failed** (CPython 3.13; details in `docs/PROJECT_CONTEXT.md` §14).

## Key rules to carry forward

- Orders stay **disarmed** unless a durable, signed session authorization exists.
- Risk constants have one owner each and change only on a written ruling by Maurice.
- Editing any of the 30 Brain-contract files changes `brain:<fingerprint>` and
  invalidates session authorizations. Last recorded: `brain:3a09895222765f22`.
- Production Brain model is `gpt-6-luna` (single authority, fail-closed on mismatch).
- Never skip/disable tests; never commit `.env` or credentials.

## Open questions for the owner

1. **Doctrine numbers disagree.** An older chat said: threshold 40, 45 pt stop, $250,
   15 contracts, 2 trades, 09:30–16:07 ET. The code says: production lane preferred
   35 pt / absolute 50 pt / 15 contracts / $350 risk / $725 daily loss budget /
   09:00–14:00 ET; deterministic lane 25 pt stop / $500 / 30 contracts / $1,000 /
   09:30–14:00 ET. Which is intended? (Ask Maurice.)
2. Is wake **ENFORCE** accepted for the Combine phase? (Docs say historical
   acceptance was not proven; sessions have run it since.)
3. What does **"Miss Juicy"** (commit `989ae89`) refer to? Not defined in the repo.
4. A fresh session authorization is needed before the next `PROD-` session (the
   Brain fingerprint changed at `49550b5`).

## Suggested first message for the new chat

> Read `CLAUDE.md` and `docs/PROJECT_CONTEXT.md`. Then give me a ten-line summary
> of the current state and the open questions, and wait for my instruction.

Keep early requests narrow (specific files or questions). If the model flags a
message, rephrase it narrower or switch models; the repo docs carry the context.

## Not done / not verified

- The old session's transcript and most `ab*` / `ai_brain_*` docs were not read.
- No orders, sessions, or authorizations were run or issued.
- The claude.ai data export (30 chats) was used only to identify chats; it was kept
  outside the repo and must **not** be committed (it contains unrelated personal chats).
