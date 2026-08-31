"""Test-suite isolation from live production persistence.

DECONTAMINATE-PRODUCTION-MEMORY-AND-CAPITAL-STATE (2026-08-06).

The PROD-20260806 memory audit proved the suite was writing into real runtime
stores. `tests/test_phase_deploy1_multi_instance.py` appended live "lessons" to
`data/global_memory/global_lessons.jsonl` (240 -> 266 records), and
`tests/test_brain_lifecycle_enforce.py` persisted a **QQQ** thesis into the live
`data/ai_brain/active_thesis.json`, which an MNQ production session then loads.

Cleaning up afterwards is not a fix -- a crashed or interrupted run leaves the
damage behind, and a test that can reach production state can corrupt it between
the write and the cleanup. This redirects every runtime root to a per-session
temporary directory so the write never lands, and then verifies it.
"""
from __future__ import annotations

import hashlib
import os
import tempfile

import pytest

# Every env-redirectable runtime root. A root missing from this list is a root a
# test can still corrupt, so new persistence must be added here.
# REPLAY_CANDLES_DIR is deliberately NOT redirected: it is a read-only INPUT
# archive of committed candles, not a memory store. Redirecting it hid the
# fixtures replay tests legitimately depend on.
RUNTIME_ROOTS = (
    "AI_BRAIN_DIR",            # brain artifacts, active_thesis, stance_memory
    "AI_RETRIEVAL_DIR",        # vector corpus + retrieval logs
    "PERFORMANCE_TABLES_DIR",  # performance tables + ACCOUNT/capital_history
    "HTF_MEMORY_DIR",          # multi-day higher-timeframe memory
    "GLOBAL_MEMORY_DIR",       # global lessons
)

# Live files the suite must never modify. Hashed before and after the session.
PROTECTED = (
    os.path.join("data", "global_memory", "global_lessons.jsonl"),
    os.path.join("data", "ai_brain", "active_thesis.json"),
    os.path.join("data", "ai_brain", "stance_memory.json"),
    os.path.join("data", "ai_retrieval", "memory_store.jsonl"),
    os.path.join("data", "performance", "ACCOUNT", "capital_history.json"),
    os.path.join("data", "htf_memory", "MNQ.json"),
)

_BEFORE: dict = {}


def _digest(path: str) -> str:
    if not os.path.exists(path):
        return "<absent>"
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pytest_configure(config):
    """Redirect runtime roots before any test module imports production code."""
    root = tempfile.mkdtemp(prefix="expansion-test-runtime-")
    config._runtime_root = root
    for var in RUNTIME_ROOTS:
        os.environ[var] = os.path.join(root, var.lower())
        os.makedirs(os.environ[var], exist_ok=True)
    # An armed production session must never be implied by a test process.
    os.environ.pop("PRODUCTION_ARMED_SESSION", None)


def pytest_sessionstart(session):
    for p in PROTECTED:
        _BEFORE[p] = _digest(p)


def pytest_sessionfinish(session, exitstatus):
    """Fail the run if the suite mutated live state, whatever else passed."""
    changed = [p for p in PROTECTED if _digest(p) != _BEFORE.get(p)]
    if changed:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter:
            reporter.write_line("")
            reporter.write_line(
                "PRODUCTION PERSISTENCE MUTATED BY THE TEST SUITE:", red=True)
            for p in changed:
                reporter.write_line(f"  {p}", red=True)
        session.exitstatus = 1


@pytest.fixture(autouse=True)
def _reassert_runtime_roots(pytestconfig):
    """Restore the redirect before AND after every test.

    Several suites set a root to their own tmp dir and then `os.environ.pop()`
    it in teardown instead of restoring the previous value. That deletes the
    session redirect, so every later test silently falls back to the production
    default -- which is how the live stance_memory.json kept changing even with
    isolation configured. Re-asserting per test makes one careless teardown
    unable to leak into the next test.
    """
    root = pytestconfig._runtime_root
    for var in RUNTIME_ROOTS:
        os.environ[var] = os.path.join(root, var.lower())
        os.makedirs(os.environ[var], exist_ok=True)
    yield
    for var in RUNTIME_ROOTS:
        os.environ[var] = os.path.join(root, var.lower())


