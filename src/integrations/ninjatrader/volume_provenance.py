"""Phase 8 — MNQ volume era separation.

The QQQ IEX volume baseline MUST NOT be reused for MNQ. Until enough MNQ
sessions satisfy the existing minimum-N doctrine, volume queries return an
honest INSUFFICIENT state. We never fabricate a percentile, never substitute
QQQ volume, and never convert missing volume into directional bias.

This is provenance + gating only; the existing volume_witness remains
witness-only and gains no new authority here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Minimum MNQ sessions before a relative-volume baseline may be computed.
# Mirrors the existing minimum-N doctrine; kept explicit for the new era.
MIN_MNQ_SESSIONS_FOR_BASELINE = 20


@dataclass
class MNQVolumeProvenance:
    instrument: str                     # exact MNQ expiry
    source: str = "ninjatrader_futures_feed"
    contract_month: str = ""
    session_template: str = "rth_0930_1130_ET"
    collection_start: str = ""
    collection_end: str = ""
    sessions_collected: int = 0
    completeness: str = "unknown"       # complete | partial | unknown
    rollover_treatment: str = "single_expiry_no_stitch"

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)


@dataclass
class VolumeReading:
    status: str                         # OK | INSUFFICIENT_HISTORY
    relative_volume: Optional[float]    # None while insufficient
    reason: str
    provenance: dict


def relative_volume(provenance: MNQVolumeProvenance,
                    current_volume: Optional[float] = None) -> VolumeReading:
    """Return a relative-volume reading, or an honest INSUFFICIENT_HISTORY when
    the MNQ era has not yet met the minimum-N doctrine.

    NEVER returns a fabricated percentile and NEVER falls back to QQQ.
    """
    if provenance.sessions_collected < MIN_MNQ_SESSIONS_FOR_BASELINE:
        return VolumeReading(
            status="INSUFFICIENT_HISTORY",
            relative_volume=None,
            reason=(f"MNQ has {provenance.sessions_collected}/"
                    f"{MIN_MNQ_SESSIONS_FOR_BASELINE} sessions — no baseline; "
                    f"QQQ volume MUST NOT be substituted"),
            provenance=provenance.to_dict(),
        )
    # A real baseline computation would live here once history exists. For the
    # foundation era we still refuse to invent a number without a stored baseline.
    return VolumeReading(
        status="INSUFFICIENT_HISTORY",
        relative_volume=None,
        reason="baseline store not yet built for MNQ era (foundation mission)",
        provenance=provenance.to_dict(),
    )
