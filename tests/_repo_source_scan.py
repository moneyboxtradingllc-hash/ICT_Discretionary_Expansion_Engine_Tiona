"""Python-native source guards, matching grep -rn --include=*.py.

Callers search literal identifiers, not regular expressions. Preserve their
src/tools scope and whole-line filters, with deterministic UTF-8 decoding and
ordering. Unreadable sources fail the guard rather than silently passing it.
"""
from pathlib import Path
import os


def matching_python_lines(pattern: str, *, root: Path | None = None) -> list[str]:
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    matches = []

    def refuse_unreadable(error):
        raise error

    for directory in ("src", "tools"):
        for current, directories, files in os.walk(
                root / directory, followlinks=False, onerror=refuse_unreadable):
            directories.sort()
            for name in sorted(files):
                path = Path(current) / name
                # Case-sensitive on every platform; grep -r skips nested links.
                if not name.endswith(".py") or path.is_symlink():
                    continue
                relative = path.relative_to(root).as_posix()
                for number, line in enumerate(
                        path.read_text(encoding="utf-8").splitlines(), start=1):
                    if pattern in line:
                        matches.append(f"{relative}:{number}:{line}")
    return matches