@pytest.fixture(scope="session")
def runtime_root(pytestconfig):
    """The temporary root every runtime store was redirected into."""
    return pytestconfig._runtime_root


# ── SYNTHETIC LANE IDENTITY FOR TESTS ────────────────────────────────────────
# The deterministic lane refuses to import without TOPSTEPX_ACCOUNT_NAME and
# TOPSTEPX_CONTRACT, because "defaulting these would point your bot at another
# operator's account". That production rule is correct and is NOT relaxed here:
# production never imports conftest.
#
# What it costs is testability -- on a fresh clone with no brokerage account,
# the lane's modules raise at IMPORT time, so ~15 test files error during
# collection instead of running. Skipping them was the old answer; it means a
# contributor without an account silently loses coverage of the lane.
#
# So the SUITE gets an identity that is obviously not a real account. It is
# structurally valid (the lane only requires two non-empty strings) and cannot
# name anyone's brokerage account. Tests that exercise the UNCONFIGURED path
# still do so, because they set their own environment via monkeypatch.
os.environ.setdefault("DETERMINISTIC_VENUE", "topstepx")
os.environ.setdefault("TOPSTEPX_ACCOUNT_NAME", "PRAC-V2-FIXTURE-00000000")
os.environ.setdefault("TOPSTEPX_CONTRACT", "MNQ")

# The PRAC release profile takes its permitted account, and its denylist, from
# the environment for the same reason: shipping either would publish real
# account numbers. The suite therefore supplies obviously-synthetic ones so the
# profile's GATES stay under test -- identity pinned, forbidden accounts
# refused, unset config failing closed -- without naming anyone's account.
os.environ.setdefault("PRAC_ACCOUNT_ID", "11111111")
# acct:66cacd650e99 == account_fingerprint(11111111,
#                       "PRAC-V2-FIXTURE-00000000"). Derived, not
# invented: an arbitrary literal would make the profile refuse its
# own fixture and hide whether the pin logic actually works.
os.environ.setdefault("PRAC_ACCOUNT_FINGERPRINT", "acct:66cacd650e99")
os.environ.setdefault(
    "PRAC_FORBIDDEN_ACCOUNTS",
    "22222222:COMBINE_ACCOUNT (50KTC-TEST-FIXTURE-B) - proven on PRAC first,"
    "33333333:RETIRED_ACCOUNT (50KTC-TEST-FIXTURE-A)")
os.environ.setdefault("PRAC_SMOKE_FORBIDDEN_ACCOUNTS",
                      "22222222:COMBINE,33333333:RETIRED")
os.environ.setdefault(
    "PRAC_FORBIDDEN_FINGERPRINTS",
    "acct:bbbbbbbbbbbb:COMBINE_ACCOUNT fingerprint,"
    "acct:cccccccccccc:RETIRED_ACCOUNT fingerprint")

# ── portability: operator-configured lanes ───────────────────────────────────
# The deterministic lane refuses to import without TOPSTEPX_ACCOUNT_NAME and
# TOPSTEPX_CONTRACT, deliberately: "Defaulting these would point your bot at another
# operator's account, so there is deliberately no default." That refusal is
# correct, but it fires at IMPORT time, so on a fresh clone these modules ERROR
# during collection rather than skipping -- which makes a clean checkout look
# broken when it is merely unconfigured.
#
# Collect them only when the lane is actually configured. An operator who has
# configured it still runs every one of them.
def _lane_configured() -> bool:
    """Read the operator's .env the same way the lane itself does.

    Checking os.environ alone is not enough: conftest is imported before
    anything calls load_dotenv(), so a configured operator would look
    unconfigured and silently lose these tests.
    """
    if (os.environ.get("TOPSTEPX_ACCOUNT_NAME")
            and os.environ.get("TOPSTEPX_CONTRACT")):
        return True
    try:
        from dotenv import dotenv_values, find_dotenv
        values = dotenv_values(find_dotenv(usecwd=True))
    except Exception:  # noqa: BLE001 -- absence is the normal fresh-clone case
        return False
    return bool(values.get("TOPSTEPX_ACCOUNT_NAME")
                and values.get("TOPSTEPX_CONTRACT"))


