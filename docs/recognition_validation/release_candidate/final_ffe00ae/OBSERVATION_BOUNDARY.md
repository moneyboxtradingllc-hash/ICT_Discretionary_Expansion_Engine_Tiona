# Observation boundary correction (supersedes the "read-only" wording of the board and release record)

Codex's Stage 4 review, 2026-10-22, independently probed this offline. **"Disarmed" means no new entry. It is not a
universal broker read-only capability.** At frozen source ffe00ae (VERIFIED-CODE):

- **Hard flatten is not gated by `--arm`.** `tools/topstepx_production_session.py` `run_production_scans` checks
  `hard_flatten_due()` before each scan (line 553). When it is due, it calls `hard_flatten(session, contract, ...)` to
  close a position and cancel working orders, whatever `armed` is.
- **Reconciliation and management run before the arm switch.**
  `src/broker/topstepx_production_loop.py` `ProductionLoop._scan_once` runs `reconcile_missions()` and
  `manage_open_position()` (lines 1032 to 1036) before cognition and long before the entry arm switch.
- **These are existing safety responsibilities, not defects.** Protected management policy is unchanged and must not be
  altered to make a "read-only" label true.

What this means for observation (no authorization is granted here):

1. **Startup proof** (`--proof --observe 60`, no `--scans` and no `--until-close`):
   - authenticates, pins and resolves;
   - attaches the quote and candle consumers;
   - prints telemetry and `ACCOUNT STILL FLAT`.

   It runs no scan loop, so no management or hard-flatten path. It makes external reads and writes local capture files
   (candles, VAP). This is a separate step.
2. **Continuous scans** (`--until-close` or `--scans N`, even without `--arm`):
   - can reconcile and manage an existing position;
   - can hard-flatten at the window end;
   - make Brain/model calls (spend) per the session's Brain configuration.

   They need an explicit owner operating contract (D10) that states the model-call scope and the management/mutation
   scope, or an independently proven read-only capability boundary. A printed DISARMED banner, or an account that is
   flat at start, is **not** universal mutation denial.
3. **Codex's draft contract.** Codex's `SUPERVISED_OBSERVATION_DRAFT.md` (2026-10-22) is a **draft and NOT
   AUTHORIZED**. It separates external reads, local capture, source choice, supervision and stop criteria from
   continuous scans, management and model spend. It has not been executed.

The board's "CONDITIONAL GO for supervised, disarmed, read-only observation" is accordingly narrowed to: a supervised
**startup proof only**, subject to owner authorization, source choice and the conditions above. Continuous scans are
reserved to the owner's operating contract.
