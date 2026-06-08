"""
AI Connectivity Test — Phase 5E.3.
Reads AI configuration from .env and makes one minimal test request.
Read-only. No scan loop. No trading. No broker access.

Usage:
    python src/ai_layer/ai_connectivity_test.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from ai_layer.ai_api_adapter import call_external_ai, get_ai_config

_DIV = "=" * 50

_TEST_INPUT = {
    "timestamp": "connectivity_test",
    "session": "test",
    "market_context": {
        "narrative":        "neutral",
        "market_state":     "test",
        "directional_bias": "neutral",
        "confidence_score": 50,
        "confidence_tier":  "moderate",
        "warnings":         [],
    },
    "qualification": {
        "status":            "candidate",
        "grade":             "C",
        "direction":         "neutral",
        "opportunity_score": 50,
        "primary_driver":    "connectivity_test",
    },
    "playbook": {
        "selected":   "no_playbook",
        "status":     "no_playbook",
        "direction":  "neutral",
        "confidence": 0,
    },
    "risk": {
        "trade_allowed":    False,
        "risk_tier":        "blocked",
        "authority_reason": "connectivity test only",
        "blocks":           ["connectivity test — no real signal"],
        "restrictions":     [],
    },
    "toolbox": {
        "preferred_tool":                  None,
        "toolbox_status":                  "no_tool",
        "best_available_raw_status":       "no_tool",
        "best_available_effective_status": "no_tool",
        "candidates":                      [],
    },
    "memory":  {"available": False, "snapshot_count": 0},
    "po3":     {"alignment": ""},
    "structure":  {"alignment": "neutral"},
    "volatility": {},
    "expansion":  {},
    "liquidity":  [],
}


def run_connectivity_test() -> dict:
    cfg = get_ai_config()
    print(f"Provider  : {cfg['provider']}")
    print(f"Model     : {cfg['model']}")
    print(f"Timeout   : {cfg['timeout']}s")
    print(f"API Key   : {'present' if cfg['api_key_present'] else 'MISSING'}")
    print()

    if not cfg["api_key_present"]:
        print("RESULT: FAIL -- API key missing")
        return {"success": False, "reason": "api_key_missing"}

    print("Sending minimal test request ...")
    result = call_external_ai(_TEST_INPUT)

    success    = result.get("ai_external_success", False)
    latency    = result.get("latency_ms")
    model_used = result.get("model_used") or cfg["model"]
    err_type   = result.get("ai_external_error_type")
    err_msg    = result.get("ai_external_error_message_safe") or ""

    if success and result.get("response"):
        lat_str = f" | latency={latency}ms" if latency is not None else ""
        print(f"RESULT: SUCCESS | model={model_used}{lat_str}")
        return {"success": True, "model": model_used, "latency_ms": latency}
    else:
        lat_str = f" | latency={latency}ms" if latency is not None else ""
        print(f"RESULT: FAIL | model={cfg['model']} | reason={err_type} | detail={err_msg}{lat_str}")
        return {"success": False, "reason": err_type, "message": err_msg, "latency_ms": latency}


if __name__ == "__main__":
    print(_DIV)
    print("AI Connectivity Test -- Phase 5E.3")
    print(_DIV)
    print()
    outcome = run_connectivity_test()
    print()
    sys.exit(0 if outcome.get("success") else 1)
