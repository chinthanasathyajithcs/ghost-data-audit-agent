"""Build code.zip (README.md + code/) for submission, using only the standard library.

    python3 code/package.py          # writes ./code.zip at the repository root

Same rules as the README's zip command: no dataset, virtual environments, caches of Python or pytest,
run outputs, usage logs or nested archives. The shipped LLM answer caches (code/deletion_audit/cache/)
are included so the agent reruns offline.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = REPO_ROOT / "code.zip"
EXCLUDED_DIRS = {"__pycache__", ".venv", "venv", "node_modules", ".git", ".pytest_cache"}
EXCLUDED_PATHS = ("code/usage/", "code/evaluation/runs/")
EXCLUDED_SUFFIXES = (".zip", ".tar", ".gz", ".tgz", ".7z", ".rar", ".pyc")


def included(path: Path) -> bool:
    relative = path.relative_to(REPO_ROOT).as_posix()
    return (path.is_file()
            and not EXCLUDED_DIRS & set(path.relative_to(REPO_ROOT).parts)
            and not relative.startswith(EXCLUDED_PATHS)
            and not relative.endswith(EXCLUDED_SUFFIXES)
            and path.name != ".DS_Store")


def main() -> int:
    files = [REPO_ROOT / "README.md"] + sorted(p for p in (REPO_ROOT / "code").rglob("*") if included(p))
    with zipfile.ZipFile(ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(REPO_ROOT).as_posix())
    print(f"wrote {ARCHIVE} with {len(files)} files ({ARCHIVE.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
