"""
Playbook Library — playbook names only.

Tool eligibility and preferred-tool data have been consolidated into
toolbox.tool_library, which is the single source of truth for canonical
tool names.  This module re-exports eligible_tools() and preferred_tools()
so that existing callers (playbook_classifier) need no import changes.
"""

from toolbox.tool_library import eligible_tools, preferred_tools  # re-export

PLAYBOOK_NAMES = [
    "liquidity_sweep_reversal",
    "trend_continuation",
    "manipulation_to_distribution",
    "failed_breakout_reversal",
    "opening_drive",
    "range_expansion",
]