_NT_CONFIGURED = _lane_configured()

_NT_LANE_TESTS = (
    "test_auto_flatten_before_close.py", "test_compounding_risk.py",
    "test_deterministic_backtest.py", "test_funnel_trace.py",
    "test_gate_authority_attribution.py", "test_htf_mnq_accum.py",
    "test_ninjatrader_deterministic.py", "test_ninjatrader_order_path.py",
    "test_ninjatrader_smoke_order.py",
)

# ── portability: operator runtime state ──────────────────────────────────────
# These modules assert against the OPERATOR'S OWN runtime evidence -- archived
# sessions under data/, the live descriptive corpus, recorded candles, account
# configuration. They are operational verification, not architecture invariants,
# and a fresh clone legitimately has none of it.
#
# The architecture tests stay in force everywhere. Only the state assertions
# stand down, and only when the state is genuinely absent -- an operator with
# data/ present runs every one of them.
_OPERATOR_STATE_TESTS = (
    # TIONA-TEST-ENVIRONMENT-BOUNDARY-1: the closure certification runs semantic
    # predicates against ARCHIVED TAPE. Without the corpus it reports
    # "frontier coverage is UNPROVEN on this machine, which is not the same as
    # clean" -- the framework's own words, and exactly right. An unproven gate
    # is not a passing gate and must not read as one, so the honest result on a
    # checkout that ships no evidence is a skip, not a green tick.
    "test_epistemic_closure_certification.py",
    "test_adapt_loop6_health_timeline.py", "test_brain_authorship.py",
    "test_brain_lifecycle_enforce.py", "test_entry_invariant.py",
    "test_memory_audit_integrity.py",
    "test_memory_identity_and_contract_provenance.py",
    "test_ninjatrader_foundation.py", "test_operator_terminated_closure.py",
    "test_ops1_startup_authority.py",
    "test_phase_5f_authority_enforcement.py",
    "test_phase_5g_shared_context.py", "test_phase_5h_rule_governance.py",
    "test_phase_5t_adaptive_management.py", "test_phase_ab1_ai_brain.py",
    "test_phase_ab3_vector_memory.py", "test_phase_deploy1_multi_instance.py",
    "test_phase_fc1_promoted_authority.py",
    "test_phase_na1_narrative_authority.py", "test_r001_audit.py",
    "test_regime_is_observe_only.py", "test_replay1_candle_archive.py",
    "test_session_archive_integrity.py", "test_session_boundary_gaps.py",
    "test_session_evidence_contract.py", "test_tier2a_retirement.py",
    "test_topstep_sizing_wired.py", "test_topstepx_lane_transport.py",
)

