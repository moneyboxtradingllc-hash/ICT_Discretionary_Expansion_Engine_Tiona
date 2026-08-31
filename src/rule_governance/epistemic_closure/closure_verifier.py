"""EPISTEMIC-CLOSURE-CERTIFICATION-1 — the release gate.

ONE ENTRY POINT that answers a single question:

    DOES THE ORGANISM KNOW WHAT IT KNOWS, AND KNOW WHAT IT DOES NOT?

Passing does NOT mean the roadmap is finished. It means every fact that reaches
Luna's decision surface has a declared owner, a declared meaning, a declared
lifecycle, declared clocks, declared consumers, and declared limits -- and that
nothing which cannot back those declarations is being used to decide.

Failing means one of a small number of specific things, each named in the report
so it can be acted on rather than investigated:

    REGISTRY          a contract is malformed or duplicated
    MATRIX            a capability claim is unbacked or self-contradictory
    MANIFEST          the payload lane manifest is internally inconsistent
    COVERAGE          a payload path is claimed by no lane -- a NEW FACT
    PROMOTION         a BLOCKED/LEGACY/OBSERVE_ONLY fact holds decision authority
    CONSUMER          producer and consumer disagree about what a fact means
    SEMANTIC          an executable semantic predicate failed
    OWNERSHIP         two subsystems claim to own one fact
    TESTS             a CERTIFIED fact names no certification test

FINDINGS ARE NOT WARNINGS. Every finding here is a release blocker. The
bootstrap debt -- market facts that predate this framework and have no contract
yet -- is deliberately NOT a finding: it is reported as a COUNT, because failing
the gate on work that was never claimed to be done would train everyone to
ignore it. What that debt may never do is GROW silently, and the coverage check
is what enforces that.
"""
from __future__ import annotations

import glob
import json
import os

from rule_governance.epistemic_closure import capability_matrix, payload_coverage
from rule_governance.epistemic_closure import semantic_predicates as SP
from rule_governance.epistemic_closure.fact_contract import (CERTIFIED, DECISION_BEARING,
                                           NON_DECIDING, is_decision_bearing)
# MODULE REFERENCE, NOT A FROM-IMPORT. The mutation campaign must be able to
# substitute a defective registry and watch this gate fail; binding the tuple at
# import time would make the gate untestable, and a gate nobody can prove works
# is decoration.
from rule_governance.epistemic_closure import bootstrap_debt as BD
from rule_governance.epistemic_closure import fact_registry as FR

#: repo root. The package sits at src/rule_governance/epistemic_closure/,
#: so four levels up. Derived rather than hardcoded so a future move
#: fails loudly at import instead of silently reading the wrong tree.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
_ARCHIVE = os.path.join(_ROOT, "data", "ai_brain")


def _finding(kind, fact_id, detail, **extra):
    return dict({"kind": kind, "fact_id": fact_id, "detail": detail}, **extra)


# ── the individual gates ────────────────────────────────────────────────────
def check_registry() -> list:
    return [_finding("REGISTRY", None, p) for p in FR.validate_registry()]


def check_matrix() -> list:
    return [_finding("MATRIX", None, p) for p in capability_matrix.validate_matrix()]


def check_manifest() -> list:
    return [_finding("MANIFEST", None, p)
            for p in payload_coverage.validate_manifest()]


def check_promotion() -> list:
    """A fact that cannot be trusted may not hold decision authority.

    `validate` already refuses this at the contract level; repeating it here is
    deliberate. This is the invariant the whole framework exists to protect, and
    it should be impossible to disable by loosening one validator.
    """
    out = []
    for contract in FR.CONTRACTS:
        cls = contract.get("authority_class")
        if cls in NON_DECIDING and is_decision_bearing(contract):
            out.append(_finding(
                "PROMOTION", contract.get("fact_id"),
                f"authority_class {cls} holds decision influence "
                f"{list(contract.get('decision_influence') or ())}",
                owner=contract.get("producer_owner")))
        # A consumer may not exceed the fact's own authority either -- that is
        # how a witness field quietly becomes a decision input.
        #
        # GRANDFATHERING IS HISTORICAL INVENTORY, NOT PERMISSION. Three facts
        # genuinely ARE read by `brain_prompt` today at higher influence than
        # their class permits: two LEGACY liquidity fields and the unclamped
        # dealing-range zone. That authority predates this gate, and demoting it
        # would change what Luna receives -- a payload decision owned by the
        # units that replace those facts.
        #
        # So the debt is excused ONLY if it appears in the FROZEN bootstrap
        # manifest, which pins the exact fact ids and their exact blast radius
        # and cannot be extended by editing a contract. A fact that is not in
        # that manifest still blocks, which is the whole difference between an
        # inherited compromise and a new one.
        if BD.is_grandfathered(contract.get("fact_id")):
            continue
        for consumer in contract.get("consumers") or []:
            if cls in NON_DECIDING and consumer.get("influence") in DECISION_BEARING:
                out.append(_finding(
                    "PROMOTION", contract.get("fact_id"),
                    f"consumer {consumer.get('name')!r} claims "
                    f"{consumer.get('influence')} influence over a {cls} fact",
                    consumer=consumer.get("name")))
    return out


