"""The one real-provider transport for a released Mode C run (PREPARED, DISABLED).

Production's Brain request is built byte-for-byte by
`ai_brain.narrative_brain._call_llm` and arrives here only through the gateway
seam (`brain_gateway.BrainGateway._provider_request`) and the counted
`CurrentModelResponder` (authority admitted, worst case reserved). This module
adds exactly the last hop: the genuine OpenAI SDK client, pinned to the public
endpoint, with SDK retries disabled, sending the responder's payload once.

Nothing here can run on its own:
  * no credential is stored; the release supplies a callable that is read once,
    only after `ModelAuthority.admit()` has passed;
  * `CurrentExternalResponder` is the ONLY responder whose origin is
    CURRENT_EXTERNAL, and it refuses any transport that is not a genuine
    `OpenAIChatTransport` over the installed `openai` package with no injected
    HTTP client. A fake SDK, a mock HTTP transport, a scripted or historical
    responder can never be labelled fresh cognition;
  * an environment base-URL override or a non-public endpoint refuses.

Every SDK error is a `TransportError` (usage unknown): the reservation stays
charged in full and the run halts (see `CurrentModelResponder`).
"""
from __future__ import annotations

import contextlib
import importlib.util
import inspect
import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

from recognition_validation import contracts as C
from recognition_validation import ports as P
from recognition_validation.brain_gateway import (CurrentModelResponder, ProviderReply, TransportError)

ENDPOINT = "https://api.openai.com/v1"
#: The authorization's endpoint_identity must equal this exactly.
ENDPOINT_IDENTITY = "openai:chat.completions:" + ENDPOINT
_BASE_URL_ENV = ("OPENAI_BASE_URL", "OPENAI_API_BASE")
#: Parameters the payload may carry: production's create kwargs plus the
#: evaluation output cap. Anything else is refused rather than sent.
ALLOWED_PAYLOAD_KEYS = frozenset({"model", "messages", "timeout", "prompt_cache_key", "response_format",
                                  "max_completion_tokens", "extra_headers"})
#: The only header production adds (its own request identity, sent so a timeout still has an id we own).
ALLOWED_HEADERS = frozenset({"X-Client-Request-Id"})


def genuine_sdk(module) -> bool:
    """The installed `openai` package itself, not a stand-in object.

    The module must be the one the import system resolves and has loaded, from
    an installed site/dist-packages directory, and its client class must be
    defined inside that package. A module object merely named `openai` is not."""
    try:
        spec = importlib.util.find_spec("openai")
        client_file = inspect.getfile(module.OpenAI)
    except (ImportError, AttributeError, TypeError, ValueError):
        return False
    path = getattr(module, "__file__", None)
    if spec is None or not spec.origin or not isinstance(path, str) or path != spec.origin:
        return False
    package = Path(spec.origin).resolve().parent
    return (module is sys.modules.get("openai") and getattr(module, "__name__", None) == "openai"
            and Path(path).name == "__init__.py"
            and bool({"site-packages", "dist-packages"} & set(Path(path).parts))
            and callable(module.OpenAI) and Path(client_file).resolve().is_relative_to(package))


def _usage(usage) -> dict:
    """Provider usage, every billed class kept; missing fields stay None."""
    def get(obj, name):
        return getattr(obj, name, None) if not isinstance(obj, dict) else obj.get(name)
    prompt_details = get(usage, "prompt_tokens_details")
    completion_details = get(usage, "completion_tokens_details")
    return {"prompt_tokens": get(usage, "prompt_tokens"), "completion_tokens": get(usage, "completion_tokens"),
            "cached_tokens": get(prompt_details, "cached_tokens") if prompt_details is not None else None,
            "reasoning_tokens": (get(completion_details, "reasoning_tokens")
                                 if completion_details is not None else None)}