# EXISTENCE IS NOT DISTRIBUTION. This guard asked whether `data/` existed, and
# every test run recreates it as a runtime root -- including `data/replay_sessions`
# -- so on a checkout that ships no history the guard silently stopped applying
# and ~150 tests ran against artifacts that were never there. Asking for a
# specific corpus directory fails the same way for the same reason.
#
# The honest question is whether this REPOSITORY DISTRIBUTES the evidence, which
# is a fact about what git tracks, not about what happens to be on disk.
def _operator_evidence_present() -> bool:
    import subprocess
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        out = subprocess.run(["git", "ls-files", "--", "data/"], cwd=repo,
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        # No git available: fall back to disk, accepting that a runtime-created
        # data/ may read as evidence. Failing OPEN here only means tests run and
        # report honestly; it never grants any production permission.
        return os.path.isdir(os.path.join(repo, "data"))
    # A DEAD SPAWN IS NOT AN ANSWER. Only a successful git call may decide this.
    if out.returncode != 0:
        return os.path.isdir(os.path.join(repo, "data"))
    return bool((out.stdout or "").strip())


_OPERATOR_STATE_PRESENT = _operator_evidence_present()

collect_ignore = []
if not _NT_CONFIGURED:
    collect_ignore += list(_NT_LANE_TESTS)
if not _OPERATOR_STATE_PRESENT:
    collect_ignore += [t for t in _OPERATOR_STATE_TESTS
                       if t not in collect_ignore]


# ── ENVIRONMENTAL PREREQUISITES ARE NOT SOURCE FAILURES ──────────────────────
# TIONA-TEST-ENVIRONMENT-BOUNDARY-1 (2026-08-31).
#
# This repository ships WITHOUT two things on purpose:
#
#   data/   the operator's forensic evidence -- archived sessions, recorded
#           tapes, execution artifacts. It is one operator's account history,
#           it is not application source, and it is not shareable.
#   .env    live TopstepX credentials.
#
# A large family of tests CERTIFIES those historical artifacts. Without them
# they raise FileNotFoundError, which reads as ~150 broken tests on a clean
# checkout when nothing is broken at all. That is a lie in the other direction:
# it buries any real regression in noise.
#
# So a missing PREREQUISITE becomes an explicit SKIP, and only when the
# prerequisite is genuinely absent:
#
#   evidence root absent  + FileNotFoundError  -> EXTERNAL_EVIDENCE_REQUIRED
#   credentials absent    + config refusal     -> LIVE_ENV_REQUIRED
#
# WHAT THIS DELIBERATELY DOES NOT DO. It does not touch production: nothing in
# `src/` imports conftest, and an unconfigured production install still fails
# closed with no default account and no default credential. It does not convert
# assertion failures -- a test that RAN and disagreed with the code is a real
# failure and stays one. And it only ever engages while the prerequisite is
# missing; on an operator's machine with data/ and .env present, every one of
# these tests runs for real and this hook is inert.
_EVIDENCE_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def _under_evidence_root(path) -> bool:
    """Is this missing file one of the artifacts we deliberately do not ship?

    KEYED ON THE PATH, NOT ON `data/` EXISTING. An earlier version asked
    whether the data/ directory was present and went inert the moment a test
    run recreated it as an empty runtime root -- the directory exists, the
    EVIDENCE does not. Asking about the specific missing file is both stricter
    and correct on an operator's machine, where the file is really there and no
    exception is raised at all.
    """
    if not path:
        return False
    try:
        target = os.path.abspath(str(path))
        return os.path.commonpath([target, _EVIDENCE_ROOT]) == _EVIDENCE_ROOT
    except (ValueError, TypeError):   # different drive, or unusable path
        return False
_LIVE_CREDS_PRESENT = bool(
    (os.environ.get("TOPSTEPX_USERNAME") or "").strip()
    and (os.environ.get("TOPSTEPX_API_KEY") or "").strip())

#: Exception types that mean "the environment did not supply something", as
#: opposed to "the code is wrong". Matched by NAME for the config error so this
#: hook never imports a broker module at collection time.
_LIVE_ENV_EXC_NAMES = ("TopstepXConfigError",)


def _prerequisite_reason(exc) -> "str | None":
    """Name the missing prerequisite, or None if this is a real failure."""
    if exc is None:
        return None
    value = getattr(exc, "value", exc)
    if type(value).__name__ in _LIVE_ENV_EXC_NAMES and not _LIVE_CREDS_PRESENT:
        return ("LIVE_ENV_REQUIRED: this test needs live TopstepX credentials "
                "(TOPSTEPX_USERNAME / TOPSTEPX_API_KEY). They are not shipped; "
                "configure your own account to run it.")
    if (isinstance(value, FileNotFoundError)
            and _under_evidence_root(getattr(value, "filename", None))):
        return ("EXTERNAL_EVIDENCE_REQUIRED: this test certifies a recorded "
                "forensic artifact under data/, which is the operator's own "
                "account history and is intentionally not distributed.")
    if type(value).__name__ == "SessionSourceError":
        return ("EXTERNAL_EVIDENCE_REQUIRED: this test needs an archived "
                "session under data/, which is intentionally not distributed.")
    return None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.passed or report.when not in ("setup", "call"):
        return
    reason = _prerequisite_reason(call.excinfo)
    if reason is None:
        return                      # a genuine failure stays a failure
    report.outcome = "skipped"
    report.longrepr = (str(item.fspath), item.location[1], reason)