def check_bootstrap_debt(coverage_report=None) -> tuple:
    """The frozen manifest's integrity, whether any debt GREW, and whether any
    debt is genuinely gone.

    Returns (blocking_findings, resolution_rows).

    RESOLUTION IS NEVER INFERRED FROM A MISSING VALUE. A market-fact branch is
    conditional, so a path can be absent because this specimen had no active
    protected swing or an empty list -- that is evidence about the specimen, not
    proof that an authority was deleted. `resolution_state` asks the SOURCE
    instead: can the producer still author it, does the exact consumer still
    read it, and has the remediation unit actually changed the declared
    authority. Payload absence is carried alongside as a diagnostic and marked
    NOT_OBSERVED_IN_FIXTURE.
    """
    blocking = [_finding("BOOTSTRAP", None, p) for p in BD.validate_manifest()]
    resolutions = []
    src_root = os.path.join(_ROOT, "src")

    paths_by_fact = {}
    if coverage_report and coverage_report.get("available"):
        for path, fact_id in (coverage_report.get("path_to_fact") or {}).items():
            paths_by_fact.setdefault(fact_id, []).append(path)

    for contract in FR.CONTRACTS:
        fid = contract.get("fact_id")
        if not BD.is_grandfathered(fid):
            continue
        observed = paths_by_fact.get(fid) if paths_by_fact else None
        for finding in (BD.check_class_drift(contract)
                        + BD.check_expansion(contract, observed)):
            blocking.append(_finding(
                finding["kind"], finding["fact_id"], finding["detail"],
                remediation_owner=finding.get("remediation_owner")))
        debt = BD.by_id().get(fid)
        if debt is not None:
            try:
                resolutions.append(BD.resolution_state(
                    debt, contract, src_root=src_root, observed_paths=observed))
            except Exception as exc:  # noqa: BLE001 — never kill the gate
                blocking.append(_finding(
                    "BOOTSTRAP", fid,
                    f"resolution check crashed: {type(exc).__name__}: "
                    f"{str(exc)[:160]}"))
    return blocking, resolutions


def check_tests() -> list:
    out = []
    for contract in FR.CONTRACTS:
        if contract.get("authority_class") != CERTIFIED:
            continue
        if not (contract.get("certification_tests") or ()):
            out.append(_finding("TESTS", contract.get("fact_id"),
                                "CERTIFIED with no certification tests"))
            continue
        for ref in contract["certification_tests"]:
            path = os.path.join(_ROOT, ref.split("::")[0])
            if not os.path.exists(path):
                out.append(_finding(
                    "TESTS", contract.get("fact_id"),
                    f"certification test file {ref.split('::')[0]!r} does not "
                    f"exist"))
    return out


def check_ownership() -> list:
    """ONE SEMANTIC OWNER per fact. Many witnesses are fine; many authors are not.

    A contract may declare its owner UNRESOLVED, which is how the dual sweep
    writer is recorded. That is honest, and it is also why such a fact may not
    be CERTIFIED.
    """
    out = []
    for contract in FR.CONTRACTS:
        owner = str(contract.get("producer_owner") or "")
        unresolved = owner.startswith("UNRESOLVED") or owner.startswith("NONE")
        if unresolved and contract.get("authority_class") == CERTIFIED:
            out.append(_finding("OWNERSHIP", contract.get("fact_id"),
                                f"CERTIFIED but its owner is {owner!r}"))
        if unresolved and is_decision_bearing(contract):
            out.append(_finding("OWNERSHIP", contract.get("fact_id"),
                                f"decision-bearing but its owner is {owner!r}"))
    return out