class OpenAIChatTransport:
    """`send(payload) -> ProviderReply` over `chat.completions`, exactly once."""

    endpoint_identity = ENDPOINT_IDENTITY

    def __init__(self, sdk, credential, *, timeout: float, http_client=None, environ=None):
        environ = os.environ if environ is None else environ
        for name in _BASE_URL_ENV:
            value = environ.get(name)
            C.require(value in (None, "", ENDPOINT), "ENDPOINT_OVERRIDE_REFUSED", "/" + name, str(value))
        C.require(callable(credential), "CREDENTIAL_PROVIDER_REQUIRED", "/credential")
        C.require(callable(getattr(sdk, "OpenAI", None)), "SDK_UNAVAILABLE", "/sdk")
        self.sdk, self.timeout = sdk, float(timeout)
        # Genuine only when this class builds the HTTP client itself: an injected
        # client (a test's mock transport) can never carry fresh cognition.
        self.genuine = genuine_sdk(sdk) and http_client is None
        self.sdk_version = getattr(sdk, "__version__", None)
        if http_client is None and callable(getattr(sdk, "DefaultHttpxClient", None)):
            # trust_env=False: no proxy, netrc or CA override is taken from the environment.
            http_client = sdk.DefaultHttpxClient(trust_env=False)
        kwargs = {"api_key": credential(), "base_url": ENDPOINT, "timeout": self.timeout, "max_retries": 0}
        if http_client is not None:
            kwargs["http_client"] = http_client
        self.client = sdk.OpenAI(**kwargs)
        # The SDK's own retry counter, read back: an implicit retry is an uncounted request.
        C.require(getattr(self.client, "max_retries", 0) == 0, "SDK_RETRY_UNCOUNTED", "/max_retries")
        self.sent = 0

    def send(self, payload: dict) -> ProviderReply:
        extra = sorted(set(payload) - ALLOWED_PAYLOAD_KEYS)
        C.require(not extra, "PAYLOAD_PARAMETER_UNEXPECTED", "/payload", ",".join(extra))
        C.require(isinstance(payload.get("max_completion_tokens"), int), "OUTPUT_CAP_ABSENT",
                  "/payload/max_completion_tokens")
        headers = sorted(set(payload.get("extra_headers") or {}) - ALLOWED_HEADERS)
        C.require(not headers, "PAYLOAD_HEADER_UNEXPECTED", "/payload/extra_headers", ",".join(headers))
        self.sent += 1
        try:
            raw = self.client.chat.completions.with_raw_response.create(**payload)
            response = raw.parse()
        except Exception as error:  # noqa: BLE001 -- every SDK failure has unknown usage
            raise TransportError(f"{type(error).__name__}: {error}") from error
        choice = (getattr(response, "choices", None) or [None])[0]
        message = getattr(choice, "message", None)
        usage = getattr(response, "usage", None)
        headers = getattr(raw, "headers", None) or {}
        reply = ProviderReply(content=str(getattr(message, "content", None) or ""),
                              served_model=getattr(response, "model", None) or None,
                              usage=_usage(usage) if usage is not None else {},
                              request_id=headers.get("x-request-id") or None,
                              response_id=getattr(response, "id", None) or None)
        reply.finish_reason = getattr(choice, "finish_reason", None)
        reply.service_tier = getattr(response, "service_tier", None)
        return reply


class CurrentExternalResponder(CurrentModelResponder):
    """The only CURRENT_EXTERNAL responder: genuine SDK transport or refusal."""

    origin = "CURRENT_EXTERNAL"

    def __init__(self, authority, ledger, transport, *, trajectory_id: str):
        C.require(isinstance(transport, OpenAIChatTransport) and transport.genuine, "WRONG_TRANSPORT_SEAM",
                  "/transport", "fresh cognition requires the genuine SDK transport")
        super().__init__(authority, ledger, transport, trajectory_id=trajectory_id)


class ProviderOnlyNetworkGuard(P.NetworkGuard):
    """The offline guard with exactly one exception: the pinned provider host.

    Name resolution is admitted only for the endpoint host and connections
    only to the addresses that resolution returned, on its port; everything
    else (venue, broker, any other host) is refused and recorded exactly as
    in the fully offline guard. Used only by a released run.
    """

    def __init__(self, endpoint: str = ENDPOINT):
        super().__init__()
        url = urlparse(endpoint)
        C.require(url.scheme == "https" and bool(url.hostname), "ENDPOINT_INVALID", "/endpoint", endpoint)
        self.host, self.port = url.hostname, url.port or 443
        self.allowed_addresses: set = set()
        self.admitted: list = []

    @contextlib.contextmanager
    def deny(self):
        original_connect = socket.socket.connect
        original_create = socket.create_connection
        original_getaddrinfo = socket.getaddrinfo
        guard = self

        def getaddrinfo(host, port, *args, **kwargs):
            if host == guard.host and int(port or 0) == guard.port:
                infos = original_getaddrinfo(host, port, *args, **kwargs)
                guard.allowed_addresses.update(info[4][0] for info in infos)
                guard.admitted.append(("getaddrinfo", repr(host)))
                return infos
            guard.attempts.append(("getaddrinfo", repr(host)))
            raise P.NetworkRefused(f"provider-only run refused name resolution for {host!r}")

        def connect(sock, address, *args, **kwargs):
            if (isinstance(address, tuple) and len(address) >= 2 and address[0] in guard.allowed_addresses
                    and address[1] == guard.port):
                guard.admitted.append(("connect", repr(address)))
                return original_connect(sock, address, *args, **kwargs)
            guard.attempts.append(("connect", repr(address)))
            raise P.NetworkRefused(f"provider-only run refused connect to {address!r}")

        def create_connection(address, *args, **kwargs):
            if isinstance(address, tuple) and address[0] == guard.host and address[1] == guard.port:
                guard.admitted.append(("create_connection", repr(address)))
                return original_create(address, *args, **kwargs)
            guard.attempts.append(("create_connection", repr(address)))
            raise P.NetworkRefused(f"provider-only run refused connection to {address!r}")
        socket.socket.connect = connect
        socket.create_connection = create_connection
        socket.getaddrinfo = getaddrinfo
        try:
            yield self
        finally:
            socket.socket.connect = original_connect
            socket.create_connection = original_create
            socket.getaddrinfo = original_getaddrinfo
