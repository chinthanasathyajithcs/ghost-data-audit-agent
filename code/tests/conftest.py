"""Make the agent package and the evaluation modules importable from tests."""

import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = CODE_DIR.parent

for path in (CODE_DIR, CODE_DIR / "evaluation"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
