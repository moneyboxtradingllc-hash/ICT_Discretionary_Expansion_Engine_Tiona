# Topstep Combine Reset — Operator Runbook

Written after 2026-08-10, when a mid-session Combine reset issued a **new account
identity** and the running bot stayed pinned to the retired one.

The reset is not a state change on an existing account. Topstep retires the old
account and creates a new one with a **different account id and a different
fingerprint**. Every local binding that names the old account is stale the
moment the reset completes.

Observed that day:

| | retired | active after reset |
|---|---|---|
| name | `50KTC-TEST-FIXTURE-RETIRED` (retired) | `50KTC-TEST-FIXTURE-ACTIVE` (active) |
| fingerprint | `acct:fc84…` (retired) | `acct:c533…` (active) |
| canTrade | False | True |
| isVisible | False | True |
| balance | $48,028.06 | $50,000.00 |

The bot's pin path fails closed — it refuses to fall back to any other account —
so a restart after a reset does not silently trade the wrong one. But a process
already running holds the old account pinned in memory, and must be stopped.

---

## After any Combine reset, before any authorization

**1. Stop any running production session.** It is pinned to an account that no
longer exists.

**2. Discover the new active account.** Never type the id; derive it.

```
python tools/preflight_account_state.py
```

Exactly one account should return `canTrade=True, isVisible=True`. If more than
one is active, stop — the binding is ambiguous and must not be guessed.

**3. Derive the fingerprint from that same account object**, not from memory and
not from an old file.

**4. Update the local binding** — `TOPSTEPX_ACCOUNT_ID` and
`TOPSTEPX_ACCOUNT_FINGERPRINT` in `.env`. Never commit `.env`. Keep the previous
values in an ignored backup until the new session is proven.

**5. Mint a fresh production authorization with a NEW session id.**

```
python tools/topstepx_issue_session_authorization.py \
    --session-id PROD-<date>-<suffix> --date YYYY-MM-DD
```

Do **not** reuse a session id that belongs to the retired account. Mission and
ledger filenames are keyed by session id, so a fresh id is what keeps the old
session's missions, voids and submission records from being read as this
session's history.

**6. Verify the account is flat and tradeable** — 0 positions, 0 working orders,
correct contract, balance as expected.

**7. Manually confirm Auto OCO / bracket orders are enabled in the Topstep UI.**

> **This step is manual and cannot be automated.** The ProjectX
> `/api/Account/search` response exposes only `balance`, `canTrade`, `id`,
> `isVisible`, `name`, `simulated`. **There is no Auto OCO field.** Do not build
> a check that pretends to verify it — a green tick for a setting the API never
> reported would be worse than no check at all.
>
> A reset appears to clear this setting. On 2026-08-10 it had to be re-enabled
> by hand after the reset.

**8. Run the normal read-only production preflight** before arming.

---

## What is NOT established

Order `3385801549` was rejected by Topstep during the window when Auto OCO was
disabled, and its rejection reason was never persisted. Auto OCO being off is a
**plausible but unproven** cause: the smoke test run afterwards to check it
carried an unrelated unsigned-ticks defect and never reached the question.

Do not record "Auto OCO caused the rejection" as fact anywhere. Since that day
the production path flight-records every submission, so the next rejection will
carry its own reason and will not need a hypothesis.
