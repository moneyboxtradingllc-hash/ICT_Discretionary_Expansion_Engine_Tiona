# D11 to D14: proposal definitions with provenance (NOT ratified, NOT implemented in protected source)

The repository file `docs/recognition_validation/OWNER_DECISIONS_APPENDIX.md` on this branch (frozen source
ffe00ae) defines D01 to D10 only. D11 to D14 were proposed in the gap-closure return and exist **only inside its
verified archive**. They are reproduced below verbatim, for reference only.

Provenance:

- **Archive:** `docs/recognition_validation/gap_closure_package/STAGE5_GAP_CLOSURE_c962a3d.tar.xz` at evidence
  commit 976d0c1efbfe22de8e9fe0cf4eba82f5038292a9, SHA-256
  c9176583ea6914a36c33606f348fe22b75b07cf5c17fde9628923a5c56e6b057. This was re-extracted and re-verified here.
- **Archive member:** `STAGE5_GAP_CLOSURE_c962a3d/OWNER_DECISIONS_APPENDIX.md`, SHA-256
  a9e090776f17cba54cbff8dc91a12ddf2dbbe507ac86b4a91bf61ece7a573a00. This matches the archive's own `MANIFEST_SHA256`.
- **Excerpt:** member lines 125 to 180, section "Gap-closure additions (engineering GO of 2026-10-19)".

Status: owner proposals only.
- D11 (WATCHING/refusal semantics), D12 (`.env` import), D13 (wall-clock wake stamps) and D14 (delivery vocabulary)
  are **reserved to the owner**.
- The protected-source changes they describe (D12, D13) are **not implemented**.
- Nothing here ratifies them.

---

## Gap-closure additions (engineering GO of 2026-10-19)

### D11: WATCHING in the contract 07 REFUSAL cell

- **Built now:** the mission 4 COMPOSITION layer scores `expected_action`
  WATCHING. It agrees with a published or waiting plan, and with its trigger.
- **Still unchanged:** `scoring.classify_episode` (the REFUSAL cell) knows
  ENTRY and STAND_DOWN only. It treats a published plan as an entry, so it
  scores FALSE_POSITIVE against a WATCHING label. The GAP_M4 parent reproducer
  shows this.
- **Owner input and command:** decide the REFUSAL semantics for WATCHING:
  plan published = HIT, no plan = MISS or UNSCORED. Record the decision in a
  ratified `scoring/v1`. Engineering then changes only that branch.

### D12: import-time `.env` loading in production libraries

- **Built now:** a trajectory child refuses `load_dotenv`, records the refusal
  (a no-op), and re-checks its environment against the allowlist after the
  run.
- **Still UNPROVEN:** isolation of any other importer of the scan cycle.
  `src/data_feed/__init__.py`, `src/live_scan/scan_loop.py` and `src/main.py`
  call `load_dotenv()` at import.
- **Owner input and command:** approve the narrow production fix: move
  `load_dotenv()` to the launcher entrypoint
  (`tools/topstepx_production_session.py`), which is a protected-source
  change.

### D13: wall-clock wake stamps (inventoried T32 site)

- **Built now:** the offline WakeRegistry reads the injected decision clock.
  The stamp is telemetry only: plan expiry and revalidation read the loop
  clock.
- **Still unchanged in production:** `WakeRegistry._observed_at` stamps an
  interaction raised without `observed_at` (publish-while-inside, armed-inside
  refresh) with the wall clock.
- **Owner input and command:** approve the narrow production fix: the loop
  passes `observed_at=self.clock()` to `publish_conditional_watch`, and the
  launcher passes its observation time to `refresh_from_bars`.

### D14: delivery vocabulary for layer scoring

- **Built now:** DELIVERY maps production Lifecycle states onto the
  annotation vocabulary:
  - ACTIVE_DELIVERY to ACTIVE_DELIVERY;
  - RETRACING to RETRACEMENT;
  - TRANSFER_UNRESOLVED to REVERSAL_DEVELOPING;
  - a path ownership change to TRANSFER_CONFIRMED;
  - DESTINATION_SUBSTANTIALLY_DELIVERED to DESTINATION_DELIVERED, which has
    no annotation value.

  A RETRACEMENT label agrees with an intact campaign (ACTIVE_DELIVERY or
  RETRACEMENT). AUTHORITY_UNKNOWN is UNPROVEN.
- **Still UNPROVEN:** whether this mapping is the owner's meaning.
- **Owner input and command:** ratify or amend the mapping, and add a
  delivered-destination value to `annotation/v1` if one is wanted.

