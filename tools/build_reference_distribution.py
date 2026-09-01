"""Build a sanitized, portable reference distribution of this architecture.

BUILD-REFERENCE-DISTRIBUTION (2026-08-07).

Another operator runs her own Expansion Bot, her own Topstep account, her own
Combine and her own memory. She should inherit the ENGINEERING -- the canonical
objective bridge, fact parity, decision evidence, memory v2.2, closure and
provenance law -- without inheriting one byte of this operator's identity,
credentials, account state, memories or session history.

    TRANSFER ENGINEERING KNOWLEDGE AND CAPABILITY.
    DO NOT TRANSFER OPERATOR IDENTITY OR OPERATOR EXPERIENCE.

The export is an ALLOW-LIST walk, not a recursive copy with deletions after the
fact: a copy-then-delete build leaks whatever the deny-list forgot, and the
thing being exported is precisely the kind of data that must not leak once.

Runs read-only against the source repository.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import hashlib
import json
import os
import re
import shutil

#: Directories exported wholesale (still filtered file-by-file below).
ALLOW_DIRS = ("src", "tools", "tests", "docs")

#: Individual project files that are safe and useful.
ALLOW_FILES = ("requirements.txt", "pytest.ini", "setup.cfg", "pyproject.toml",
               ".gitignore", ".env.template", "README.md", "CLAUDE.md",
               "conftest.py")

#: Never exported, whatever directory they appear in.
DENY_NAMES = (".env", ".env.local", ".env.production", "credentials.json",
              "token.json", "memory_store.jsonl")
DENY_GLOBS = ("*.pem", "*.key", "*.p12", "*.pfx", "*.jwt", "*_token*",
              "*credential*", "*secret*", "*.log", "*.sqlite", "*.db",
              "session_auth_*.json", "*.pyc")
DENY_DIR_PARTS = (".git", "__pycache__", ".pytest_cache", ".venv", "venv",
                  "node_modules", ".idea", ".vscode", "data", "logs",
                  "htmlcov", ".mypy_cache", ".ruff_cache")

#: Documentation naming a specific operator session is that operator's private
#: record, not shared architecture -- Markdown is not a safety property.
DENY_DOC_PATTERNS = ("PROD-2026", "SESSION_REPORT", "MEMORY_AUDIT",
                     "MEMORY_AUTHORING", "MEMORY_DRY_RUN")

#: Substrings that mark operator identity/state. Their PRESENCE in an exported
#: file is a build failure, not a warning.
#: OPERATOR IDENTITY IS SUPPLIED, NOT BUILT IN. This tuple used to name one
#: operator's handle and email literally, so the sanitizer shipped the very
#: identity it existed to strip -- and every downstream copy inherited it.
#: `OPERATOR_IDENTIFIERS` (comma-separated) adds this operator's own strings at
#: build time; the generic credential shapes below always apply.
FORBIDDEN_CONTENT = tuple(
    [x.strip() for x in (os.environ.get("OPERATOR_IDENTIFIERS") or "").split(",")
     if x.strip()]
    + ["TOPSTEPX_API_KEY=", "TOPSTEPX_USERNAME=",
       "Bearer ", "eyJhbGciOi",            # JWT header
       "NT_DEMO_ACCOUNT"])

#: Operator-state values that may legitimately appear in a docstring as
#: engineering history, but must never appear as a live assertion.
OPERATOR_STATE_MARKERS = ("PROD-20260806", "PROD-20260807")


def denied(path: str, name: str) -> str | None:
    parts = path.replace("\\", "/").split("/")
    for part in parts[:-1]:
        if part in DENY_DIR_PARTS:
            return f"directory:{part}"
    if name in DENY_NAMES:
        return "denylisted name"
    for pattern in DENY_GLOBS:
        if fnmatch.fnmatch(name.lower(), pattern):
            return f"glob:{pattern}"
    return None


def doc_is_private(rel: str) -> bool:
    return any(marker in rel for marker in DENY_DOC_PATTERNS)


#: Operator identity tokens replaced UNIFORMLY across the exported tree.
#:
#: The NinjaTrader account number is hardcoded as a defense-in-depth allowlist
#: in `account_safety.py`. Deleting that module would remove a safety control;
#: shipping it as-is would hand over an account identifier AND leave the new
#: operator an allowlist naming somebody else's account. Substituting the token
#: everywhere -- source, tests and docs alike -- keeps the control intact and
#: self-consistent while naming nobody: the receiving operator must put her own
#: account in before the lane will address anything.
#: Same law: the map is seeded from the environment so no operator's identity is
#: hardcoded here. Format: "find=>replace,find=>replace".
REDACTIONS = dict(
    [("NT_DEMO_ACCOUNT", "NT_DEMO_ACCOUNT_PLACEHOLDER")]
    + [tuple(part.split("=>", 1)) for part in
       (os.environ.get("OPERATOR_REDACTIONS") or "").split(",")
       if "=>" in part])

REDACTABLE_SUFFIXES = (".py", ".md", ".txt", ".json", ".jsonl", ".html",
                       ".yml", ".yaml", ".ini", ".cfg", ".template", ".cs")


def redact_tree(root: str) -> list:
    """Substitute operator identity tokens in place. Returns an audit list."""
    audit = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in DENY_DIR_PARTS]
        for name in filenames:
            if not name.lower().endswith(REDACTABLE_SUFFIXES):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            try:
                text = open(full, encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                continue
            hits = {t: text.count(t) for t in REDACTIONS if t in text}
            if not hits:
                continue
            for token, replacement in REDACTIONS.items():
                text = text.replace(token, replacement)
            open(full, "w", encoding="utf-8").write(text)
            # Naming the tokens here would put them straight back into the
            # distribution inside the report that certifies their removal.
            audit.append({"path": rel,
                          "tokens_redacted": len(hits),
                          "total": sum(hits.values())})
    return audit


def sha256(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def build(source: str, out: str) -> dict:
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out)

    copied, excluded = [], []

    def take(src_path: str, rel: str):
        dst = os.path.join(out, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src_path, dst)
        copied.append(rel)

    for top in ALLOW_DIRS:
        root_dir = os.path.join(source, top)
        if not os.path.isdir(root_dir):
            continue
        for dirpath, dirnames, filenames in os.walk(root_dir):
            dirnames[:] = [d for d in dirnames if d not in DENY_DIR_PARTS]
            for name in sorted(filenames):
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, source).replace(os.sep, "/")
                reason = denied(rel, name)
                if reason:
                    excluded.append((rel, reason))
                    continue
                if top == "docs" and doc_is_private(rel):
                    excluded.append((rel, "operator-private session document"))
                    continue
                take(full, rel)

    for name in ALLOW_FILES:
        full = os.path.join(source, name)
        if os.path.isfile(full) and not denied(name, name):
            take(full, name)

    return {"copied": copied, "excluded": excluded}


def purge_runtime_dirt(root: str) -> list:
    """Remove anything a test run left behind inside the staging tree.

    Running the fresh-operator suite in the staging directory writes `data/`
    artifacts, and a distribution that ships `data/` would both carry runtime
    dirt and flip the operator-state guard so the receiving operator's suite
    silently expects evidence she does not have.
    """
    removed = []
    for name in ("data", "logs", ".pytest_cache", "__pycache__", "build",
                 ".coverage", "htmlcov"):
        victim = os.path.join(root, name)
        if os.path.isdir(victim):
            shutil.rmtree(victim)
            removed.append(name + "/")
        elif os.path.isfile(victim):
            os.remove(victim)
            removed.append(name)
    for dirpath, dirnames, _ in os.walk(root):
        for d in list(dirnames):
            if d in ("__pycache__", ".pytest_cache"):
                shutil.rmtree(os.path.join(dirpath, d), ignore_errors=True)
                dirnames.remove(d)
                removed.append(f"{os.path.relpath(os.path.join(dirpath, d), root)}")
    return removed


def scan_secrets(root: str) -> list:
    """Fail closed. Reports the FINDING, never the value."""
    findings = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in DENY_DIR_PARTS]
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            # This builder names every forbidden token as a literal in order to
            # hunt for them; scanning it finds only its own vocabulary.
            if rel == "tools/build_reference_distribution.py":
                continue
            try:
                text = open(full, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue

            # A blank `KEY=` in a template is the POINT of a template. Only a
            # populated one is a secret.
            for var in ("TOPSTEPX_API_KEY", "TOPSTEPX_USERNAME",
                        "TOPSTEPX_ACCOUNT_ID", "OPENAI_API_KEY", "NT_ACCOUNT"):
                # Horizontal whitespace only. A bare `\s*` eats the newline and
                # matches the NEXT line's first character, which makes every
                # blank template field look populated.
                if re.search(rf"^{var}[ \t]*=[ \t]*\S", text, re.M):
                    findings.append((rel, f"{var} carries a value"))

            # `Bearer` in header-construction code is not a credential; a
            # Bearer followed by a real-looking token is.
            if re.search(r"Bearer\s+[A-Za-z0-9_\-\.]{20,}", text):
                findings.append((rel, "Bearer followed by a token-shaped value"))

            # Synthetic JWTs in fixtures decode to {"alg":..}/{"sub":"1"};
            # anything with a long payload segment is not synthetic.
            for match in re.finditer(r"eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]{40,}",
                                     text):
                findings.append((rel, "JWT with a substantial payload"))

            for token in REDACTIONS:
                if token in text:
                    findings.append((rel, "operator identity token survived redaction"))

            if re.search(r"(?i)(api_key|apikey|secret|password)\s*[=:]\s*"
                         r"['\"][A-Za-z0-9_\-]{24,}['\"]", text):
                findings.append((rel, "key-shaped literal assignment"))
    return findings


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    result = build(args.source, args.out)
    redactions = redact_tree(args.out)
    purged = purge_runtime_dirt(args.out)
    findings = scan_secrets(args.out)

    total = 0
    for dirpath, _, filenames in os.walk(args.out):
        for name in filenames:
            total += os.path.getsize(os.path.join(dirpath, name))

    print("=" * 80)
    print("  SANITIZED REFERENCE DISTRIBUTION")
    print("=" * 80)
    print(f"  source        : {args.source}")
    print(f"  staging       : {args.out}")
    print(f"  files copied  : {len(result['copied'])}")
    print(f"  bytes         : {total}")
    print(f"  excluded      : {len(result['excluded'])}")
    by_reason: dict = {}
    for _, reason in result["excluded"]:
        by_reason[reason] = by_reason.get(reason, 0) + 1
    for reason, count in sorted(by_reason.items(), key=lambda kv: -kv[1])[:10]:
        print(f"      {count:>4}  {reason}")
    print(f"  .git present  : {os.path.exists(os.path.join(args.out, '.git'))}")
    print(f"  .env present  : {os.path.exists(os.path.join(args.out, '.env'))}")
    print(f"  data/ present : {os.path.exists(os.path.join(args.out, 'data'))}")
    redacted_files = len(redactions)
    redacted_total = sum(r["total"] for r in redactions)
    print(f"  redacted      : {redacted_total} token(s) across {redacted_files} file(s)")
    print(f"  purged        : {len(purged)} runtime artifact(s)")
    print(f"  SECRET SCAN   : {len(findings)} finding(s)")
    for rel, why in findings[:10]:
        print(f"      {rel}: {why}")
    report_path = os.path.join(os.path.dirname(args.out.rstrip("/\\")),
                               "_reference_build_report.json")
    json.dump({"copied": result["copied"],
               "redactions": redactions,
               "excluded": [{"path": p, "reason": r}
                            for p, r in result["excluded"]],
               "secret_findings": [{"path": p, "reason": r}
                                   for p, r in findings],
               "built_at": _dt.datetime.now(_dt.timezone.utc).isoformat()},
              open(report_path, "w", encoding="utf-8"), indent=1)
    print(f"  build report  : {report_path}  (OUTSIDE the distribution)")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
