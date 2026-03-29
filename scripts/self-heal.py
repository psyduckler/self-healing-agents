#!/usr/bin/env python3
"""
self-heal.py — Thin wrapper for backward compatibility.

Usage:
  python3 self-heal.py <command> [args]

Prefer: self-heal <command> [args]
"""

import sys
from pathlib import Path

# Add src/ to path so the package is importable without install
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from self_healing.healer import main

if __name__ == "__main__":
    main()
