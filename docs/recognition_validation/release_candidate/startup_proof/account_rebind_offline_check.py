"""Offline evidence for stage5_account_rebind.zsh. Stubs only: no network, no operator data.

    PYTHONPATH= python3 -I account_rebind_offline_check.py <frozen ffe00ae checkout> [evidence.json]

Executes the exact Python body embedded in the helper (between its REBIND BODY markers) against the frozen
source's real TopstepXClient and pin law, with a stub HTTP transport. Exported evidence holds scenario names,
pass/fail and request counts only: no ids, names, account lists, fingerprints or credentials.
"""
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
HELPER = HERE / "stage5_account_rebind.zsh"
REPO = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(REPO / "src"))

from broker.topstepx_client import TopstepXClient, TopstepXError, TopstepXRateLimited  # noqa: E402
from broker.topstepx_redaction import account_fingerprint  # noqa: E402

text = HELPER.read_text()
body = text.split("# --- REBIND BODY", 1)[1].split("# --- END REBIND BODY ---", 1)[0]
body = body.split("\n", 1)[1]
ns = {"__name__": "rebind_body"}
exec(compile(body, str(HELPER) + "#REBIND_BODY", "exec"), ns)

INTENDED = {"id": 70001, "name": "SYNTH-INTENDED-50K-0001", "balance": 50000.0, "canTrade": True,
            "isVisible": True, "simulated": True}
OTHER = {"id": 70002, "name": "SYNTH-OTHER-150K-0002", "balance": 150000.0, "canTrade": True,
         "isVisible": True, "simulated": True}
ENV0 = ("TOPSTEPX_USERNAME=synthetic-user\nTOPSTEPX_API_KEY=synthetic-key\n# comment\n"
        "TOPSTEPX_ACCOUNT_ID=69999\nTOPSTEPX_ACCOUNT_FINGERPRINT=acct:000000000000\nOTHER_SETTING=1\n")


def stub_http(accounts, search_error=None, login_ok=True):
    calls = []

    def http(url, payload, headers, timeout):
        calls.append(url.rsplit("/api", 1)[1])
        if url.endswith("/api/Auth/loginKey"):
            if not login_ok:
                raise TopstepXError(f"HTTP 401 from {url}: bad key")
            return {"success": True, "token": "synthetic-token"}
        if url.endswith("/api/Account/search"):
            if search_error is not None:
                raise search_error(url)
            return {"success": True, "accounts": [dict(a) for a in accounts]}
        raise AssertionError(f"unexpected endpoint {url}")

    http.calls = calls
    return http


def answers(*seq):
    it = iter(seq)
    return lambda prompt: next(it)


def scenario(accounts, typed, *, search_error=None, login_ok=True, select=None):
    with tempfile.TemporaryDirectory() as d:
        envp = os.path.join(d, ".env")
        Path(envp).write_text(ENV0)
        http = stub_http(accounts, search_error, login_ok)
        guarded = ns["budget_transport"](http)
        saved = ns["select_intended"]
        if select is not None:
            ns["select_intended"] = select
        try:
            rc = ns["run"](envp, transport=guarded, ask=answers(*typed), say=lambda s: None)
        finally:
            ns["select_intended"] = saved
        after = Path(envp).read_text()
        _, vals = ns["read_env"](envp)
        backups = [f for f in os.listdir(d) if f.startswith(".env.before_rebind_")]
        return {"rc": rc, "unchanged": after == ENV0 and not backups, "backups": len(backups),
                "vals": vals, "http": list(http.calls), "accounts": accounts}


def bound_to(res, acct):
    """Activated intended-account assertion: id AND canonical fingerprint are the intended object's, and the
    frozen pin law accepts the written binding against the same account list."""
    v = res["vals"]
    if v.get("TOPSTEPX_ACCOUNT_ID") != str(acct["id"]):
        return False
    if v.get("TOPSTEPX_ACCOUNT_FINGERPRINT") != account_fingerprint(acct["id"], acct["name"]):
        return False
    c = TopstepXClient("u", "k", transport=stub_http(res["accounts"]))
    pinned = c.pin_account(account_id=int(v["TOPSTEPX_ACCOUNT_ID"]),
                           expected_fingerprint=v["TOPSTEPX_ACCOUNT_FINGERPRINT"])
    return pinned.id == acct["id"]


def refused(res):
    return res["rc"] == 1 and res["unchanged"]


OK = ("SYNTH-INTENDED-50K-0001", "GO", "YES")
checks = {}

r = scenario([OTHER, INTENDED], OK)
checks["healthy: intended selected by exact name, YES, bound, pin accepts"] = (
    r["rc"] == 0 and r["backups"] == 1 and bound_to(r, INTENDED) and r["vals"]["OTHER_SETTING"] == "1")
checks["healthy: exactly one login and one account-list request"] = r["http"] == ["/Auth/loginKey", "/Account/search"]

