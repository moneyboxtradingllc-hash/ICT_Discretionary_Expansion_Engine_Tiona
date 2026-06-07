"""
AI Response Schema Validator — Phase 1N.
Validates external AI responses before they enter the confidence fusion pipeline.
Rejects any response that does not match the required schema.
"""

_VALID_DIRECTIONS = {"bullish", "bearish", "neutral", "conflicted"}

_REQUIRED_STR_FIELDS = (
    "market_story",
    "primary_thesis",
    "invalidation_thesis",
    "preferred_scenario",
    "alternative_scenario",
)


def validate_ai_response(response: dict) -> tuple[bool, str | None]:
    """
    Validate an external AI response against the required schema.
    Returns (is_valid, reason_if_invalid).
    Returns (True, None) if the response is valid.
    Returns (False, reason) if validation fails — caller should fall back to deterministic AI.
    """
    if not isinstance(response, dict):
        return False, "response is not a dict"

    if not isinstance(response.get("agreement_with_playbook"), bool):
        return False, "agreement_with_playbook must be bool"

    if not isinstance(response.get("agreement_with_risk"), bool):
        return False, "agreement_with_risk must be bool"

    direction = response.get("ai_direction")
    if direction not in _VALID_DIRECTIONS:
        return False, f"ai_direction '{direction}' not in {sorted(_VALID_DIRECTIONS)}"

    confidence = response.get("ai_confidence")
    if not isinstance(confidence, int) or not (0 <= confidence <= 100):
        return False, f"ai_confidence must be int 0-100, got {confidence!r}"

    if not isinstance(response.get("concerns"), list):
        return False, "concerns must be a list"

    if not isinstance(response.get("missing_evidence"), list):
        return False, "missing_evidence must be a list"

    for field in _REQUIRED_STR_FIELDS:
        if not isinstance(response.get(field), str):
            return False, f"{field} must be a str, got {type(response.get(field)).__name__}"

    return True, None
