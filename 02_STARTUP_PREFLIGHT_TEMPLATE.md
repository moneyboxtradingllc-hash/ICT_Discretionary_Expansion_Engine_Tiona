# Startup / preflight template (existing operational controls only)

This is a template for a LATER, separately authorized session. Nothing here authorizes one.
No new gate, approval file or authority service is introduced.

## A. Frozen dormant source (as delivered; selection OFF)

1. Verify the identity of the checkout you will run.
   - `git rev-parse HEAD` returns the reviewed SHA, and `git status --porcelain` is empty.
   - `python tools/verify_engineering_ledger.py --require-clean` returns `LEDGER_VERIFIED`.
2. Run the startup banner (`--scans 0`, disarmed). Expect:
   - `LOCAL AUTHORITY SELECTION    : OFF (legacy DISABLED; no local cases)`
   - `LOCAL AUTHORITY SOURCE       : src/market_data/local_authority.py:RELEASE_SELECTION`
   - `BRAIN CONTRACT FINGERPRINT   : ...` ending in the last six characters of the reviewed fingerprint.
3. Result: the new routes are unused. This is the legacy, accepted participation.

## B. Only after an owner decision applies the reviewed activation diff

1. The new reviewed commit contains exactly the one-line selection change plus its pins, test and ledger (00_RETURN §2).
   - Run the complete source-isolated offline suite at that SHA. It must be green before any session.
2. The Brain contract fingerprint is new. Every earlier `session_auth_<id>.json` stops verifying. This is expected, and no migration or alias exists.
3. Issue a fresh durable SessionAuthorization for the session through the existing authorization CLI (`tools/topstepx_issue_session_authorization.py`). This is the operator's step, with their own credentials, on their own machine.
4. Disarmed rehearsal first (`--scans N`, no `--arm`). The banner must show:
   - `LOCAL AUTHORITY SELECTION    : requested local_authority_production/v1, resolved local_authority_production/v1`
   - `LOCAL AUTHORITY CASES        : member_order_witness, retained_support, delivery_change`
   - `LOCAL AUTHORITY SOURCE       : src/market_data/local_authority.py:RELEASE_SELECTION (bound by the Brain contract fingerprint)`
5. An armed session still requires everything that exists today: `--arm`, the durable SessionAuthorization verified against the account fingerprint, contract, session date and source fingerprint, plus every existing startup guard (contract month, startup history, memory/retrieval, window).
   - `PRODUCTION SESSION REFUSED`, `NO_SESSION_AUTHORIZATION` or `PRODUCTION LANE REFUSED` all mean stop.
6. Any `LOCAL AUTHORITY RELEASE SELECTION <reason>` refusal (offline, unknown or copied object) means the source is not the reviewed one: stop.
   - It is printed before authentication, and no venue or model is used.

## C. What this template never does

- It never selects a profile from env, CLI, JSON or an account record.
- It never edits protected session authorization.
- It never bypasses an existing guard.
- It never runs an operator process with execution switches set merely to test the profile.
