#!/usr/bin/env python3
"""
self-heal.py — Known-fixes database manager for AI self-healing.

Commands:
  check "<error message>"     Search for matching known fix
  log --error "..." --cause "..." --fix "..." --fix-type heal [--files-changed f1,f2] [--commit hash]
  list                        List all known fixes
  stats                       Show self-healing statistics

The known-fixes database lives at WORKSPACE/known-fixes.json
"""

import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Resolve workspace — prefer OPENCLAW_WORKSPACE env, fall back to ~/.openclaw/workspace
WORKSPACE = Path(os.environ.get("OPENCLAW_WORKSPACE", Path.home() / ".openclaw" / "workspace"))
DB_PATH = WORKSPACE / "known-fixes.json"


def load_db():
    if DB_PATH.exists():
        try:
            return json.loads(DB_PATH.read_text())
        except json.JSONDecodeError:
            return []
    return []


def save_db(db):
    DB_PATH.write_text(json.dumps(db, indent=2) + "\n")


def fuzzy_match(error_text, pattern, pattern_regex=None):
    """Score how well an error matches a known pattern. Returns 0.0-1.0."""
    score = 0.0

    # Try regex match first (highest confidence)
    if pattern_regex:
        try:
            if re.search(pattern_regex, error_text, re.IGNORECASE):
                score = max(score, 0.9)
        except re.error:
            pass

    # Exact substring match
    if pattern.lower() in error_text.lower():
        score = max(score, 0.95)

    # Word overlap scoring
    error_words = set(error_text.lower().split())
    pattern_words = set(pattern.lower().split())
    if pattern_words:
        overlap = len(error_words & pattern_words) / len(pattern_words)
        score = max(score, overlap * 0.8)

    # Key phrase matching (common error signatures)
    error_signatures = [
        r"FileNotFoundError",
        r"Permission denied",
        r"Connection refused",
        r"rate limit",
        r"timeout",
        r"No such file",
        r"Module not found",
        r"ImportError",
        r"git push.*rejected",
        r"remote.*ahead",
    ]
    for sig in error_signatures:
        if re.search(sig, error_text, re.IGNORECASE) and re.search(sig, pattern, re.IGNORECASE):
            score = max(score, 0.85)

    return round(score, 2)


def cmd_check(error_text):
    """Search known fixes for a matching error pattern."""
    db = load_db()
    if not db:
        print(json.dumps({"match": False, "message": "Known-fixes database is empty. No matches possible."}))
        return

    matches = []
    for entry in db:
        score = fuzzy_match(error_text, entry.get("pattern", ""), entry.get("patternRegex"))
        if score >= 0.5:
            matches.append({**entry, "confidence": score})

    matches.sort(key=lambda x: x["confidence"], reverse=True)

    if matches:
        best = matches[0]
        print(json.dumps({
            "match": True,
            "confidence": best["confidence"],
            "autoApply": best["confidence"] >= 0.8,
            "knownFix": {
                "id": best.get("id"),
                "pattern": best.get("pattern"),
                "cause": best.get("cause"),
                "fix": best.get("fix"),
                "fixType": best.get("fixType"),
                "filesChanged": best.get("filesChanged", []),
                "healCount": best.get("healCount", 1),
                "lastSeen": best.get("timestamp")
            },
            "alternateMatches": len(matches) - 1
        }, indent=2))
    else:
        print(json.dumps({
            "match": False,
            "message": f"No known fix for this error pattern. Diagnosis needed.",
            "suggestion": "After fixing, run `self-heal.py log` to record the fix for future matching."
        }, indent=2))


