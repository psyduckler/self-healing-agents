"""
Log file source plugin — scans structured log files for errors.

Config:
    paths: list of glob patterns (e.g., ["/tmp/*.log", "/var/log/myapp/*.log"])
    error_patterns: list of regex patterns to match error lines
    severity_map: dict mapping matched keywords to severity levels
"""

import re
import time
from datetime import datetime, timezone
from pathlib import Path

from .base import FailureSource

# Default patterns if none configured
DEFAULT_ERROR_PATTERNS = [
    r"ERROR|FATAL|CRITICAL",
    r"Traceback",
    r"Exception",
]

DEFAULT_PATHS = [
    "/tmp/*.log",
]

DEFAULT_SEVERITY_MAP = {
    "FATAL": "critical",
    "CRITICAL": "critical",
    "ERROR": "warning",
    "WARNING": "info",
}


class LogFileSource(FailureSource):
    """Scans log files matching glob patterns for error lines."""

    name = "logfile"

    def __init__(self, paths: list[str] = None, error_patterns: list[str] = None,
                 severity_map: dict[str, str] = None):
        self.paths = paths or list(DEFAULT_PATHS)
        self.error_patterns = [re.compile(p, re.IGNORECASE) for p in (error_patterns or DEFAULT_ERROR_PATTERNS)]
        self.severity_map = severity_map or dict(DEFAULT_SEVERITY_MAP)

    @classmethod
    def from_config(cls, config: dict) -> "LogFileSource":
        return cls(
            paths=config.get("paths", DEFAULT_PATHS),
            error_patterns=config.get("error_patterns"),
            severity_map=config.get("severity_map"),
        )

    def scan(self, hours: int = 6) -> list[dict]:
        failures = []
        cutoff_time = time.time() - (hours * 3600)

        for pattern in self.paths:
            # Handle glob patterns
            if "*" in pattern or "?" in pattern:
                # Split into directory and glob
                p = Path(pattern)
                parent = p.parent
                glob_pattern = p.name
                if parent.exists():
                    log_files = list(parent.glob(glob_pattern))
                else:
                    log_files = []
            else:
                log_path = Path(pattern)
                log_files = [log_path] if log_path.exists() else []

            for log_path in log_files:
                if not log_path.is_file():
                    continue
                try:
                    if log_path.stat().st_mtime < cutoff_time:
                        continue
                except OSError:
                    continue

                try:
                    content = log_path.read_text(errors="replace")
                    for line in content.split("\n"):
                        if not line.strip():
                            continue
                        for regex in self.error_patterns:
                            if regex.search(line):
                                severity = self._classify_severity(line)
                                failures.append({
                                    "source": "logfile",
                                    "id": str(log_path),
                                    "name": log_path.name,
                                    "error": line.strip()[:300],
                                    "timestamp": datetime.fromtimestamp(
                                        log_path.stat().st_mtime, tz=timezone.utc
                                    ).isoformat(),
                                    "severity": severity,
                                })
                                break  # One match per line is enough
                except Exception:
                    pass

        return failures

    def _classify_severity(self, line: str) -> str:
        """Classify severity based on the severity_map."""
        line_upper = line.upper()
        for keyword, severity in self.severity_map.items():
            if keyword.upper() in line_upper:
                return severity
        return "warning"
