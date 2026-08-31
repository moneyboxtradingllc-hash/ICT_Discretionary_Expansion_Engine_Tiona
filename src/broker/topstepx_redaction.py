"""TOPSTEPX-INTEGRATION — credential redaction primitives.

Every string that can reach a log line, an evidence artifact or a traceback
passes through here first. The rule this module enforces is blunt on purpose:
a secret is never *partially* shown. There is no "last four characters" mode,
because a partial reveal is still a reveal and it invites the habit.

What counts as secret in this venue:
  - TOPSTEPX_USERNAME  (the login name — Topstep treats it as an identifier,
                        and it is half of the loginKey payload)
  - TOPSTEPX_API_KEY   (the other half)
  - the JWT session token returned by /api/Auth/loginKey

Account *names* are not secrets in the same sense, but they identify the
operator's funded account, so evidence artifacts carry a stable redacted
identity instead of the raw name.
"""
from __future__ import annotations

import hashlib
import os
import re

# The literal we print in place of anything sensitive. One token, no variants,
# so a grep for it over an artifact finds every redaction site.
MASK = "[REDACTED]"

# TOPSTEPX_ACCOUNT_ID is not a credential — it cannot authenticate anything —
# but the mission forbids a full account number in any artifact, and the live
# 2026-08-04 preflight proved that a pin-failure message could carry it there.
# Redacting it defensively means a future code path that prints the id is
# caught by the layer rather than by the next audit.
_SECRET_ENV = ("TOPSTEPX_USERNAME", "TOPSTEPX_API_KEY", "TOPSTEPX_ACCOUNT_ID")

# A JWT is three base64url segments separated by dots. Matching the shape means
# a token is caught even when it arrives from somewhere we did not anticipate
# (an error body, a repr, a nested dict).
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\b")

# Bearer headers, whatever follows them.
_BEARER_RE = re.compile(r"(?i)\bBearer\s+\S+")


def _live_secrets() -> list[str]:
    """Current secret VALUES from the environment, longest first.

    Longest-first matters: if the username happened to be a substring of the
    API key, replacing the short one first would leave a fragment of the long
    one visible.
    """
    vals = [os.getenv(k, "").strip() for k in _SECRET_ENV]
    # A 1-2 character "secret" would turn every artifact into confetti; those
    # are configuration errors, not credentials, and the config loader rejects
    # them separately.
    return sorted((v for v in vals if len(v) >= 3), key=len, reverse=True)


def redact(text: object) -> str:
    """Return `text` as a string with every known secret replaced by MASK.

    Never raises: redaction that fails open would be worse than useless, so a
    conversion failure degrades to the mask rather than to the original value.
    """
    try:
        s = text if isinstance(text, str) else str(text)
    except Exception:  # noqa: BLE001 — a hostile __str__ must not leak or crash
        return MASK
    for secret in _live_secrets():
        if secret and secret in s:
            s = s.replace(secret, MASK)
    s = _JWT_RE.sub(MASK, s)
    s = _BEARER_RE.sub(f"Bearer {MASK}", s)
    return s


def redact_mapping(obj: object) -> object:
    """Deep-redact a JSON-ish structure for evidence artifacts.

    Keys whose NAME implies a secret are masked regardless of value shape, so a
    token nested inside an unexpected envelope is still caught.
    """
    secret_key = re.compile(r"(?i)(token|apikey|api_key|password|secret|authorization|username|userName)")
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if secret_key.search(str(k)):
                out[k] = MASK
            else:
                out[k] = redact_mapping(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [redact_mapping(v) for v in obj]
    if isinstance(obj, str):
        return redact(obj)
    return obj


def account_fingerprint(account_id: object, account_name: object = "") -> str:
    """A stable, non-reversible identity for an account.

    Evidence must let the operator confirm "the run pinned the account I meant"
    across sessions without the artifact carrying the account number. A salted
    digest would not be comparable between runs, so this is a plain digest of
    the identity — it proves sameness, never membership.
    """
    raw = f"{account_id}|{account_name}".encode("utf-8", "replace")
    return "acct:" + hashlib.sha256(raw).hexdigest()[:12]


def redacted_account_label(name: object) -> str:
    """Human-orientable account label that does not print the full name.

    Topstep account names look like 'PRACTICEJUL2612345' or '50KCOMBINE98765'.
    The trailing digits are the account number, so only the leading
    non-numeric class survives.
    """
    s = str(name or "")
    head = re.match(r"^[A-Za-z]+", s)
    return f"{head.group(0) if head else '?'}{MASK}"


def assert_clean(text: object, where: str = "output") -> str:
    """Redact, then verify nothing secret-shaped survived. Raises on failure.

    Used at artifact-write time so a leak fails the run loudly instead of
    landing on disk quietly.
    """
    s = redact(text)
    for secret in _live_secrets():
        if secret and secret in s:
            raise RuntimeError(f"redaction failed in {where}: a configured secret survived")
    if _JWT_RE.search(s):
        raise RuntimeError(f"redaction failed in {where}: a JWT-shaped string survived")
    return s
