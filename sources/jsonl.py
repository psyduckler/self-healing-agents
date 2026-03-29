"""Backward compatibility shim — imports from src/self_healing/sources/jsonl.py"""
import sys
from pathlib import Path
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
from self_healing.sources.jsonl import JSONLSource
