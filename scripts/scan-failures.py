#!/usr/bin/env python3
"""
scan-failures.py — Scan for failures across multiple sources using a plugin architecture.
Includes cascading failure detection — groups related failures that likely share a root cause.

Usage:
  python3 scan-failures.py [--hours N] [--json] [--source NAME] [--config PATH]

Options:
  --hours N       Look back N hours (default: 6)
  --json          Output raw JSON (default: human-readable summary)
  --source NAME   Scan only this source (can be repeated). Default: all configured sources.
  --config PATH   Path to config file (YAML or JSON). Default: auto-detect.

Backward compatible: if no config or source is specified, scans OpenClaw + default log paths.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add parent dir to path so we can import sources/
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SKILL_DIR))

from sources import get_source, get_all_sources, list_sources


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


def load_config(config_path=None):
    """Load config from file, auto-detecting format. Returns dict or None."""
    if config_path:
        p = Path(config_path)
        if not p.exists():
            print(f"Warning: config file not found: {config_path}", file=sys.stderr)
            return None
        return _parse_config_file(p)

    # Auto-detect config in skill dir or workspace
    for candidate in [
        SKILL_DIR / "self-healing.yaml",
        SKILL_DIR / "self-healing.yml",
        SKILL_DIR / "self-healing.json",
    ]:
        if candidate.exists():
            return _parse_config_file(candidate)

    return None


def _parse_config_file(path: Path) -> dict:
    """Parse a YAML or JSON config file."""
    content = path.read_text()
    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml
            return yaml.safe_load(content)
        except ImportError:
            print("Warning: PyYAML not installed, falling back to JSON config", file=sys.stderr)
            return None
    else:
        return json.loads(content)


def merge_cascade_signatures(config):
    """Merge user-defined cascade signatures with defaults."""
    merged = dict(CASCADE_SIGNATURES)
    if config and "cascades" in config:
        merged.update(config["cascades"])
    return merged


def detect_cascades(failures, cascade_sigs=None):
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

    sigs = cascade_sigs or CASCADE_SIGNATURES
    cascades = []

    # Check for known cascade signatures across all failure errors
    for cascade_name, sig in sigs.items():
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


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    hours = 6
    output_json = False
    source_names = []
    config_path = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--hours" and i + 1 < len(args):
            hours = int(args[i + 1])
            i += 2
        elif args[i] == "--json":
            output_json = True
            i += 1
        elif args[i] == "--source" and i + 1 < len(args):
            source_names.append(args[i + 1])
            i += 2
        elif args[i] == "--config" and i + 1 < len(args):
            config_path = args[i + 1]
            i += 2
        else:
            i += 1

    # Load config
    config = load_config(config_path)

    # Merge cascade signatures
    cascade_sigs = merge_cascade_signatures(config)

    # Determine which sources to scan
    all_failures = []

    if source_names:
        # Explicit sources requested
        for name in source_names:
            try:
                src_config = config.get("sources", {}).get(name, {}) if config else {}
                source = get_source(name, src_config if src_config else None)
                all_failures.extend(source.scan(hours))
            except KeyError as e:
                print(f"Warning: {e}", file=sys.stderr)
    elif config:
        # Use config to determine sources
        sources = get_all_sources(config)
        for source in sources:
            all_failures.extend(source.scan(hours))
    else:
        # Backward compatible: try OpenClaw + default logfile scanning
        try:
            openclaw_src = get_source("openclaw")
            all_failures.extend(openclaw_src.scan(hours))
        except Exception:
            pass

        try:
            logfile_src = get_source("logfile")
            all_failures.extend(logfile_src.scan(hours))
        except Exception:
            pass

    # Detect cascading failures
    cascades = detect_cascades(all_failures, cascade_sigs)

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
