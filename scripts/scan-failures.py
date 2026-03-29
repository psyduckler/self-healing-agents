#!/usr/bin/env python3
"""
scan-failures.py — Scan OpenClaw cron jobs and recent sub-agents for failures.
Includes cascading failure detection — groups related failures that likely share a root cause.

Usage:
  python3 scan-failures.py [--hours N] [--json]

Options:
  --hours N   Look back N hours (default: 6)
  --json      Output raw JSON (default: human-readable summary)
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path


# ─── Cascading Failure Detection ───────────────────────────────────────────────

# Common root causes that affect multiple systems simultaneously
CASCADE_SIGNATURES = {
    "gateway_down": {
        "patterns": [r"gateway", r"ECONNREFUSED.*3000", r"RPC.*fail", r"openclaw.*not running"],
        "description": "OpenClaw gateway is down — all crons and sub-agents affected",
        "severity": "critical"
    },
    "git_locked": {
        "patterns": [r"\.git/index\.lock", r"unable to create.*lock", r"Another git process"],
        "description": "Git lock file — concurrent git operations are failing",
        "severity": "warning"
    },
    "disk_full": {
        "patterns": [r"No space left", r"ENOSPC", r"disk full", r"Disk quota"],
        "description": "Disk full — all file writes failing",
        "severity": "critical"
    },
    "network_down": {
        "patterns": [r"ENETUNREACH", r"Network is unreachable", r"DNS.*fail", r"Could not resolve host"],
        "description": "Network unreachable — all external API calls failing",
        "severity": "critical"
    },
    "api_outage": {
        "patterns": [r"503 Service", r"502 Bad Gateway", r"500 Internal Server"],
        "description": "External API outage — multiple services returning errors",
        "severity": "warning"
    },
    "auth_expired": {
        "patterns": [r"401.*expired", r"token.*expired", r"Unauthorized", r"invalid.*token"],
        "description": "Authentication expired — multiple services failing on auth",
        "severity": "warning"
    },
    "tmp_cleanup": {
        "patterns": [r"FileNotFoundError.*\/tmp\/", r"No such file.*\/tmp\/", r"ENOENT.*\/tmp\/"],
        "description": "macOS /tmp cleanup — temp files were purged",
        "severity": "warning"
    }
}


def detect_cascades(failures):
    """
    Group failures that likely share a root cause.

    Strategy:
    1. Time proximity: failures within 5 minutes of each other
    2. Error similarity: same error class or matching cascade signatures
    3. Source correlation: multiple crons failing simultaneously → likely shared cause

    Returns list of cascade groups, each with a probable root cause.
    """
    if len(failures) < 2:
        return []

    cascades = []

    # Check for known cascade signatures across all failure errors
    all_errors = " ".join(f.get("error", "") for f in failures)
    for cascade_name, sig in CASCADE_SIGNATURES.items():
        matching_failures = []
        for f in failures:
            error = f.get("error", "")
            if any(re.search(p, error, re.IGNORECASE) for p in sig["patterns"]):
                matching_failures.append(f)

        if len(matching_failures) >= 2:
            cascades.append({
                "type": "signature",
                "name": cascade_name,
                "description": sig["description"],
                "severity": sig["severity"],
                "failures": [f.get("name", "unknown") for f in matching_failures],
                "count": len(matching_failures),
                "recommendation": f"Fix the root cause ({cascade_name}) — individual failures will resolve"
            })

    # Time-proximity grouping: multiple failures within 5 minutes
    timed_failures = []
    for f in failures:
        ts_str = f.get("timestamp", "")
        try:
            if ts_str and ts_str != "unknown":
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                timed_failures.append((ts, f))
        except (ValueError, TypeError):
            pass

    if len(timed_failures) >= 2:
        timed_failures.sort(key=lambda x: x[0])
        # Sliding window: group failures within 5 minutes
        groups = []
        current_group = [timed_failures[0]]
        for i in range(1, len(timed_failures)):
            if (timed_failures[i][0] - current_group[-1][0]).total_seconds() <= 300:
                current_group.append(timed_failures[i])
            else:
                if len(current_group) >= 2:
                    groups.append(current_group)
                current_group = [timed_failures[i]]
        if len(current_group) >= 2:
            groups.append(current_group)

        for group in groups:
            names = [f[1].get("name", "unknown") for f in group]
            # Don't duplicate if already captured by signature detection
            already_captured = any(
                set(names) <= set(c["failures"]) for c in cascades
            )
            if not already_captured:
                cascades.append({
                    "type": "time_proximity",
                    "name": "simultaneous_failures",
                    "description": f"{len(group)} failures within 5 minutes — likely shared root cause",
                    "severity": "warning",
                    "failures": names,
                    "count": len(group),
                    "timeWindow": f"{group[0][0].isoformat()} to {group[-1][0].isoformat()}",
                    "recommendation": "Investigate shared dependencies before fixing individually"
                })

    # Source correlation: 3+ cron failures = likely systemic
    cron_failures = [f for f in failures if f.get("source") == "cron"]
    if len(cron_failures) >= 3:
        already_captured = any(c["type"] == "signature" for c in cascades)
        if not already_captured:
            cascades.append({
                "type": "source_correlation",
                "name": "mass_cron_failure",
                "description": f"{len(cron_failures)} cron jobs in error state — systemic issue likely",
                "severity": "critical",
                "failures": [f.get("name", "unknown") for f in cron_failures],
                "count": len(cron_failures),
                "recommendation": "Check gateway status, git locks, and shared dependencies before fixing individual crons"
            })

    return cascades


# ─── Scanners ──────────────────────────────────────────────────────────────────

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
                    except:
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


def get_deploy_failures(hours=6):
    """Check for recent deploy/git push failures in common log locations."""
    failures = []
    log_dir = Path("/tmp")
    cutoff_time = time.time() - (hours * 3600)

    # Scan any log files in /tmp that might contain errors
    log_patterns = ["compare-batch.log", "fulfillment.log", "compare-gen-*.log"]
    for pattern in log_patterns:
        for log_path in log_dir.glob(pattern):
            if not log_path.is_file():
                continue
            if log_path.stat().st_mtime < cutoff_time:
                continue
            try:
                content = log_path.read_text()
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
                        break
            except Exception:
                pass
    return failures


# ─── Main ──────────────────────────────────────────────────────────────────────

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

    # Detect cascading failures
    cascades = detect_cascades(all_failures)

    # Sort individual failures by severity
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    all_failures.sort(key=lambda f: severity_order.get(f.get("severity", "info"), 3))

    if output_json:
        print(json.dumps({
            "failures": all_failures,
            "cascades": cascades,
            "summary": {
                "totalFailures": len(all_failures),
                "totalCascades": len(cascades),
                "hasCritical": any(f.get("severity") == "critical" for f in all_failures),
                "hasCascade": len(cascades) > 0
            }
        }, indent=2))
    else:
        if not all_failures:
            print(f"✅ No failures detected in the last {hours} hours.")
        else:
            # Show cascades first (most important)
            if cascades:
                print(f"⚡ {len(cascades)} cascading failure group(s) detected:\n")
                for c in cascades:
                    icon = {"critical": "🔴", "warning": "🟡"}.get(c["severity"], "⚪")
                    print(f"  {icon} [{c['type']}] {c['description']}")
                    print(f"     Affected: {', '.join(c['failures'][:5])}{'...' if len(c['failures']) > 5 else ''}")
                    print(f"     → {c['recommendation']}")
                    print()

            print(f"🔍 {len(all_failures)} individual failure(s) in the last {hours} hours:\n")
            for f in all_failures:
                icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(f["severity"], "⚪")
                print(f"  {icon} [{f['source']}] {f['name']}")
                print(f"     Error: {f['error'][:200]}")
                print(f"     Time: {f['timestamp']}")
                print()


if __name__ == "__main__":
    main()