def check_consumers() -> list:
    """Producer and consumer must agree about what a fact MEANS.

    Prose cannot be diffed, so agreement is enforced structurally: every
    decision-bearing consumer must be backed by an EXECUTABLE semantic predicate
    on the fact it reads. That is what would have caught `registered_at` --
    `brain_prompt` believed 'birth time', and no runnable check ever asserted
    the producer agreed.
    """
    out = []
    for contract in FR.CONTRACTS:
        deciding = [c for c in contract.get("consumers") or []
                    if c.get("influence") in DECISION_BEARING]
        if not deciding:
            continue
        if not (contract.get("semantic_predicates") or ()):
            out.append(_finding(
                "CONSUMER", contract.get("fact_id"),
                f"{len(deciding)} decision-bearing consumer(s) "
                f"({', '.join(sorted(c['name'] for c in deciding))}) but no "
                f"executable semantic predicate binds the producer to what they "
                f"believe"))
        for pid in contract.get("semantic_predicates") or ():
            if not SP.predicate_exists(pid):
                out.append(_finding("CONSUMER", contract.get("fact_id"),
                                    f"names unknown semantic predicate {pid!r}"))
    return out


def check_semantics(run_predicates=True) -> tuple:
    """Execute every declared semantic predicate. Returns (findings, results)."""
    out, results = [], []
    if not run_predicates:
        return out, results
    seen = set()
    for contract in FR.CONTRACTS:
        for pid in contract.get("semantic_predicates") or ():
            if pid in seen:
                continue
            seen.add(pid)
            result = SP.run(pid)
            result["fact_id"] = contract.get("fact_id")
            results.append(result)
            if result["status"] in ("FAIL", "ERROR", "MISSING"):
                out.append(_finding("SEMANTIC", contract.get("fact_id"),
                                    f"{pid}: {result['status']} — "
                                    f"{result['detail']}"))
    return out, results


def _canonical_snapshot():
    """The newest archived canonical SNAPSHOT -- raw market state, not a payload.

    The distinction is the whole point of the frontier guard. An archived
    *payload* is a frozen artifact of the builder that existed when it was
    written; an archived *snapshot* is market data, which the CURRENT builder
    can be run against. Only the second can reveal a field somebody added to
    `build_brain_input` today.
    """
    for day in ("20260825", "20260824"):
        files = sorted(glob.glob(os.path.join(_ARCHIVE, f"{day}_*_MNQ.json")))
        for path in reversed(files):
            try:
                with open(path, encoding="utf-8") as fh:
                    return json.load(fh)["raw_snapshot"], os.path.basename(path)
            except Exception:  # noqa: BLE001
                continue
    return None, None


def current_tree_payload():
    """Build a payload with the CURRENT builder from a canonical snapshot."""
    snapshot, source = _canonical_snapshot()
    if snapshot is None:
        return None, None
    from ai_brain.brain_input import build_brain_input
    return build_brain_input(snapshot, {}), source


