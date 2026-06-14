# MAP-4 — Thesis Ownership Audit (Brain vs Mechanical Layer), read-only at `dd52dec`

Design-ownership audit: does the wiring match the intended architecture (Brain =
ECU, mechanical = sensors+executor)? No code changed. Grep + pipeline-order
evidence.

## The decisive structural fact
The Brain runs **after** the entire decision chain. In `build_snapshot`
(snapshot_builder.py): qualification(126) → playbook(129) → risk(137) →
toolbox(140) → wrapper(159). Then in scan_loop: gate(886) → … →
`run_narrative_brain`(923). **By the time the Brain produces anything,
qualification, playbook, toolbox, and the gate have already decided the trade.**
And the Brain's outputs (`recommended_playbook_family`, `recommended_tool_family`,
`forbidden_direction`, `dominant_reasoning`, `narrative_direction`) have **zero
consumers outside `ai_brain/`** (grep: NONE). The Brain is a post-hoc observer.

## Phase 1 — Playbook ownership
- **A. Who selects the playbook?** `playbooks/playbook_classifier.classify_playbook`
  (mechanical scoring + firewalled `_direction`).
- **B. Mechanical or Brain?** Mechanical.
- **C. Does the Brain recommendation influence it?** No — `recommended_playbook_family`
  has no consumer; and the Brain runs after playbook is set.
- **D. Brain recommendation ignored?** Yes, entirely.
- **E. If the Brain vanished, would playbook selection function?** Yes, unchanged.

## Phase 2 — Toolbox ownership
- **A. Who selects the toolbox?** `toolbox/toolbox_engine.run_toolbox`, from
  `playbook.direction` (mechanical).
- **B. Mechanical or Brain?** Mechanical.
- **C. Brain influence?** None — `recommended_tool_family` has no consumer.
- **D. Ignored?** Yes.
- **E. Functions without the Brain?** Yes, unchanged.

## Phase 3 — Thesis ownership
Operational "thesis" = {direction, forbidden direction, opportunity meaning,
trade intent}. Produced mechanically: direction by `qualification._direction`
(firewalled delivery/liquidity, AB-2A/2C); forbidden by the firewall/gate;
intent by `trade_intent/intent_builder`. **The Brain produces a parallel thesis
(`narrative_direction`/`forbidden_direction`/`dominant_reasoning`) that nobody
consumes.** Owner: **mechanical layer.** The Brain's thesis is decorative.

## Phase 4 — Opportunity ownership
`qualification/trade_qualification_engine.qualify_trade` scores and classifies
the opportunity (status/grade/score). Mechanical. The Brain does not gate or
influence qualification (runs after it, output unread). Owner: **mechanical.**

## Phase 5 — ECU test (actual code dependencies)
- **Remove the Brain entirely:** playbooks, toolbox, qualification, generation,
  gate, risk, ATM, execution **all still function** — none import or read
  `ai_brain`. Only `divergence` + `snapshot_store` reads vanish (logging). The
  trading system is fully operational without the Brain. → **The Brain is NOT
  load-bearing; it is not the ECU.**
- **Remove the mechanical layer, keep only the Brain:** nothing functions. The
  Brain has no inputs (`build_brain_input` reads mechanical snapshot fields), no
  retrieval store (mechanical), no candles/price, no execution. It produces a
  narrative consumed by no one. → **The Brain is 100% dependent and produces
  zero load-bearing output.**

## Phase 6 — Ownership matrix
| Capability | Current owner | Intended owner | Mismatch? |
|---|---|---|---|
| Evidence Collection | mechanical engines | mechanical | no |
| Market Interpretation | mechanical (narrative_builder + qualification) | **Brain** | **YES** |
| Opportunity Recognition | mechanical (qualification) | **Brain** | **YES** |
| Playbook Selection | mechanical (playbook_classifier) | **Brain** | **YES** |
| Toolbox Selection | mechanical (toolbox_engine) | **Brain** | **YES** |
| Thesis Generation | mechanical (qual+playbook+debate); Brain parallel-but-ignored | **Brain** | **YES** |
| Direction Generation | mechanical (qualification._direction, firewalled) | **Brain** | **YES** |
| Direction Prohibition | mechanical firewall + gate (council/R-001/NA); Brain forbidden ignored | **Brain** | **YES** |
| Execution Planning | mechanical (toolbox/order_builder) | **Brain** (preferred path) | **YES** |
| Order Execution | mechanical (execution_engine/broker) | mechanical | no |
| Risk Management | mechanical (risk_governor/regime matrix) | mechanical | no |

## Phase 7 — Architecture alignment
**The current architecture does NOT match the intended architecture.** Eight of
eleven capabilities are owned by the mechanical layer but were intended for the
Brain. The three matches (evidence collection, order execution, risk) are exactly
the capabilities the intended design assigns to the mechanical layer. Every
*intelligence* capability the design assigns to the Brain is currently
mechanical, and the Brain's corresponding outputs are unconsumed.

Two structural reasons (not preferences — code facts):
1. **Consumption:** no module reads the Brain's recommendation fields.
2. **Order:** the Brain runs after the decision chain, so it could not seed
   playbook/toolbox/direction even if its output were read.

What must move for the Brain to be the ECU: market interpretation, opportunity
classification, playbook selection, toolbox selection (direction seeding), thesis
/direction generation, direction prohibition, and execution planning — AND the
Brain must run **before** playbook/toolbox so it can seed them. (Mapping only —
not implemented.)

## Final questions
1. **Is the Brain the ECU?** No.
2. **If not, who is?** The mechanical decision chain — qualification → playbook →
   toolbox, with the execution gate as final authority. That chain is the de-facto ECU.
3. **Who owns playbook selection today?** `playbook_classifier` (mechanical).
4. **Who owns toolbox selection today?** `toolbox_engine` (mechanical).
5. **Who owns thesis generation today?** Mechanical (qualification+playbook+debate);
   the Brain's parallel thesis is unconsumed.
6. **First-class intelligence layer or observer?** **Observer** — it sees and
   narrates but owns and influences nothing in the decision path.
7. **What must migrate to the Brain to align with the intended design?**
   - Direction generation (from qualification._direction → Brain narrative_direction)
   - Direction prohibition (Brain forbidden_direction consumed by the gate)
   - Opportunity recognition (qualification gated/seeded by Brain)
   - Playbook selection (Brain recommended_playbook_family → playbook activation)
   - Toolbox selection (Brain recommended_tool_family → tool activation)
   - Thesis generation (Brain thesis becomes the canonical thesis)
   - Execution planning (Brain preferred path → order_builder)
   - **Plus a pipeline reorder:** Brain must run before playbook/toolbox.
   These are the AB-5/AB-5B generation-ownership migration — NOT implemented here.

STOP — ownership mapping only. No code changes, no authority, no AB-5B.
