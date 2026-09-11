"""Certification is independent of checkout line endings, not source content."""
import builtins
from io import BytesIO
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ai_brain import production_model as PM


@pytest.fixture
def source_bytes(monkeypatch):
    """Exercise the actual 30-file hash without rewriting production files."""
    sources = {}
    for label, relative in PM._CONTRACT_SOURCES + PM._CONTRACT_SOURCES_REPO:
        base = ROOT if (label, relative) in PM._CONTRACT_SOURCES_REPO else ROOT / "src"
        path = base / relative
        sources[os.path.normcase(str(path))] = path.read_bytes().replace(b"\r\n", b"\n")
    original_open = builtins.open

    def read_source(path, mode="r", *args, **kwargs):
        key = os.path.normcase(os.path.abspath(path))
        if mode == "rb" and key in sources:
            return BytesIO(sources[key])
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(PM, "open", read_source, raising=False)
    return sources


@pytest.mark.parametrize("style", ["lf", "crlf", "mixed_files", "mixed_lines"])
def test_all_closure_sources_have_one_canonical_identity(source_bytes, style):
    assert len(source_bytes) == 30
    for index, (path, data) in enumerate(source_bytes.items()):
        if style == "crlf" or (style == "mixed_files" and index % 2):
            source_bytes[path] = data.replace(b"\n", b"\r\n")
        elif style == "mixed_lines":
            # Include a mixed-EOL single file, not only different file styles.
            source_bytes[path] = data.replace(b"\n", b"\r\n", 1)
    # Feature-branch source includes the deterministic Brain wake boundary.
    # This is a new contract fingerprint, not a historical authorization
    # migration.
    assert PM.brain_contract_fingerprint() == "brain:5db77eab2b66b53e"


@pytest.mark.parametrize("addition", [
    b"\nCERTIFICATION_PROBE = 1\n",  # semantic source content
    b"\n# certification probe\n",   # comments remain bound
    b" ",                          # arbitrary whitespace remains bound
    b"\n",                         # trailing blank lines remain bound
    b"\nprobe = '\\r\\n'\n",       # escaped literal bytes are not line endings
    b"\r",                         # lone CR is not silently canonicalized
])
@pytest.mark.parametrize("relative", [
    "src/ai_brain/brain_prompt.py", "tools/topstepx_production_session.py",
])
def test_other_content_changes_remain_bound_in_both_anchors(source_bytes, relative, addition):
    before = PM.brain_contract_fingerprint()
    key = os.path.normcase(str(ROOT / relative))
    source_bytes[key] += addition
    assert PM.brain_contract_fingerprint() != before