def cmd_log(args):
    """Log a new known fix to the database."""
    # Parse args
    params = {}
    i = 0
    while i < len(args):
        if args[i].startswith("--") and i + 1 < len(args):
            key = args[i][2:].replace("-", "_")
            params[key] = args[i + 1]
            i += 2
        else:
            i += 1

    required = ["error", "cause", "fix"]
    missing = [k for k in required if k not in params]
    if missing:
        print(f"Error: Missing required params: {', '.join('--' + k for k in missing)}")
        print("Usage: self-heal.py log --error '...' --cause '...' --fix '...' --fix-type heal")
        sys.exit(1)

    db = load_db()

    # Check for existing similar pattern — update heal count instead of duplicating
    for entry in db:
        score = fuzzy_match(params["error"], entry.get("pattern", ""), entry.get("patternRegex"))
        if score >= 0.85:
            entry["healCount"] = entry.get("healCount", 1) + 1
            entry["timestamp"] = datetime.now(timezone.utc).isoformat()
            if params.get("commit"):
                entry["commit"] = params["commit"]
            save_db(db)
            print(json.dumps({
                "action": "updated",
                "id": entry["id"],
                "healCount": entry["healCount"],
                "message": f"Updated existing fix (seen {entry['healCount']} times)"
            }, indent=2))
            return

    # Create new entry
    # Auto-generate a basic regex from the error message
    error_text = params["error"]
    # Escape special chars but keep key identifiers
    pattern_regex = re.sub(r'[/\\][\w.-]+', r'[/\\\\][\\w.-]+', re.escape(error_text))

    entry = {
        "id": str(uuid.uuid4())[:8],
        "pattern": error_text,
        "patternRegex": pattern_regex,
        "cause": params["cause"],
        "fix": params["fix"],
        "fixType": params.get("fix_type", "heal"),
        "severity": params.get("severity", "warning"),
        "filesChanged": params.get("files_changed", "").split(",") if params.get("files_changed") else [],
        "commit": params.get("commit", ""),
        "source": params.get("source", "manual"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "healCount": 1
    }

    db.append(entry)
    save_db(db)
    print(json.dumps({
        "action": "created",
        "id": entry["id"],
        "message": f"Logged new known fix: {entry['cause'][:80]}"
    }, indent=2))


def cmd_list():
    """List all known fixes."""
    db = load_db()
    if not db:
        print("No known fixes recorded yet.")
        return

    print(f"📋 {len(db)} known fix(es):\n")
    for entry in db:
        icon = {"heal": "🩹", "patch": "🔧", "retry": "🔄"}.get(entry.get("fixType", ""), "❓")
        print(f"  {icon} [{entry.get('id', '?')}] {entry.get('pattern', 'unknown')[:80]}")
        print(f"     Cause: {entry.get('cause', 'unknown')[:100]}")
        print(f"     Fix: {entry.get('fix', 'unknown')[:100]}")
        print(f"     Type: {entry.get('fixType', '?')} | Healed: {entry.get('healCount', 1)}x | Last: {entry.get('timestamp', '?')[:10]}")
        print()


def cmd_stats():
    """Show self-healing statistics."""
    db = load_db()
    if not db:
        print(json.dumps({"totalFixes": 0, "totalHeals": 0}))
        return

    total_heals = sum(e.get("healCount", 1) for e in db)
    by_type = {}
    for e in db:
        ft = e.get("fixType", "unknown")
        by_type[ft] = by_type.get(ft, 0) + 1

    by_source = {}
    for e in db:
        src = e.get("source", "unknown")
        by_source[src] = by_source.get(src, 0) + 1

    print(json.dumps({
        "totalPatterns": len(db),
        "totalHeals": total_heals,
        "byType": by_type,
        "bySource": by_source,
        "mostCommon": sorted(db, key=lambda e: e.get("healCount", 1), reverse=True)[0].get("pattern", "")[:80] if db else None
    }, indent=2))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "check":
        if len(sys.argv) < 3:
            print("Usage: self-heal.py check \"<error message>\"")
            sys.exit(1)
        cmd_check(sys.argv[2])
    elif cmd == "log":
        cmd_log(sys.argv[2:])
    elif cmd == "list":
        cmd_list()
    elif cmd == "stats":
        cmd_stats()
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
