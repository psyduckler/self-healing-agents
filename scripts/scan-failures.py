#!/usr/bin/env python3
"""
scan-failures.py — Thin wrapper for backward compatibility.

Usage:
  python3 scan-failures.py [--hours N] [--json] [--source NAME] [--config PATH]

Prefer: self-heal scan [--hours N] [--json] [--source NAME] [--config PATH]
"""

import sys
from pathlib import Path

# Add src/ to path so the package is importable without install
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from self_healing.scanner import main

if __name__ == "__main__":
    main()
