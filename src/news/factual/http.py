"""The one outbound seam for NEWS-2. HTTP GET only; never raises.

Every source adapter receives a `fetch` callable with this signature, so tests
inject recorded payloads and no test ever touches the network. Nothing here can
write to any venue: it has no method but GET.
"""
from __future__ import annotations

import urllib.error
import urllib.request

#: Some agency servers (BLS in particular) refuse anonymous default agents.
#: A descriptive agent with a contact is what their access policy asks for.
DEFAULT_USER_AGENT = ("ms-juicy-news2/1.0 (read-only economic calendar fetch; "
                      "contact: repository owner)")


def fetch_text(url: str, *, timeout: float = 20.0, headers: dict = None) -> dict:
    """GET `url`. Returns {ok, status, text, error, url}; never raises."""
    hdrs = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "*/*"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, headers=hdrs, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:   # noqa: S310
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            return {"ok": True, "status": resp.status, "url": url,
                    "text": raw.decode(charset, errors="replace"), "error": None}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "url": url, "text": None,
                "error": f"HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001 -- a failed source is a FACT, not a crash
        return {"ok": False, "status": None, "url": url, "text": None,
                "error": f"{type(exc).__name__}: {exc}"}


def redact(url: str) -> str:
    """A reference safe to persist: API keys never reach a report or file."""
    import re
    return re.sub(r"(api_key|token|apikey)=[^&]+", r"\1=REDACTED", url or "")
