"""Shared fixtures for self-healing tests."""

import sys
from pathlib import Path

# Ensure src/ is on the path so the package is importable without install
REPO_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_DIR / "src"
sys.path.insert(0, str(SRC_DIR))
# Also keep backward compat paths
sys.path.insert(0, str(REPO_DIR))
sys.path.insert(0, str(REPO_DIR / "scripts"))
