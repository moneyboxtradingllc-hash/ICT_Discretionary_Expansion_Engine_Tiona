"""
AI-BRAIN-REQUIRED (2026-07-10) — the Brain-availability operating policy.

Doctrine (Maurice): for an AI-sovereign paper session, silent deterministic
fallback CHANGES THE ORGANISM BEING TESTED. The session may stay safe, but its
results become behaviorally meaningless evidence. Therefore:

  * NEW JUDGMENT REQUIRES THE AI BRAIN — with AI_BRAIN_REQUIRED=true the
    session REFUSES TO START unless a live-model preflight succeeds (no quota,
    auth, or model-access error), and after N consecutive in-session Brain
    failures NEW-ENTRY authority is revoked (clone of the feed-failure
    pattern; restored on the next healthy Brain scan).
  * EXISTING-POSITION SAFETY NEVER DEPENDS ON THE BRAIN — revocation gates
    entries only; stops, position management, reconciliation, and EOD flatten
    run deterministically regardless.

Default AI_BRAIN_REQUIRED=false = byte-identical legacy (development
diagnostics keep the fallback). The FC launcher opts in.
"""
import os

# per-scan LLM health as recorded on snapshot["ai_brain"]["source"]
HEALTHY_SOURCE = "llm"
DEGRADED_SOURCES = ("llm_failed_fallback", "contaminated_input", "degraded",
                    "deterministic", "brain_disabled")


def brain_required() -> bool:
    return os.getenv("AI_BRAIN_REQUIRED", "false").lower().strip() == "true"


def max_consecutive_failures() -> int:
    try:
        return max(1, int(os.getenv("AI_BRAIN_REQUIRED_MAX_FAILURES", "5")))
    except (TypeError, ValueError):
        return 5


def preflight() -> dict:
    """One minimal live-model call. Returns
    {ok, model, classification: ok|quota|auth|model_access|transport|config,
     detail}. Never raises."""
    model = os.getenv("AI_BRAIN_MODEL", os.getenv("AI_MODEL", "gpt-4o-mini"))
    out = {"ok": False, "model": model, "classification": "transport",
           "detail": None}
    try:
        from ai_layer.ai_api_adapter import _openai, _OPENAI_AVAILABLE
    except Exception as exc:  # noqa: BLE001
        out.update(classification="config", detail=f"adapter_import:{exc}")
        return out
    if not _OPENAI_AVAILABLE:
        out.update(classification="config", detail="openai package unavailable")
        return out
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        out.update(classification="auth", detail="no OPENAI_API_KEY")
        return out
    try:
        client = _openai.OpenAI(api_key=key, timeout=15, max_retries=0)
        resp = client.chat.completions.create(
            model=model, max_tokens=5,
            messages=[{"role": "user", "content": "Reply with exactly: OK"}])
        content = (resp.choices[0].message.content or "").strip()
        out.update(ok=True, classification="ok", detail=content[:40])
        return out
    except Exception as exc:  # noqa: BLE001
        text = f"{type(exc).__name__}: {exc}"
        low = text.lower()
        if "insufficient_quota" in low or "exceeded your current quota" in low \
                or "billing" in low:
            cls = "quota"
        elif "401" in low or "invalid_api_key" in low or "authentication" in low \
                or "incorrect api key" in low:
            cls = "auth"
        elif "model" in low and ("does not exist" in low or "not found" in low
                                 or "access" in low):
            cls = "model_access"
        else:
            cls = "transport"
        out.update(classification=cls, detail=text[:200])
        return out


class BrainHealthGate:
    """In-session Brain availability gate (pure; scan_loop threads one).

    update(source) per scan; entry_allowed flips False after
    max_consecutive_failures degraded scans and back True on the first healthy
    scan. Gates NEW ENTRIES ONLY — the caller must never wire this into stop /
    position management (doctrine: existing-position safety never depends on
    the Brain)."""

    def __init__(self, threshold: int = None):
        self.threshold = threshold or max_consecutive_failures()
        self.consecutive_failures = 0
        self.entry_allowed = True

    def update(self, brain_source) -> dict:
        healthy = (str(brain_source or "").lower() == HEALTHY_SOURCE)
        revoked_now = restored_now = False
        if healthy:
            if not self.entry_allowed:
                restored_now = True
            self.consecutive_failures = 0
            self.entry_allowed = True
        else:
            self.consecutive_failures += 1
            if self.entry_allowed and self.consecutive_failures >= self.threshold:
                self.entry_allowed = False
                revoked_now = True
        return {
            "required": brain_required(),
            "brain_source": brain_source,
            "degraded": not healthy,
            "consecutive_failures": self.consecutive_failures,
            "threshold": self.threshold,
            "entry_allowed": self.entry_allowed,
            "revoked_now": revoked_now,
            "restored_now": restored_now,
            "positions_managed": True,   # constitutional: never Brain-dependent
        }
