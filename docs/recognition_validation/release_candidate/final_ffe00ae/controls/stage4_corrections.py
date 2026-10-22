"""Docs-only corrections requested by Codex's Stage 4 review (2026-10-22). Usage: python3 stage4_corrections.py <S>"""
import sys
from pathlib import Path

S = Path(sys.argv[1])
D = S / "g6/w201/docs/recognition_validation/release_candidate"
F = D / "final_ffe00ae"
A = S / "g6/gcx/STAGE5_GAP_CLOSURE_c962a3d/OWNER_DECISIONS_APPENDIX.md"

lines = A.read_text().splitlines()
assert lines[124].startswith("## Gap-closure additions") and lines[180].startswith("## Executable future sequence")
excerpt = "\n".join(lines[124:180])
(F / "DECISIONS_D11_D14_PROVENANCE.md").write_text(
    "# D11 to D14: proposal definitions with provenance (NOT ratified, NOT implemented in protected source)\n\n"
    "The repository file `docs/recognition_validation/OWNER_DECISIONS_APPENDIX.md` on this branch (frozen source\n"
    "ffe00ae) defines D01 to D10 only. D11 to D14 were proposed in the gap-closure return and exist **only inside its\n"
    "verified archive**. They are reproduced below verbatim, for reference only.\n\n"
    "Provenance:\n\n"
    "- **Archive:** `docs/recognition_validation/gap_closure_package/STAGE5_GAP_CLOSURE_c962a3d.tar.xz` at evidence\n"
    "  commit 976d0c1efbfe22de8e9fe0cf4eba82f5038292a9, SHA-256\n"
    "  c9176583ea6914a36c33606f348fe22b75b07cf5c17fde9628923a5c56e6b057. This was re-extracted and re-verified here.\n"
    "- **Archive member:** `STAGE5_GAP_CLOSURE_c962a3d/OWNER_DECISIONS_APPENDIX.md`, SHA-256\n"
    "  a9e090776f17cba54cbff8dc91a12ddf2dbbe507ac86b4a91bf61ece7a573a00. This matches the archive's own `MANIFEST_SHA256`.\n"
    "- **Excerpt:** member lines 125 to 180, section \"Gap-closure additions (engineering GO of 2026-10-19)\".\n\n"
    "Status: owner proposals only.\n"
    "- D11 (WATCHING/refusal semantics), D12 (`.env` import), D13 (wall-clock wake stamps) and D14 (delivery vocabulary)\n"
    "  are **reserved to the owner**.\n"
    "- The protected-source changes they describe (D12, D13) are **not implemented**.\n"
    "- Nothing here ratifies them.\n\n---\n\n" + excerpt + "\n")

(F / "OBSERVATION_BOUNDARY.md").write_text("""# Observation boundary correction (supersedes the "read-only" wording of the board and release record)

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
""")

r = D / "RELEASE_CANDIDATE.md"
t = r.read_text()
i = t.index("## 5. Read-only observation command")
t = t[:i] + """## 5. Observation commands (corrected 2026-10-22; see `final_ffe00ae/OBSERVATION_BOUNDARY.md`; nothing here is authorized)

"Disarmed" means no new entry. It is not read-only.

**Startup proof only.** Run this only after owner authorization and source choice, in a fresh checkout at ffe00ae (or
production cbfaddb), with the operator's own `.env` (never committed), never with `--arm`:

    export TOPSTEPX_ARM_ORDERS=false EXECUTION_ENABLED=false ALLOW_PAPER_ORDERS=false
    PYTHONPATH=src python3 tools/topstepx_production_session.py --proof --observe 60

**Continuous scans (`--until-close` / `--scans N`) are NOT part of this step.** Even disarmed, they reconcile and manage
an existing position (`ProductionLoop._scan_once`, before the arm switch) and hard-flatten at the window end
(`run_production_scans`, line 553). They also make model calls. They require the owner's operating contract (D10),
covering model-call and management/mutation scope; Codex's draft for it is NOT AUTHORIZED.

**Rollback:** stop the process with Ctrl-C (the pump joins and the hub closes) and return to the production checkout at
cbfaddb. There is no state migration to undo.

The authority to connect, arm, manage, flatten or trade is not granted by this document.
"""
r.write_text(t)

b = D / "GO_NO_GO_BOARD.md"
u = b.read_text()
anchor = "> and the UNPROVEN list is corrected after the coverage-instrument fix. The verdicts are unchanged."
assert u.count(anchor) == 1
u = u.replace(anchor, "> and the UNPROVEN list is corrected after the coverage-instrument fix.\n"
              "> **Corrected again on Oct 22 by `final_ffe00ae/OBSERVATION_BOUNDARY.md`:** \"disarmed\" is not read-only.\n"
              "> Continuous scans reconcile and manage positions and hard-flatten at the window end even without `--arm`.\n"
              "> The CONDITIONAL GO is narrowed to a supervised `--proof --observe 60` startup proof only. Continuous scans\n"
              "> are reserved to the owner's operating contract (D10). Section 7 below is superseded where it says\n"
              "> `--until-close` or \"read-only\".")
b.write_text(u)

s4 = F / "STAGE4_REMAINING_ITEMS.md"
v = s4.read_text()
a1 = "- D13 wall-clock wake stamps. The matrix also records"
assert v.count(a1) == 1
v = v.replace(a1, "- D13 wall-clock wake stamps. D11 to D14 are not defined in the repository appendix, which stops at\n"
              "  D10. Their proposal text, with provenance, is in `DECISIONS_D11_D14_PROVENANCE.md`; they are not\n"
              "  ratified. The matrix also records")
a2 = ("the formation's settled-bar self-revocation is an independent defense | OWNER-INPUT then ENG (D03/D04) |")
assert v.count(a2) == 1
v = v.replace(a2, "the formation's settled-bar self-revocation is an independent defense. **Restart precision:** "
              "`test_bound_scope_history_custody.py::test_new_process_replay_earns_the_formation_but_never_restores_scope` "
              "builds a fresh scan-cycle instance in one interpreter, which proves fresh-instance reconstruction. It does not "
              "prove literal OS-process replay of that complete bound tape, and the separate Stage 5 fresh-child proofs do "
              "not fill that cross-product. This is a coverage qualification, not a defect | OWNER-INPUT then ENG (D03/D04) |")
s4.write_text(v)
print("ok")
