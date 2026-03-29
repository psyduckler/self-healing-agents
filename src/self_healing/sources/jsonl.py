"""
JSONL source plugin — scans JSONL files where each line is a JSON error record.

Config:
    path: path to the JSONL file
    error_field: field name containing the error message (default: "message")
    timestamp_field: field name containing the timestamp (default: "timestamp")
    severity_field: field name containing the severity (default: "level")
    id_field: field name containing a unique id (default: "id")
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .base import FailureSource


class JSONLSource(FailureSource):
    """Scans JSONL files for error records within a time window."""

    name = "jsonl"

    def __init__(self, path: str = "/tmp/agent-errors.jsonl",
                 error_field: str = "message",
                 timestamp_field: str = "timestamp",
                 severity_field: str = "level",
                 id_field: str = "id"):
        self.path = Path(path)
        self.error_field = error_field
        self.timestamp_field = timestamp_field
        self.severity_field = severity_field
        self.id_field = id_field

    @classmethod
    def from_config(cls, config: dict) -> "JSONLSource":
        return cls(
            path=config.get("path", "/tmp/agent-errors.jsonl"),
            error_field=config.get("error_field", "message"),
            timestamp_field=config.get("timestamp_field", "timestamp"),
            severity_field=config.get("severity_field", "level"),
            id_field=config.get("id_field", "id"),
        )

    def scan(self, hours: int = 6) -> list[dict]:
        failures = []

        if not self.path.exists():
            return failures

        cutoff = time.time() - (hours * 3600)

        try:
            with open(self.path, "r") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if not isinstance(record, dict):
                        continue

                    # Parse timestamp
                    ts_raw = record.get(self.timestamp_field)
                    ts = self._parse_timestamp(ts_raw)
                    if ts is not None and ts < cutoff:
                        continue

                    # Get error message
                    error_msg = record.get(self.error_field, "")
                    if not error_msg:
                        continue

                    # Get severity
                    severity = self._normalize_severity(
                        record.get(self.severity_field, "warning")
                    )

                    # Get id
                    record_id = record.get(self.id_field, f"jsonl-{line_num}")

                    failures.append({
                        "source": "jsonl",
                        "id": str(record_id),
                        "name": self.path.name,
                        "error": str(error_msg)[:500],
                        "timestamp": datetime.fromtimestamp(
                            ts, tz=timezone.utc
                        ).isoformat() if ts else datetime.now(timezone.utc).isoformat(),
                        "severity": severity,
                    })
        except Exception:
            pass

        return failures

    def _parse_timestamp(self, ts_raw) -> Optional[float]:
        """Parse various timestamp formats into epoch float."""
        if ts_raw is None:
            return None

        if isinstance(ts_raw, (int, float)):
            # Epoch seconds or milliseconds
            return ts_raw / 1000 if ts_raw > 1e12 else ts_raw

        if isinstance(ts_raw, str):
            # Try ISO format
            try:
                return datetime.fromisoformat(
                    ts_raw.replace("Z", "+00:00")
                ).timestamp()
            except ValueError:
                pass
            # Try epoch string
            try:
                val = float(ts_raw)
                return val / 1000 if val > 1e12 else val
            except ValueError:
                pass

        return None

    def _normalize_severity(self, raw: str) -> str:
        """Normalize severity strings to critical/warning/info."""
        raw_lower = str(raw).lower()
        if raw_lower in ("critical", "fatal", "emergency", "alert"):
            return "critical"
        if raw_lower in ("error", "err", "warning", "warn"):
            return "warning"
        return "info"