r = scenario([INTENDED, OTHER], OK)
checks["reordered list [intended, other]: same intended binding"] = r["rc"] == 0 and bound_to(r, INTENDED)

r1 = scenario([INTENDED, OTHER], ("", "GO", "YES"))
r2 = scenario([OTHER, INTENDED], OK)
checks["Codex reproduction shape: refused first run, reordered second query, intended still bound"] = (
    refused(r1) and r2["rc"] == 0 and bound_to(r2, INTENDED))
checks["no name typed: refused before any request"] = refused(r1) and r1["http"] == []

dup = dict(OTHER, name=INTENDED["name"])
r = scenario([INTENDED, dup], OK)
checks["ambiguous (two accounts with the intended name): refused, nothing changed"] = refused(r)

r = scenario([OTHER], OK)
checks["intended account disappeared (sole eligible is another): refused, never chosen"] = refused(r)

r = scenario([OTHER, INTENDED], ("SYNTH-INTENDED-50K-000", "GO", "YES"))
checks["invalid selection (name not exact): refused"] = refused(r)

r = scenario([OTHER, dict(INTENDED, canTrade=False)], OK)
checks["invalid selection (intended canTrade=False): refused"] = refused(r)

r = scenario([OTHER, dict(INTENDED, isVisible=False)], OK)
checks["invalid selection (intended isVisible=False): refused"] = refused(r)

r = scenario([OTHER, INTENDED], ("SYNTH-INTENDED-50K-0001", "go", "YES"))
checks["GO not typed: refused before any request"] = refused(r) and r["http"] == []

r = scenario([OTHER, INTENDED], ("SYNTH-INTENDED-50K-0001", "GO", "yes please"))
checks["YES not typed: refused after the one read, nothing changed"] = refused(r) and len(r["http"]) == 2


def by_position(accounts, name):  # the defect: identity by position / sole eligibility
    return [a for a in accounts if a.can_trade and a.is_visible][0]


r = scenario([OTHER, INTENDED], OK, select=by_position)
checks["ACTIVATED CONTROL: position-based selection substitutes the other account and the assertion catches it"] = (
    r["rc"] == 0 and not bound_to(r, INTENDED) and bound_to(r, OTHER))

r = scenario([OTHER, INTENDED], OK, search_error=lambda u: TopstepXError(f"HTTP 401 from {u}: expired"))
checks["budget: HTTP 401 on the list -> SDK re-login refused by the guard before sending; 2 requests; nothing changed"] = (
    refused(r) and r["http"] == ["/Auth/loginKey", "/Account/search"])

r = scenario([OTHER, INTENDED], OK, search_error=lambda u: TopstepXRateLimited(f"HTTP 429 from {u}", 1.0))
checks["budget: HTTP 429 -> no retry; 2 requests; nothing changed"] = refused(r) and len(r["http"]) == 2

r = scenario([OTHER, INTENDED], OK, search_error=lambda u: TopstepXError(f"HTTP 503 from {u}: down"))
checks["budget: HTTP 503 -> no retry; 2 requests; nothing changed"] = refused(r) and len(r["http"]) == 2

r = scenario([OTHER, INTENDED], OK, login_ok=False)
checks["budget: login refused -> 1 request; nothing changed"] = refused(r) and r["http"] == ["/Auth/loginKey"]

# Why a guard is needed: the SDK's default policy turns one accounts() call into several requests.
sdk_default = {}
for label, err in (("429", lambda u: TopstepXRateLimited(f"HTTP 429 from {u}", 0.0)),
                   ("503", lambda u: TopstepXError(f"HTTP 503 from {u}: down")),
                   ("401", lambda u: TopstepXError(f"HTTP 401 from {u}: expired"))):
    http = stub_http([INTENDED], err)
    try:
        TopstepXClient("u", "k", transport=http, sleep=lambda s: None).accounts(only_active=True)
    except Exception:  # noqa: BLE001
        pass
    sdk_default[label] = {"login": http.calls.count("/Auth/loginKey"), "account_search": http.calls.count("/Account/search")}

passed = all(checks.values())
evidence = {
    "helper": str(HELPER.relative_to(HERE.parents[3])),
    "helper_sha256": hashlib.sha256(HELPER.read_bytes()).hexdigest(),
    "executed_body_sha256": hashlib.sha256(body.encode()).hexdigest(),
    "frozen_source_head": os.popen(f"git -C '{REPO}' rev-parse HEAD").read().strip(),
    "live_calls": 0,
    "checks": checks,
    "sdk_default_requests_for_one_accounts_call_without_guard": sdk_default,
    "result": "PASS" if passed else "FAIL",
}
for k, v in checks.items():
    print(f"[{'x' if v else ' '}] {k}")
print("SDK default (no guard), requests for ONE accounts() call:", sdk_default)
print("RESULT:", evidence["result"])
if len(sys.argv) > 2:
    Path(sys.argv[2]).write_text(json.dumps(evidence, indent=2) + "\n")
sys.exit(0 if passed else 1)
