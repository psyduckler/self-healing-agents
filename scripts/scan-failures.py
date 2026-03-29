#!/usr/bin/env python3
"""
scan-failures.py — Scan OpenClaw cron jobs and recent sub-agents for failures.
Outputs a JSON array of detected failures for the self-healing workflow.

Usage:
  python3 scan-failures.py [--hours N] [--json]

Options:
  --hours N   Look back N hours (default: 6)
  --json      Output raw JSON (default: human-readable summary)
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

def get_cron_failures():
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
            # Find status column — it's after the time-ago columns
            status = None
            for i, p in enumerate(parts):
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


def get_subagent_failures(hours=6):
    """Check recent sub-agent runs for failures."""
    failures = []
    runs_path = Path.home() / ".openclaw" / "subagents" / "runs.json"
    if not runs_path.exists():
        return failures

    try:
        data = json.loads(runs_path.read_text())
        cutoff = time.time() - (hours * 3600)

        raw_runs = data if isinstance(data, list) else data.get("runs", data)
        # runs can be a dict keyed by runId or a list
        if isinstance(raw_runs, dict):
            runs = list(raw_runs.values())
        else:
            runs = raw_runs
        for run in runs:
            if not isinstance(run, dict):
                continue
            # Check if recent
            ts = run.get("startedAt", run.get("createdAt", 0))
            if isinstance(ts, str):
                try:
                    ts_val = float(ts)
                    # Milliseconds if > 1e12
                    ts = ts_val / 1000 if ts_val > 1e12 else ts_val
                except ValueError:
                    try:
                        ts = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                    except:
                        continue
            elif isinstance(ts, (int, float)):
                ts = ts / 1000 if ts > 1e12 else ts
            if ts < cutoff:
                continue

            # Status may be a string or nested in outcome dict
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


def get_deploy_failures(hours=6):
    """Check for recent deploy/git push failures in common log locations."""
    failures = []
    log_paths = [
        Path("/tmp/compare-batch.log"),
        Path("/tmp/fulfillment.log"),
    ]
    cutoff_time = time.time() - (hours * 3600)

    for log_path in log_paths:
        if not log_path.exists():
            continue
        if log_path.stat().st_mtime < cutoff_time:
            continue
        try:
            content = log_path.read_text()
            # Look for common failure indicators
            for line in content.split("\n"):
                line_lower = line.lower()
                if any(kw in line_lower for kw in ["error", "failed", "fatal", "traceback", "exception"]):
                    failures.append({
                        "source": "deploy",
                        "id": str(log_path),
                        "name": log_path.name,
                        "error": line.strip()[:300],
                        "timestamp": datetime.fromtimestamp(
                            log_path.stat().st_mtime, tz=timezone.utc
                        ).isoformat(),
                        "severity": "warning"
                    })
                    break  # One failure per log file
        except Exception:
            pass
    return failures


def main():
    hours = 6
    output_json = False

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--hours" and i + 1 < len(args):
            hours = int(args[i + 1])
            i += 2
        elif args[i] == "--json":
            output_json = True
            i += 1
        else:
            i += 1

    all_failures = []
    all_failures.extend(get_cron_failures())
    all_failures.extend(get_subagent_failures(hours))
    all_failures.extend(get_deploy_failures(hours))

    # Sort by severity (critical first)
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    all_failures.sort(key=lambda f: severity_order.get(f.get("severity", "info"), 3))

    if output_json:
        print(json.dumps(all_failures, indent=2))
    else:
        if not all_failures:
            print("✅ No failures detected in the last {} hours.".format(hours))
        else:
            print(f"🔍 Found {len(all_failures)} failure(s) in the last {hours} hours:\n")
            for f in all_failures:
                icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(f["severity"], "⚪")
                print(f"  {icon} [{f['source']}] {f['name']}")
                print(f"     Error: {f['error'][:200]}")
                print(f"     Time: {f['timestamp']}")
                print()


if __name__ == "__main__":
    main()
