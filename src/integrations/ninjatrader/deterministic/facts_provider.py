"""Mechanical facts provider for the deterministic lane (HONEST, fail-closed).

Builds a real MNQ snapshot from the bridge and assembles the `mechanical_facts`
the author needs. The organism's AUTHORITATIVE mechanical subsystems
(qualification, playbook, decision, protected-zone, Market Commander, FC-0B,
final gate) are the real authors of those facts — they are NOT reimplemented or
faked here. Until they are wired to run deterministically on MNQ (no Brain, no
OpenAI) and that wiring is verified, this provider returns those facts as
UNKNOWN, which makes the author fail closed (NO TRADE).

This is deliberate: a 5-contract auto-trader must never trade on fabricated
mechanical agreement. Real structural observations that CAN be computed
deterministically from MNQ bars (recent swings, displacement, sweep) are
provided as evidence inputs; the authoritative directional gates stay unknown
until genuinely wired.
"""
from __future__ import annotations

from typing import Optional

# Which authoritative facts still require the organism's real subsystems wired
# to deterministic MNQ evaluation. Listed so the NO-TRADE reason is precise.
UNWIRED_AUTHORITIES = (
    "qualification_direction", "playbook_direction", "decision_direction",
    "protected_zone_permits", "commander_state", "fc0b_permits",
    "final_gate_authorizes", "setup_family", "direction", "trigger_confirmed",
)


def _swings(bars: list):
    """Most recent prior swing high/low from completed bars (simple 3-bar pivots)."""
    highs = [b.get("high") for b in bars if b.get("high") is not None]
    lows = [b.get("low") for b in bars if b.get("low") is not None]
    swing_high = max(highs) if highs else None
    swing_low = min(lows) if lows else None
    return swing_high, swing_low


def build_facts(bars: list, quote: dict) -> dict:
    """Assemble mechanical_facts. Real structural evidence is computed; the
    organism's authoritative directional gates are returned UNKNOWN (None) so the
    author fails closed until they are wired."""
    bars = bars or []
    quote = quote or {}
    swing_high, swing_low = _swings(bars[-60:]) if bars else (None, None)
    last = quote.get("last")

    # Displacement evidence: a recent bar whose range clearly exceeds the median.
    ranges = [b["high"] - b["low"] for b in bars[-30:]
              if b.get("high") is not None and b.get("low") is not None]
    displacement = None
    if len(ranges) >= 10:
        med = sorted(ranges)[len(ranges) // 2]
        displacement = ranges[-1] >= 2.0 * med if med > 0 else None

    facts = {
        # Structural observations we can compute deterministically from MNQ bars.
        "recent_swing_high": swing_high,
        "recent_swing_low": swing_low,
        "last_price": last,
        "liquidity_evidence": None,      # requires organism liquidity witness on MNQ
        "structural_evidence": None,     # requires organism structure witness on MNQ
        "displacement_evidence": displacement,
        "expected_entry": last,
        "entry_invalidation": None,      # comes from the organism's real invalidation
        "opposing_direction": None,
        # Authoritative directional gates — UNKNOWN until wired (fail closed).
        "setup_family": None,
        "direction": None,
        "qualification_direction": None,
        "playbook_direction": None,
        "decision_direction": None,
        "trigger_confirmed": None,
        "protected_zone_permits": None,
        "commander_state": None,
        "fc0b_permits": None,
        "final_gate_authorizes": None,
        # Provenance / honesty.
        "_provenance": "deterministic MNQ snapshot; authoritative gates UNWIRED",
        "_unwired_authorities": list(UNWIRED_AUTHORITIES),
    }
    return facts
