"""
OpenClaw source plugin — scans cron jobs and sub-agent runs for failures.
"""

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from .base import FailureSource


class OpenClawSource(FailureSource):
    """Scans OpenClaw cron jobs and recent sub-agent runs for failures."""

    name = "openclaw"

    def scan(self, hours: int = 6) -> list[dict]:
        failures = []
        failures.extend(self._get_cron_failures())
        failures.extend(self._get_subagent_failures(hours))
        return failures

    @classmethod
    def from_config(cls, config: dict) -> "OpenClawSource":
        return cls()

    def _get_cron_failures(self) -> list[dict]:
        """Check cron jobs for error status."""
        failures = []
        try:
            result = subprocess.run(
                ["openclaw", "cron", "list"],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode != 0:
                return failures

            for line in result.stdout.strip().split("\n")[1:]:  # Skip header
                parts = line.split()
                if len(parts) < 8:
                    continue
                job_id = parts[0]
                name = parts[1]
                status = None
                for p in parts:
                    if p in ("ok", "error", "running", "idle", "timeout"):
                        status = p
                        break
                if status == "error":
                    failures.append({
                        "source": "cron",
                        "id": job_id,
                        "name": name,
                        "error": f"Cron job '{name}' in error state",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "severity": "warning",
                        "raw_line": line.strip()
                    })
        except Exception as e:
            failures.append({
                "source": "system",
                "id": "cron-scan",
                "name": "Cron scanner",
                "error": f"Failed to scan crons: {e}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "severity": "info"
            })
        return failures

    def _get_subagent_failures(self, hours: int = 6) -> list[dict]:
        """Check recent sub-agent runs for failures."""
        failures = []
        runs_path = Path.home() / ".openclaw" / "subagents" / "runs.json"
        if not runs_path.exists():
            return failures

        try:
            data = json.loads(runs_path.read_text())
            cutoff = time.time() - (hours * 3600)

            raw_runs = data if isinstance(data, list) else data.get("runs", data)
            if isinstance(raw_runs, dict):
                runs = list(raw_runs.values())
            else:
                runs = raw_runs

            for run in runs:
                if not isinstance(run, dict):
                    continue
                ts = run.get("startedAt", run.get("createdAt", 0))
                if isinstance(ts, str):
                    try:
                        ts_val = float(ts)
                        ts = ts_val / 1000 if ts_val > 1e12 else ts_val
                    except ValueError:
                        try:
                            ts = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                        except Exception:
                            continue
                elif isinstance(ts, (int, float)):
                    ts = ts / 1000 if ts > 1e12 else ts
                if ts < cutoff:
                    continue

                status = run.get("status", "")
                outcome = run.get("outcome", "")
                if isinstance(outcome, str) and "error" in outcome:
                    status = "error"
                elif isinstance(outcome, dict):
                    status = outcome.get("status", status)
                ended_reason = run.get("endedReason", "")
                if ended_reason in ("timeout", "error"):
                    status = ended_reason
                if status in ("error", "failed", "timeout"):
                    failures.append({
                        "source": "subagent",
                        "id": run.get("sessionKey", run.get("id", "unknown")),
                        "name": run.get("label", run.get("task", "unknown")[:80]),
                        "error": run.get("error", run.get("frozenResultText", f"Sub-agent {status}"))[:500],
                        "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts > 0 else "unknown",
                        "severity": "warning" if status == "timeout" else "critical"
                    })
        except Exception as e:
            failures.append({
                "source": "system",
                "id": "subagent-scan",
                "name": "Sub-agent scanner",
                "error": f"Failed to scan sub-agents: {e}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "severity": "info"
            })
        return failures
