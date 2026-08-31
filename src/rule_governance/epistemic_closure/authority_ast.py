"""EPISTEMIC-CLOSURE-CERTIFICATION-1 — authority claims, read STRUCTURALLY.

WHY THIS EXISTS. The first version of the v2-inertness check searched source
text for `causal_identity_version=2`. It immediately reported the governance
package itself as an offender, because that package DESCRIBES v2 in order to
record that production does not use it. The repair at the time was to exclude a
directory -- a lexical patch on a lexical defect, and the exact brittleness this
framework was created to stop tolerating.

A comment is not a call. A docstring is not a call. A test fixture is not a
call. A governance contract naming a keyword is emphatically not a call. Only a
CALL is a call, and Python can tell us which is which.

    LEXICAL   "does this string appear in src/?"
    STRUCTURAL "does production actually pass this argument at a call site?"

The second question is the one the release gate means to ask.

WHERE LEXICAL IS STILL HONEST. Structural inspection answers questions about
CALLS and IMPORTS. It cannot answer "does this prose still mean what it meant",
and it is not used to pretend otherwise -- see `prompt_anchor` for the digest
mechanism and the explicit statement of what it does and does not prove.
"""
from __future__ import annotations

import ast
import hashlib
import os

#: Namespaces that are PRODUCTION. Governance describes production; it is not
#: production, and neither are tests or tools. This is a structural fact about
#: the package layout rather than a filename blocklist.
_NON_PRODUCTION_PARTS = ("rule_governance", "__pycache__")


def production_files(src_root) -> list:
    """Every production source file, by package location rather than by name."""
    out = []
    for root, _dirs, files in os.walk(src_root):
        parts = root.replace("\\", "/").split("/")
        if any(p in parts for p in _NON_PRODUCTION_PARTS):
            continue
        for name in files:
            if name.endswith(".py"):
                out.append(os.path.join(root, name))
    return out


def _parse(path):
    """Parse a module, or None when it genuinely cannot be read.

    `utf-8-sig` rather than `utf-8`: `src/main.py` carries a byte-order mark,
    and `ast.parse` rejects U+FEFF as a non-printable character. Read as plain
    utf-8 that file degraded every answer about it to UNKNOWN -- an honest
    degradation, but an avoidable one, and it was the tri-state reporting the
    reason that made the cause visible at all.
    """
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return ast.parse(fh.read(), filename=path)
    except (OSError, SyntaxError, ValueError):
        return None


def _literal(node):
    """The literal a node denotes, or a sentinel when it is not a literal."""
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return _NOT_LITERAL


_NOT_LITERAL = object()


def keyword_call_sites(src_root, keyword, *, exclude_files=()) -> list:
    """Every real CALL in production that passes `keyword=<something>`.

    Returns one row per call site: file, line, the callee as written, and the
    literal value when the argument is a literal. A non-literal (a variable, a
    lookup) is reported with `value=None` and `literal=False` -- it cannot be
    proven inert, so it is surfaced rather than assumed harmless.
    """
    skip = {os.path.abspath(p) for p in exclude_files}
    found = []
    for path in production_files(src_root):
        if os.path.abspath(path) in skip:
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg != keyword:
                    continue
                value = _literal(kw.value)
                found.append({
                    "file": os.path.relpath(path, src_root).replace("\\", "/"),
                    "line": node.lineno,
                    "callee": _callee_name(node.func),
                    "literal": value is not _NOT_LITERAL,
                    "value": None if value is _NOT_LITERAL else value,
                })
    return found


def _callee_name(func) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return f"{_callee_name(func.value)}.{func.attr}"
    return type(func).__name__


def imports_module(src_root, module_name, *, exclude_files=()) -> list:
    """Every production file that structurally IMPORTS `module_name`.

    `import a.b.c`, `from a.b import c` and `from a.b.c import d` all count. A
    string mentioning the name in a comment, a docstring or a governance
    contract does not -- which is precisely the distinction the two contaminated
    suite failures showed we were missing.
    """
    skip = {os.path.abspath(p) for p in exclude_files}
    hits = []
    for path in production_files(src_root):
        if os.path.abspath(path) in skip:
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                names = [base] + [f"{base}.{a.name}" if base else a.name
                                  for a in node.names]
            for name in names:
                if name == module_name or name.endswith(f".{module_name}") \
                        or name.startswith(f"{module_name}."):
                    hits.append({
                        "file": os.path.relpath(path, src_root).replace("\\", "/"),
                        "line": node.lineno, "imports": name})
                    break
    return hits


