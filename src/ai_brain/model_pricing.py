"""Single source of truth for model pricing and usage-based cost.

One table, one calculator. Pricing was previously inlined in `luna_health`, and
a stale copy there produced a cost estimate roughly 5x too high (2026-08-04:
$1.00/$6.00 per 1M quoted against the correct $0.20/$1.20). Duplicated pricing
is guaranteed to drift, and a cost figure nobody can trace is worse than none.

Cost is always computed FROM RETURNED USAGE FIELDS — never from an assumed
token count. If the provider says a call used 400 cached input tokens, that is
what gets billed at the cached rate.
"""
from __future__ import annotations

# USD per 1,000,000 tokens. Official standard pricing, operator-supplied
# 2026-08-04. `cached_input` applies to the cached portion of the prompt.
PRICING = {
    "gpt-5.6-luna": {"input": 0.20, "cached_input": 0.02, "output": 1.20},
    "gpt-5.6-terra": {"input": 2.50, "cached_input": 0.25, "output": 15.00},
    "gpt-5.6-sol":  {"input": 5.00, "cached_input": 0.50, "output": 30.00},
    "gpt-5.4-mini": {"input": 0.75, "cached_input": 0.075, "output": 4.50},
}

# MODEL-IDENTITY-CONSISTENCY-1 (2026-08-20). This module used to declare its
# OWN `PRODUCTION_MODEL`, set to "gpt-5.6-terra" by the 2026-08-06 Terra
# migration. The operator's 2026-08-19 ruling moved production to Luna and
# updated `ai_brain.production_model` -- but not this copy. The repository then
# held two constants with the same name and OPPOSITE values:
#
#     ai_brain/production_model.py    PRODUCTION_MODEL = "gpt-5.6-luna"
#     ai_brain/model_pricing.py       PRODUCTION_MODEL = "gpt-5.6-terra"
#
# Live authorship stayed correct, because the execution lane reads the canonical
# owner. What broke was everything that trusted THIS one: `cost_from_usage`
# billed Luna traffic at Terra's rate -- 12.5x on both input and output -- and
# any module importing both names got whichever import came second. In
# `test_topstepx_execution_runner` that shadowing rejected every candidate as
# foreign-authored, leaving 44 tests of the execution path silently dark.
#
# A duplicated identity drifts for exactly the reason duplicated pricing drifts,
# which this module's own docstring already knew. So there is no second literal
# here to fall out of date: the canonical owner is imported, and pricing follows
# the production ruling automatically.
from ai_brain.production_model import PRODUCTION_MODEL  # noqa: F401 — re-export


class UnknownModelPricing(KeyError):
    """No pricing on file. Callers must refuse to guess a cost."""


def pricing_for(model: str) -> dict:
    try:
        return PRICING[model]
    except KeyError:
        raise UnknownModelPricing(
            f"no pricing on file for {model!r}; refusing to invent a cost") from None


def cost_from_usage(usage: dict, model: str = PRODUCTION_MODEL) -> dict:
    """Dollar cost from a provider usage block. Never raises.

    Handles the OpenAI shape: `prompt_tokens`, `completion_tokens`,
    `prompt_tokens_details.cached_tokens`,
    `completion_tokens_details.reasoning_tokens`. Reasoning tokens are already
    counted inside `completion_tokens`, so they are reported but not re-billed —
    double-counting them would silently inflate every estimate.
    """
    try:
        p = pricing_for(model)
    except UnknownModelPricing as exc:
        return {"error": str(exc), "cost_usd": None, "model": model}
    try:
        u = usage or {}
        prompt = int(u.get("prompt_tokens") or 0)
        completion = int(u.get("completion_tokens") or 0)
        cached = int((u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
        reasoning = int((u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
        cached = min(cached, prompt)                 # a provider oddity must not go negative
        fresh = prompt - cached
        cost = (fresh * p["input"] + cached * p["cached_input"]
                + completion * p["output"]) / 1_000_000.0
        return {"model": model,
                "input_tokens": prompt, "cached_input_tokens": cached,
                "fresh_input_tokens": fresh, "output_tokens": completion,
                "reasoning_tokens": reasoning,
                "total_tokens": int(u.get("total_tokens") or (prompt + completion)),
                "cost_usd": round(cost, 6)}
    except Exception as exc:  # noqa: BLE001 — accounting must never fail a healthy call
        return {"error": f"cost_calc_failed:{type(exc).__name__}", "cost_usd": None,
                "model": model}


def estimate_session_cost(input_tokens: int, output_tokens: int, calls: int,
                          model: str = PRODUCTION_MODEL) -> dict:
    """Planning estimate. Explicitly assumes NO cache hits — the pessimistic side."""
    per_call = cost_from_usage(
        {"prompt_tokens": input_tokens, "completion_tokens": output_tokens}, model)
    if per_call.get("cost_usd") is None:
        return per_call
    return {"model": model, "calls": calls,
            "assumed_input_tokens": input_tokens,
            "assumed_output_tokens": output_tokens,
            "cost_per_call_usd": per_call["cost_usd"],
            "session_cost_usd": round(per_call["cost_usd"] * calls, 6),
            "assumes_no_cache_hits": True}
