"""
Tool Library v1 — single source of truth for canonical entry tools.

VALID_TOOLS   defines the 22 allowed tool names.
_ELIGIBLE     maps playbook → direction → eligible canonical tools.
_PREFERRED    maps playbook → direction → top 2-3 preferred tools (subset of eligible).
normalize_tool() resolves legacy/alias names to canonical equivalents.
_validate_tool_lists() asserts both tables at import time — raises ValueError on drift.
"""

# ── Canonical 22 tools ────────────────────────────────────────────────────────

VALID_TOOLS = {
    "bullish_fvg",
    "bearish_fvg",
    "bullish_ifvg",
    "bearish_ifvg",
    "bullish_order_block",
    "bearish_order_block",
    "bullish_breaker",
    "bearish_breaker",
    "bullish_rejection_block",
    "bearish_rejection_block",
    "bullish_ote_retracement",
    "bearish_ote_retracement",
    "bullish_mss_retest",
    "bearish_mss_retest",
    "bullish_ote_after_reclaim",
    "bearish_ote_after_reclaim",
    "bullish_opening_fvg",
    "bearish_opening_fvg",
    "bullish_opening_order_block",
    "bearish_opening_order_block",
    "bullish_range_break_retest",
    "bearish_range_break_retest",
    # PO3-REVERSAL-ORDER-BLOCK-1 (2026-08-20).
    "bullish_po3_reversal_order_block",
    "bearish_po3_reversal_order_block",
}

CANONICAL_TOOLS = sorted(VALID_TOOLS)

# ── Alias → canonical mapping ─────────────────────────────────────────────────
# Keys are bare family suffixes (without bullish_/bearish_ prefix).
# normalize_tool() re-applies the direction prefix after lookup.
#
# Mapping rationale:
#   breaker_retest          → breaker          (retest is implied; same structure)
#   continuation_mss_retest → mss_retest       (continuation qualifier is redundant)
#   fvg_continuation        → fvg              (continuation qualifier is redundant)
#   continuation_fvg        → fvg              (same)
#   ote_pullback            → ote_retracement  (pullback IS the OTE retracement)
#   ote_after_breakout      → ote_retracement  (OTE entry after any directional move)
#   ote_into_distribution   → ote_retracement  (OTE entry into delivery — same mechanics)
#   failed_breakout_reversal→ breaker          (failed breakout forms the breaker block)

_FAMILY_ALIASES: dict[str, str] = {
    "breaker_retest":             "breaker",
    "continuation_mss_retest":    "mss_retest",
    "fvg_continuation":           "fvg",
    "continuation_fvg":           "fvg",
    "ote_pullback":               "ote_retracement",
    "ote_after_breakout":         "ote_retracement",
    "ote_into_distribution":      "ote_retracement",
    "failed_breakout_reversal":   "breaker",
}


def normalize_tool(tool: str) -> str | None:
    """
    Return the canonical name for *tool*, or None if it cannot be mapped.
    Strips the direction prefix, resolves the family alias, and reattaches the prefix.
    """
    for prefix in ("bullish_", "bearish_"):
        if tool.startswith(prefix):
            family = tool[len(prefix):]
            canonical = prefix + _FAMILY_ALIASES.get(family, family)
            return canonical if canonical in VALID_TOOLS else None
    return None


# ── Eligible canonical tools per playbook per direction ───────────────────────

_ELIGIBLE: dict[str, dict[str, list]] = {
    "liquidity_sweep_reversal": {
        "bullish": [
            "bullish_ifvg",
            "bullish_breaker",
            "bullish_rejection_block",
            "bullish_mss_retest",
            "bullish_ote_after_reclaim",
            "bullish_po3_reversal_order_block",
        ],
        "bearish": [
            "bearish_ifvg",
            "bearish_breaker",
            "bearish_rejection_block",
            "bearish_mss_retest",
            "bearish_ote_after_reclaim",
            "bearish_po3_reversal_order_block",
        ],
    },
    "trend_continuation": {
        "bullish": [
            "bullish_fvg",
            "bullish_order_block",
            "bullish_ote_retracement",
            "bullish_mss_retest",
        ],
        "bearish": [
            "bearish_fvg",
            "bearish_order_block",
            "bearish_ote_retracement",
            "bearish_mss_retest",
        ],
    },
    "manipulation_to_distribution": {
        "bullish": [
            "bullish_ifvg",
            "bullish_breaker",
            "bullish_rejection_block",
            "bullish_fvg",
            "bullish_po3_reversal_order_block",
        ],
        "bearish": [
            "bearish_ifvg",
            "bearish_breaker",
            "bearish_rejection_block",
            "bearish_fvg",
            "bearish_po3_reversal_order_block",
        ],
    },
    "failed_breakout_reversal": {
        "bullish": [
            "bullish_breaker",
            "bullish_ifvg",
            "bullish_rejection_block",
            "bullish_mss_retest",
        ],
        "bearish": [
            "bearish_breaker",
            "bearish_ifvg",
            "bearish_rejection_block",
            "bearish_mss_retest",
        ],
    },
    "opening_drive": {
        "bullish": [
            "bullish_opening_fvg",
            "bullish_opening_order_block",
            "bullish_fvg",
            "bullish_ote_retracement",
        ],
        "bearish": [
            "bearish_opening_fvg",
            "bearish_opening_order_block",
            "bearish_fvg",
            "bearish_ote_retracement",
        ],
    },
    "range_expansion": {
        "bullish": [
            "bullish_range_break_retest",
            "bullish_fvg",
            "bullish_order_block",
            "bullish_ote_retracement",
        ],
        "bearish": [
            "bearish_range_break_retest",
            "bearish_fvg",
            "bearish_order_block",
            "bearish_ote_retracement",
        ],
    },
}

