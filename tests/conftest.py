"""Shared fixtures for self-healing tests."""

import sys
from pathlib import Path

# Ensure the skill root is on the path so imports work
SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))
sys.path.insert(0, str(SKILL_DIR / "scripts"))