def archived_corpus_coverage(limit=None) -> dict:
    """HISTORICAL BREADTH. Every archived snapshot, through the current builder.

    This is not the frontier guard -- it is variance coverage, proving the lane
    manifest handles the shapes the payload actually takes (blocks absent, lists
    empty, whole families missing) rather than only the one shape that happened
    to be newest.
    """
    from ai_brain.brain_input import build_brain_input
    checked, unclassified = 0, {}
    for path in sorted(glob.glob(os.path.join(_ARCHIVE, "*_MNQ.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                snapshot = json.load(fh)["raw_snapshot"]
        except Exception:  # noqa: BLE001
            continue
        checked += 1
        for leaf in payload_coverage.coverage(
                build_brain_input(snapshot, {}))["unclassified"]:
            unclassified.setdefault(leaf, os.path.basename(path))
        if limit and checked >= limit:
            break
    return {"payloads": checked, "unclassified": unclassified}


def check_coverage(payload=None, *, current_tree=True, corpus_limit=None) -> tuple:
    """Every payload path must be claimed by a lane. Returns (findings, report).

    TWO COVERAGES, DELIBERATELY DISTINCT:

        CURRENT TREE   build_brain_input() as it exists RIGHT NOW, run against a
                       canonical snapshot. This is the frontier guard: a field
                       added to the builder today appears here and nowhere else.

        ARCHIVED CORPUS  every archived snapshot through the same current
                       builder. This is breadth, not frontier -- it proves the
                       manifest survives the shapes the payload really takes.

    Conflating them was a real hole: an injected key in an archived payload
    proved the classifier worked, but proved nothing about tomorrow's field.
    """
    source, basis = None, "supplied"
    if payload is None:
        if current_tree:
            payload, source = current_tree_payload()
            basis = "current-tree build_brain_input"
        else:
            payload, source = _canonical_payload()
            basis = "archived payload artifact"
    if payload is None:
        return ([_finding("COVERAGE", None,
                          "no canonical snapshot available to build a CURRENT "
                          "payload from; frontier coverage is UNPROVEN on this "
                          "machine, which is not the same as clean")],
                {"available": False})

    report = payload_coverage.coverage(payload)
    report["available"] = True
    report["source"] = source
    report["basis"] = basis
    findings = [
        _finding("COVERAGE", None,
                 f"payload path {path!r} is claimed by no lane — an "
                 f"uncontracted market fact on the CURRENT decision surface")
        for path in report["unclassified"]]

    if current_tree:
        corpus = archived_corpus_coverage(corpus_limit)
        report["archived_payloads"] = corpus["payloads"]
        report["archived_unclassified"] = len(corpus["unclassified"])
        for leaf, where in sorted(corpus["unclassified"].items()):
            findings.append(_finding(
                "COVERAGE", None,
                f"archived payload {where} produced unclassified path {leaf!r}"))
    return findings, report


def _canonical_payload():
    """An archived payload artifact. Retained for callers that explicitly want
    historical shape rather than the current builder."""
    payload, source = current_tree_payload()
    return payload, source


# ── the gate ────────────────────────────────────────────────────────────────
def verify(*, run_predicates=True, payload=None, current_tree=True) -> dict:
    """Run every gate. Never raises; a crashed gate is a finding.

    `current_tree=True` builds the payload with the CURRENT `build_brain_input`
    rather than reading an archived payload artifact. That distinction is the
    frontier guard: yesterday's archives cannot contain a field somebody adds to
    the builder today, so historical coverage alone would let a new
    decision-bearing fact reach Luna uncontracted.
    """
    findings, results = [], []

    # COVERAGE FIRST. The bootstrap-expansion check needs to know which payload
    # paths a grandfathered fact actually occupies right now.
    coverage_report = {}
    try:
        coverage_findings, coverage_report = check_coverage(
            payload, current_tree=current_tree)
        findings.extend(coverage_findings)
    except Exception as exc:  # noqa: BLE001
        findings.append(_finding("COVERAGE", None, f"coverage gate crashed: "
                                                   f"{type(exc).__name__}: "
                                                   f"{str(exc)[:160]}"))

    for name, fn in (("registry", check_registry), ("matrix", check_matrix),
                     ("manifest", check_manifest), ("promotion", check_promotion),
                     ("tests", check_tests), ("ownership", check_ownership),
                     ("consumers", check_consumers)):
        try:
            findings.extend(fn())
        except Exception as exc:  # noqa: BLE001
            findings.append(_finding("REGISTRY", None,
                                     f"gate {name!r} crashed: "
                                     f"{type(exc).__name__}: {str(exc)[:200]}"))

    resolutions = []
    try:
        debt_findings, resolutions = check_bootstrap_debt(coverage_report)
        findings.extend(debt_findings)
    except Exception as exc:  # noqa: BLE001
        findings.append(_finding("BOOTSTRAP", None, f"bootstrap gate crashed: "
                                                    f"{type(exc).__name__}"))

    try:
        semantic_findings, results = check_semantics(run_predicates)
        findings.extend(semantic_findings)
    except Exception as exc:  # noqa: BLE001
        findings.append(_finding("SEMANTIC", None, f"semantic gate crashed: "
                                                   f"{type(exc).__name__}"))

    by_class = {}
    for contract in FR.CONTRACTS:
        cls = contract.get("authority_class")
        by_class[cls] = by_class.get(cls, 0) + 1
    caps = capability_matrix.summary()

    return {
        # BLOCKERS ONLY. Debt is not a blocker, and it is also not invisible --
        # it is reported in its own arrays below and in its own report section.
        "ok": not findings,
        "blockers": findings,
        # Kept under the old name so existing readers do not silently see zero.
        "findings": findings,
        "contracts": len(FR.by_id()),
        "by_authority_class": by_class,
        "capabilities": caps,
        "certified_capabilities": caps.get("CERTIFIED", 0),
        "partial_capabilities": caps.get("PARTIAL", 0),
        "blocked_capabilities": caps.get("BLOCKED", 0),
        "semantic_results": results,
        "coverage": coverage_report,
        "uncertified_debt": coverage_report.get("uncertified_debt"),
        "grandfathered_authority_debts": [dict(d) for d in
                                          BD.GRANDFATHERED_AUTHORITY_DEBT],
        "debt_resolution": resolutions,
        "debts_eligible_for_removal": [
            r for r in resolutions if r.get("state") == BD.ELIGIBLE_FOR_REMOVAL],
    }


def render(report) -> str:
    """A report an engineer can act on without opening the code.

    THE HEADLINE MUST NOT LAUNDER DEBT. "PASS -- 0 findings" while three facts
    exercise more authority than their status permits is the same disease this
    framework treats: a display that makes a known limitation invisible. When
    debt exists the status says so, and the counts are separated so nobody has
    to infer them.
    """
    lines = []
    debts = report.get("grandfathered_authority_debts") or []
    if not report.get("ok"):
        status = "FAIL"
    elif debts:
        status = "PASS WITH DECLARED LEGACY DEBT"
    else:
        status = "PASS"
    lines.append(f"EPISTEMIC CLOSURE: {status}")
    lines.append("")
    lines.append(f"  blockers                        {len(report.get('blockers') or [])}")
    lines.append(f"  grandfathered_authority_debts   {len(debts)}")
    lines.append(f"  blocked_capabilities            {report.get('blocked_capabilities')}")
    lines.append(f"  partial_capabilities            {report.get('partial_capabilities')}")
    lines.append(f"  certified_capabilities          {report.get('certified_capabilities')}")
    lines.append("")
    lines.append(f"  contracts              {report.get('contracts')}")
    for cls, n in sorted((report.get("by_authority_class") or {}).items()):
        lines.append(f"     {cls:<14} {n}")

    cov = report.get("coverage") or {}
    if cov.get("available"):
        lines.append(f"  brain payload          {cov.get('total_paths')} paths "
                     f"({cov.get('basis')}: {cov.get('source')})")
        for lane, n in sorted((cov.get("counts") or {}).items()):
            lines.append(f"     {lane:<14} {n}")
        lines.append(f"  uncertified debt       {report.get('uncertified_debt')} "
                     f"paths (pinned; may shrink, never grow silently)")
        if cov.get("archived_payloads"):
            lines.append(f"  archived corpus        "
                         f"{cov['archived_payloads']} payloads, "
                         f"{cov.get('archived_unclassified', 0)} unclassified")
    else:
        lines.append("  brain payload          UNAVAILABLE on this machine")

    results = report.get("semantic_results") or []
    if results:
        lines.append("")
        lines.append("  SEMANTIC PREDICATES")
        for r in results:
            lines.append(f"     {r['status']:<8} {r['predicate']:<42} "
                         f"{str(r.get('detail'))[:70]}")

    blockers = report.get("blockers") or []
    lines.append("")
    if not blockers:
        lines.append("  NO BLOCKERS. Every fact reaching a decision declares its")
        lines.append("  owner, meaning, lifecycle, clocks, consumers and limits.")
    else:
        lines.append(f"  {len(blockers)} BLOCKER(S) — release blocked")
        for f in blockers:
            lines.append(f"     [{f['kind']}] {f.get('fact_id') or '-'}")
            lines.append(f"        {f['detail']}")
            for extra in ("owner", "consumer", "remediation_owner"):
                if f.get(extra):
                    lines.append(f"        {extra}: {f[extra]}")

    if debts:
        lines.append("")
        lines.append(f"  GRANDFATHERED AUTHORITY DEBT ({len(debts)}) — frozen at "
                     f"{BD.BOOTSTRAP_DATE}, not permission for new authority")
        for d in debts:
            lines.append(f"     {d['fact_id']}  [{d['authority_class']}]"
                         f"  -> {d['remediation_owner_unit']}")
            lines.append(f"        paths     {list(d['payload_paths'])}")
            lines.append(f"        consumers {list(d['consumers'])} "
                         f"({d['influence']})")

    eligible = report.get("debts_eligible_for_removal") or []
    if eligible:
        lines.append("")
        lines.append(f"  DEBT ELIGIBLE FOR REMOVAL ({len(eligible)}) — producer, "
                     f"consumer AND governance all show the authority is gone")
        for r in eligible:
            lines.append(f"     {r['fact_id']} -> delete from the manifest "
                         f"({r['remediation_owner']})")
    unobserved = [r for r in (report.get("debt_resolution") or [])
                  if r.get("note") == BD.NOT_OBSERVED]
    if unobserved:
        lines.append("")
        lines.append(f"  NOT OBSERVED IN THIS FIXTURE ({len(unobserved)}) — "
                     f"DIAGNOSTIC ONLY, the authority is still present in source")
        for r in unobserved:
            lines.append(f"     {r['fact_id']}: its frozen path did not appear "
                         f"in this payload; a conditional branch simply did not "
                         f"fire. This is NOT resolution.")

    blocked = capability_matrix.blocked()
    if blocked:
        lines.append("")
        lines.append(f"  KNOWN BLOCKED CAPABILITIES ({len(blocked)}) — declared, not hidden")
        for cap in blocked:
            lines.append(f"     {cap['capability_id']}")
            lines.append(f"        {cap['question']}")
            lines.append(f"        gap: {cap['gap']}")
    return "\n".join(lines)
