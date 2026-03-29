"""
Source plugin registry — backward compatibility shim.

Imports from the canonical location: src/self_healing/sources/
"""

import sys
from pathlib import Path

# Ensure src/ is on the path for non-installed usage
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from self_healing.sources import (
    get_source,
    get_all_sources,
    list_sources,
    register_source,
)
from self_healing.sources.base import FailureSource
