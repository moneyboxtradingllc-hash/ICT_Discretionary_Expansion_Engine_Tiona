"""Stage 5 offline recognition-validation harness.

An OBSERVER and DRIVER of the current production graph, never a second
implementation of it. Production code must not import this package; it
imports production only to drive the actual ProductionLoop /
ProductionScanCycle under availability-controlled local inputs.

Nothing here arms, sizes, submits, or reaches a provider, venue, account or
paid model. Mode C (current external Brain) is implemented but disabled: it
refuses before any transport unless a complete, owner-sealed authorization
and budget are supplied by a later, separate decision.
"""

SCHEMA_VERSIONS = (
    "annotation/v1", "brain_call/v1", "corpus/v1", "event/v1", "model_authorization/v1",
    "pricing/v1", "release/v1", "result/v1", "run/v1", "schedule/v1", "scoring/v1",
)
