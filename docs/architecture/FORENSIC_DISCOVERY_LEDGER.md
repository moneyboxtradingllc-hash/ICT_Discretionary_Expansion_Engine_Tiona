\# FORENSIC DISCOVERY LEDGER



\## ICT Discretionary Expansion Engine



\---



\## FD-001 — Execution Layer Innocence



Date: 2026-06-18



Finding:

Execution layer was never the issue.



Proof:

Tiona’s forensic scans proved:



\* no broker errors

\* no bracket failures

\* no account failures

\* no submission failures



Truth:

Execution only acts on upstream authority.



Doctrine:

Always audit authority before blaming execution.



Status:

LOCKED



\---



\## FD-002 — Qualification Veto Dominance



Date: 2026-06-18



Finding:

qualification.status=no\_trade fully suppresses:



\* playbook generation

\* toolbox activation

\* candidate generation

\* execution path



Truth:

Qualification is a hard gate.



Doctrine:

No qualification = no playbook.

No playbook = no toolbox.

No toolbox = no execution.



Status:

LOCKED



\---



\## FD-003 — Safe-Harbor Discovery



Date: 2026-06-18



Finding:

Lower-timeframe sweep/reclaim can exist inside dangerous HTF conditions.



But current architecture hard-vetoes it.



Truth:

Dangerous HTF does not always mean no opportunity.



Doctrine:

Mainline needs native exception-lane architecture.

Not patch doctrine.



Status:

UNDER ARCHITECTURAL REVIEW



\---



\## FD-004 — Strategy Latency Was Innocent



Date: 2026-06-18



Finding:

Deep runtime audit proved:



qualification\_ms ≈ fast

playbook\_ms ≈ fast

risk\_ms ≈ fast

toolbox\_ms ≈ fast

proposed\_decision\_ms ≈ fast



Truth:

Strategy is not the latency bottleneck.



Doctrine:

Never assume AI/strategy is slow without timing proof.



Status:

LOCKED



\---



\## FD-005 — Broker Maintenance Bottleneck



Date: 2026-06-18



Finding:

Hot path bottlenecks:



\* reconcile\_ms

\* account\_check\_ms

\* position\_check\_ms

\* open\_orders\_ms



Truth:

Broker maintenance was choking scans.



Doctrine:

Neutral scans should use cache.

Actionable trades require fresh preflight.



Status:

APPROVED FOR MAINLINE REVIEW



\---



\## FD-006 — Sandbox Branch Value



Date: 2026-06-18



Finding:

Tiona’s branch exposed structural weaknesses faster than mainline.



Truth:

Parallel testing accelerates forensic discovery.



Doctrine:

Sandbox branches are reconnaissance engines.



Mainline absorbs principles, not patches.



Status:

LOCKED



\---



\## FD-007 — QQQ vs MNQ Environment Truth



Date: 2026-06-18



Finding:

QQQ was acting as low-volatility sparring.

MNQ/NQ is the real combat environment.



Truth:

Mainline was designed for futures volatility.



Doctrine:

QQQ is useful for behavioral observation.

MNQ/NQ is required for timing validation.



Status:

LOCKED



























\---



\## FD-008 — Mainline Authority Stack Optimization Discovery



Date: 2026-06-18



Finding:

Mainline Expansion Bot has a real multi-layer authority structure, but the authority stack must be optimized before serious futures deployment.



Current authority stack includes:



\* Data / Snapshot Builder

\* Structure / Liquidity / Volatility / Expansion / PO3

\* Regime

\* Narrative Authority

\* AI Brain ECU

\* Qualification

\* Playbook

\* Risk

\* Toolbox

\* Market Commander

\* Decision Authority

\* Execution Gate

\* Broker Runtime



Truth:

The bot is no longer primarily mechanical.



The last seven days shifted the system from mechanical signal logic toward a genuine intelligence/authority organism.



However, intelligence density creates potential latency, authority compression, over-neutralization, and delayed execution if not architected correctly.



Doctrine:

Separate the bot into three lanes:



1\. Fast Hot Path



&#x20;  \* deterministic

&#x20;  \* no blocking LLM calls

&#x20;  \* trade/no-trade decision

&#x20;  \* candidate selection

&#x20;  \* execution gate

&#x20;  \* broker action



2\. Slow Intelligence Lane



&#x20;  \* AI thesis

&#x20;  \* narrative context

&#x20;  \* memory retrieval

&#x20;  \* market interpretation

&#x20;  \* background updates

&#x20;  \* cached authority state



3\. Post-Trade Learning Lane



&#x20;  \* MFE/MAE review

&#x20;  \* thesis correctness review

&#x20;  \* timing review

&#x20;  \* memory updates

&#x20;  \* adaptive learning feedback



Rule:

AI may own narrative authority, but fresh AI calls must not block execution.



The fast lane consumes the latest valid cached intelligence state.



Status:

APPROVED FOR MAINLINE ARCHITECTURE REVIEW



\---



\## FD-009 — Mainline Must Absorb Principles, Not Sandbox Patches



Date: 2026-06-18



Finding:

Tiona’s branch exposed valuable weaknesses:



\* qualification veto dominance

\* missing safe-harbor exception lane

\* trade-management gaps

\* liquidity TP disconnect

\* oversized stop vulnerability

\* break-even safety problem

\* broker maintenance latency

\* forensic logging necessity



Truth:

These are valuable reconnaissance findings, but Tiona’s bot is not the same organism as mainline.



Tiona’s branch is an experimental sandbox.



Mainline must not copy patches directly.



Doctrine:

Sandbox branch findings must be translated into mainline-native architecture.



Bad:

Copy patch into mainline.



Good:

Extract structural principle, audit mainline, design native doctrine.



Status:

LOCKED



\---



\## FD-010 — Timing Intelligence Is the Next Mainline Battleground



Date: 2026-06-18



Finding:

Playbook and Toolbox already provide real entry-model intelligence.



The system can generate and rank tools such as:



\* FVG

\* IFVG

\* Rejection Block

\* Order Block

\* OTE

\* Liquidity Sweep

\* Breaker / Continuation models



Truth:

Tool selection exists.



But timing optimization is not yet mature.



The missing layer is not “which tool is valid?”



The missing layer is:



Which valid entry offers the best timing, lowest heat, best asymmetry, and cleanest strike location?



Doctrine:

Do not rebuild Toolbox.



Add or formalize Timing Intelligence between:



Toolbox

→ Timing Intelligence

→ Execution Gate



Timing Intelligence should evaluate:



\* heat

\* entry proximity

\* invalidation efficiency

\* premium/discount alignment

\* liquidity objective alignment

\* narrative alignment

\* urgency

\* chase risk



Status:

NEXT MAJOR MAINLINE AUDIT TARGET



\---



\## FD-011 — Mainline Live-Market Readiness Question



Date: 2026-06-18



Finding:

The bot may be approaching the point where more architecture alone cannot answer the next questions.



Remaining questions include:



\* Can it execute in real futures volatility?

\* Is timing late or early?

\* Does it chase?

\* Does it correctly refuse bad conditions?

\* Does Market Commander over-neutralize?

\* Does the AI Brain update fast enough?

\* Does the Toolbox select the right weapon in combat?



Truth:

Some truths cannot be discovered inside QQQ or offline architecture work.



NASDAQ futures exposure is required to validate timing and execution behavior.



Doctrine:

Mainline should not wait for every future feature before controlled Topstep practice.



But it must enter practice only with:



\* clear forensic logging

\* practice-only protection

\* small size

\* no live funded exposure

\* controlled observation goal

\* no blind automation trust



Status:

UNDER DEPLOYMENT REVIEW



