# Operator preflight template for the configured review candidate (existing controls only)

This applies only after Codex's independent acceptance and a separate operational/session authorization.
Nothing here authorizes deployment, account rebind, arming or orders.

1. Run on exactly the accepted source.
   - `git rev-parse HEAD` returns the accepted SHA. For this candidate that is `a164f41ea5a39ad2c06d6207669d5999bbe9ef9f`, unless Codex accepts a later one.
   - `git status --porcelain` is empty.
   - `python tools/verify_engineering_ledger.py --require-clean` returns `LEDGER_VERIFIED`.
2. Check the Brain contract fingerprint: it must be the accepted value. For this candidate that is `brain:10bbf12edd6376e0`.
   - Every earlier session authorization is invalid by design.
   - Issue a fresh durable SessionAuthorization through `tools/topstepx_issue_session_authorization.py`. This is the operator's step, with the operator's own credentials, on the operator's machine.
3. Do a disarmed startup first (`--scans 0`, then `--scans N`, both without `--arm`). The banner must show:
   - `LOCAL AUTHORITY SELECTION    : requested local_authority_existing_policy_repair/v1, resolved local_authority_existing_policy_repair/v1`
   - `LOCAL AUTHORITY CASES        : member_order_witness`
   - `LOCAL AUTHORITY SOURCE       : src/market_data/local_authority.py:RELEASE_SELECTION (bound by the Brain contract fingerprint)`

   `retained_support` and `delivery_change` must NOT appear. The member-order witness is a source-order repair for the existing family, not a 1m-only strategy or a new trade prerequisite.
4. Use every existing control unchanged:
   - account fingerprint pin;
   - venue-resolved contract month;
   - startup history authority;
   - memory/retrieval startup state;
   - decision window and hard flatten;
   - doctrine risk/stop/size;
   - daily loss budget;
   - quote freshness;
   - bracket builder.

   Any of `PRODUCTION SESSION REFUSED`, `NO_SESSION_AUTHORIZATION`, `PRODUCTION LANE REFUSED` or `LOCAL AUTHORITY RELEASE SELECTION <reason>` means stop.
5. Armed operation requires `--arm` plus the verified durable authorization for this exact account, contract, session date and source fingerprint. Nothing else enables orders.