# ── Preferred tools per playbook per direction (top 2–3 of eligible) ──────────
# All entries must be in VALID_TOOLS and must be a subset of _ELIGIBLE for the
# same playbook/direction.
#
# Non-canonical aliases resolved:
#   fvg_continuation  (manipulation_to_distribution) → fvg
#   breaker_retest    (opening_drive)                → removed; third slot uses fvg
#   ote_after_breakout(range_expansion)              → ote_retracement

_PREFERRED: dict[str, dict[str, list]] = {
    "liquidity_sweep_reversal": {
        "bullish": ["bullish_ifvg", "bullish_breaker", "bullish_rejection_block"],
        "bearish": ["bearish_ifvg", "bearish_breaker", "bearish_rejection_block"],
    },
    "trend_continuation": {
        "bullish": ["bullish_fvg", "bullish_order_block", "bullish_ote_retracement"],
        "bearish": ["bearish_fvg", "bearish_order_block", "bearish_ote_retracement"],
    },
    "manipulation_to_distribution": {
        "bullish": ["bullish_ifvg", "bullish_breaker", "bullish_fvg"],
        "bearish": ["bearish_ifvg", "bearish_breaker", "bearish_fvg"],
    },
    "failed_breakout_reversal": {
        "bullish": ["bullish_breaker", "bullish_ifvg", "bullish_rejection_block"],
        "bearish": ["bearish_breaker", "bearish_ifvg", "bearish_rejection_block"],
    },
    "opening_drive": {
        "bullish": ["bullish_opening_fvg", "bullish_opening_order_block", "bullish_fvg"],
        "bearish": ["bearish_opening_fvg", "bearish_opening_order_block", "bearish_fvg"],
    },
    "range_expansion": {
        "bullish": ["bullish_range_break_retest", "bullish_fvg", "bullish_ote_retracement"],
        "bearish": ["bearish_range_break_retest", "bearish_fvg", "bearish_ote_retracement"],
    },
}


# ── Import-time validation ────────────────────────────────────────────────────

def _validate_tool_lists() -> None:
    """
    Asserts every tool in _ELIGIBLE and _PREFERRED is in VALID_TOOLS.
    Raises ValueError immediately at import so drift is caught during development,
    not silently at runtime.
    """
    for table_name, table in (("_ELIGIBLE", _ELIGIBLE), ("_PREFERRED", _PREFERRED)):
        for playbook, dirs in table.items():
            for direction, tools in dirs.items():
                for tool in tools:
                    if tool not in VALID_TOOLS:
                        raise ValueError(
                            f"[tool_library] Non-canonical tool '{tool}' found in "
                            f"{table_name}['{playbook}']['{direction}']. "
                            f"Add it to VALID_TOOLS or use normalize_tool()."
                        )


_validate_tool_lists()


# ── Public accessors ──────────────────────────────────────────────────────────

def eligible_tools(playbook: str, direction: str) -> list:
    """Return canonical eligible tools for *playbook* + *direction*."""
    if direction not in ("bullish", "bearish"):
        return []
    return _ELIGIBLE.get(playbook, {}).get(direction, [])


def preferred_tools(playbook: str, direction: str) -> list:
    """Return the top preferred canonical tools for *playbook* + *direction*."""
    if direction not in ("bullish", "bearish"):
        return []
    return _PREFERRED.get(playbook, {}).get(direction, [])