def attribute_reads(src_root, attribute, *, exclude_files=()) -> list:
    """Production sites that structurally READ `x.attribute` or `["attribute"]`.

    Used to anchor a consumer to the exact field it consumes, so a consumer that
    silently stops reading a fact -- or starts -- is visible.
    """
    skip = {os.path.abspath(p) for p in exclude_files}
    hits = []
    for path in production_files(src_root):
        if os.path.abspath(path) in skip:
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            hit = False
            if isinstance(node, ast.Attribute) and node.attr == attribute:
                hit = True
            elif isinstance(node, ast.Subscript):
                value = _literal(node.slice)
                hit = value == attribute
            elif isinstance(node, ast.Call) and _callee_name(node.func).endswith(".get"):
                if node.args and _literal(node.args[0]) == attribute:
                    hit = True
            elif isinstance(node, ast.Constant) and node.value == attribute:
                # A bare string constant IS how a dict key is named in most of
                # this repository, so it counts -- but only as a CONSTANT in
                # code, never as text inside a comment or docstring, which the
                # parser has already discarded by this point.
                hit = True
            if hit:
                hits.append({
                    "file": os.path.relpath(path, src_root).replace("\\", "/"),
                    "line": getattr(node, "lineno", 0)})
    return hits


def prompt_anchor(path, marker, *, span=40) -> "str | None":
    """A digest of the prompt fragment that defines a fact's meaning.

    WHAT THIS PROVES, EXACTLY: that the passage did not change. Nothing more.

    WHAT IT CANNOT PROVE: that the passage still MEANS what the contract says.
    No mechanism here parses English. If someone rewrites the `registered_at`
    passage to describe a latest-confirmation timestamp, this digest moves, the
    gate fails, and a HUMAN decides whether the new language preserves the
    semantic. That is the correct division of labour, and overstating it would
    be the same overclaiming the framework exists to prevent.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return None
    for index, line in enumerate(lines):
        if marker in line:
            fragment = "\n".join(lines[index:index + span])
            normalised = " ".join(fragment.split())
            return hashlib.sha256(normalised.encode()).hexdigest()[:16]
    return None


# ── TRI-STATE RESOLUTION ────────────────────────────────────────────────────
#: The analysis proved the relationship exists.
PRESENT = "PRESENT"
#: The analysis proved it does NOT exist -- and could have seen it if it did.
ABSENT = "ABSENT"
#: The analysis could not decide. NOT the same as ABSENT, and the distinction is
#: the whole point: failure to prove presence is not proof of absence.
UNKNOWN = "UNKNOWN"


def _dynamic_constructs(tree) -> list:
    """Constructions that can author or read a key the inspector cannot name.

    Each of these can put a field into a payload, or take one out, without the
    field's name ever appearing as a literal anywhere the parser can see:

        {**a, **b}              a merge whose keys come from elsewhere
        d[k]                    a subscript whose slice is not a literal
        d.get(k)                the same, via get
        getattr(o, name)        attribute access by computed name
        {k: v for ...}          a comprehension that manufactures keys
        d.update(...)           bulk insertion

    Their presence does not prove the fact IS produced or consumed. It proves
    this inspector cannot honestly say it is not.
    """
    reasons = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict) and any(k is None for k in node.keys):
            reasons.append(f"dict merge (**) at line {node.lineno}")
        elif isinstance(node, ast.DictComp):
            reasons.append(f"dict comprehension at line {node.lineno}")
        elif isinstance(node, ast.Subscript):
            if _literal(node.slice) is _NOT_LITERAL:
                reasons.append(f"non-literal subscript at line {node.lineno}")
        elif isinstance(node, ast.Call):
            name = _callee_name(node.func)
            if name == "getattr" and len(node.args) >= 2 \
                    and _literal(node.args[1]) is _NOT_LITERAL:
                reasons.append(f"getattr with computed name at line {node.lineno}")
            elif name.endswith(".update"):
                reasons.append(f"dict.update at line {node.lineno}")
            elif name.endswith(".get") and node.args \
                    and _literal(node.args[0]) is _NOT_LITERAL:
                reasons.append(f"get with computed key at line {node.lineno}")
    return reasons


def field_authority(paths, field) -> dict:
    """Do these modules reference `field`? PRESENT / ABSENT / UNKNOWN.

    ABSENT is only returned when the inspector both found no reference AND
    found nothing that could hide one. Anything dynamic downgrades the answer to
    UNKNOWN with the reason attached, so a reader can see exactly why the
    analysis declined to conclude.
    """
    hits, unresolved, seen_any_file = [], [], False
    for path in paths:
        tree = _parse(path)
        if tree is None:
            unresolved.append({"file": os.path.basename(path),
                               "reason": "file could not be parsed"})
            continue
        seen_any_file = True
        for node in ast.walk(tree):
            named = (
                (isinstance(node, ast.Attribute) and node.attr == field)
                or (isinstance(node, ast.Constant) and node.value == field)
                or (isinstance(node, ast.Subscript)
                    and _literal(node.slice) == field))
            if named:
                hits.append({"file": os.path.basename(path),
                             "line": getattr(node, "lineno", 0)})
                break
        else:
            for reason in _dynamic_constructs(tree):
                unresolved.append({"file": os.path.basename(path),
                                   "reason": reason})
    if hits:
        return {"state": PRESENT, "sites": hits, "unresolved": unresolved}
    if not seen_any_file:
        return {"state": UNKNOWN, "sites": [],
                "unresolved": unresolved or [{"reason": "no module to inspect"}]}
    if unresolved:
        return {"state": UNKNOWN, "sites": [], "unresolved": unresolved}
    return {"state": ABSENT, "sites": [], "unresolved": []}
