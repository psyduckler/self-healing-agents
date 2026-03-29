"""
Healer module — known-fixes database manager for AI self-healing.

Provides: check, log, list, stats, risk commands.
Refactored from scripts/self-heal.py for package use.
"""

import json
import math
import os
import re
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# Resolve workspace — prefer OPENCLAW_WORKSPACE env, fall back to ~/.openclaw/workspace
WORKSPACE = Path(os.environ.get("OPENCLAW_WORKSPACE", Path.home() / ".openclaw" / "workspace"))
DB_PATH = WORKSPACE / "known-fixes.json"
RISK_PATH = WORKSPACE / "risk-profiles.json"

# ─── Matching Engine (v2) ──────────────────────────────────────────────────────

ERROR_CLASSES = {
    "file_not_found": [r"FileNotFoundError", r"No such file or directory", r"ENOENT", r"File not found"],
    "permission": [r"Permission denied", r"EACCES", r"PermissionError", r"Operation not permitted"],
    "connection": [r"Connection refused", r"ECONNREFUSED", r"ConnectionError", r"Connection reset"],
    "timeout": [r"timeout", r"Timeout", r"ETIMEDOUT", r"timed out", r"TimeoutError"],
    "rate_limit": [r"429", r"rate limit", r"Too Many Requests", r"RateLimitError"],
    "auth": [r"401", r"403", r"Unauthorized", r"Forbidden", r"AuthenticationError"],
    "json_parse": [r"JSONDecodeError", r"JSON\.parse", r"Unexpected token", r"Unterminated string"],
    "import": [r"ModuleNotFoundError", r"ImportError", r"Cannot find module", r"No module named"],
    "git_push": [r"git push.*rejected", r"remote.*ahead", r"failed to push", r"non-fast-forward"],
    "disk": [r"No space left", r"ENOSPC", r"disk full", r"Disk quota exceeded"],
    "memory": [r"MemoryError", r"OOM", r"Out of memory", r"ENOMEM", r"JavaScript heap"],
}


def classify_error(text):
    """Return set of error classes that match the text."""
    classes = set()
    for cls, patterns in ERROR_CLASSES.items():
        for p in patterns:
            if re.search(p, text, re.IGNORECASE):
                classes.add(cls)
                break
    return classes


def extract_paths(text):
    """Extract file/directory paths from error text."""
    paths = set(re.findall(r'(?:/[\w._-]+){2,}', text))
    paths.update(re.findall(r"['\"]([/~][\w._/-]+)['\"]", text))
    return paths


def ngram_overlap(text1, text2, n=3):
    """Character n-gram overlap ratio between two strings."""
    if len(text1) < n or len(text2) < n:
        return 0.0
    grams1 = Counter(text1[i:i+n] for i in range(len(text1) - n + 1))
    grams2 = Counter(text2[i:i+n] for i in range(len(text2) - n + 1))
    intersection = sum((grams1 & grams2).values())
    union = sum((grams1 | grams2).values())
    return intersection / union if union > 0 else 0.0


def smart_match(error_text, pattern, pattern_regex=None):
    """
    Multi-signal matching. Returns a score 0.0-1.0 with explanation.
    """
    signals = []
    error_lower = error_text.lower()
    pattern_lower = pattern.lower()

    # Signal 1: Regex match
    if pattern_regex:
        try:
            if re.search(pattern_regex, error_text, re.IGNORECASE):
                signals.append(("regex", 0.90))
        except re.error:
            pass

    # Signal 2: Exact substring
    if pattern_lower in error_lower:
        signals.append(("substring", 0.95))
    elif error_lower in pattern_lower:
        signals.append(("substring_reverse", 0.88))

    # Signal 3: Token overlap
    stop_words = {"the", "a", "an", "is", "was", "in", "at", "to", "for", "of", "on", "and", "or", "not"}
    error_tokens = set(error_lower.split()) - stop_words
    pattern_tokens = set(pattern_lower.split()) - stop_words
    if pattern_tokens:
        token_overlap = len(error_tokens & pattern_tokens) / len(pattern_tokens)
        if token_overlap > 0.3:
            signals.append(("token_overlap", min(token_overlap * 0.8, 0.80)))

    # Signal 4: Error class match
    error_classes = classify_error(error_text)
    pattern_classes = classify_error(pattern)
    if error_classes and pattern_classes:
        class_overlap = error_classes & pattern_classes
        if class_overlap:
            signals.append(("error_class", 0.75))

    # Signal 5: Path similarity
    error_paths = extract_paths(error_text)
    pattern_paths = extract_paths(pattern)
    if error_paths and pattern_paths:
        error_parts = set()
        for p in error_paths:
            error_parts.update(p.split("/"))
        pattern_parts = set()
        for p in pattern_paths:
            pattern_parts.update(p.split("/"))
        error_parts.discard("")
        pattern_parts.discard("")
        if pattern_parts:
            path_overlap = len(error_parts & pattern_parts) / len(pattern_parts)
            if path_overlap > 0.3:
                signals.append(("path_similarity", min(path_overlap * 0.7, 0.70)))

    # Signal 6: N-gram overlap
    ngram_score = ngram_overlap(error_lower, pattern_lower)
    if ngram_score > 0.2:
        signals.append(("ngram", min(ngram_score * 1.1, 0.85)))

    if not signals:
        return 0.0, []

    signals.sort(key=lambda s: s[1], reverse=True)
    best_score = signals[0][1]

    if len(signals) >= 3:
        best_score = min(best_score + 0.03, 1.0)
    if len(signals) >= 4:
        best_score = min(best_score + 0.02, 1.0)

    return round(best_score, 3), signals


# ─── Risk Scoring Engine ───────────────────────────────────────────────────────

DEFAULT_RISK_PROFILES = {
    "static_site": {
        "description": "Static site builds, content pages, blog posts",
        "keywords": ["html", "static", "content", "blog", "page", "compare", "popular-picks", "itinerary", "resource"],
        "baseRisk": 0.2,
        "reversible": True,
        "userFacing": True,
        "dataLoss": False
    },
    "cron_job": {
        "description": "Scheduled cron tasks",
        "keywords": ["cron", "scheduled", "heartbeat", "periodic"],
        "baseRisk": 0.3,
        "reversible": True,
        "userFacing": False,
        "dataLoss": False
    },
    "social_media": {
        "description": "Social media posts (Instagram, X/Twitter, Pinterest)",
        "keywords": ["instagram", "twitter", "pinterest", "reel", "post", "tweet", "pin"],
        "baseRisk": 0.5,
        "reversible": False,
        "userFacing": True,
        "dataLoss": False
    },
    "email": {
        "description": "Outbound emails to users/customers",
        "keywords": ["email", "send", "resend", "smtp", "customer", "notification"],
        "baseRisk": 0.7,
        "reversible": False,
        "userFacing": True,
        "dataLoss": False
    },
    "payment": {
        "description": "Payment processing, orders, Stripe",
        "keywords": ["payment", "stripe", "order", "charge", "refund", "billing", "invoice"],
        "baseRisk": 0.9,
        "reversible": False,
        "userFacing": True,
        "dataLoss": True
    },
    "deployment": {
        "description": "Git push, deploy, infrastructure changes",
        "keywords": ["deploy", "git push", "cloudflare", "production", "infrastructure"],
        "baseRisk": 0.5,
        "reversible": True,
        "userFacing": True,
        "dataLoss": False
    },
    "config": {
        "description": "Configuration changes, API keys, environment",
        "keywords": ["config", "openclaw.json", "env", "api key", "secret", "gateway"],
        "baseRisk": 0.8,
        "reversible": True,
        "userFacing": False,
        "dataLoss": False
    },
    "database": {
        "description": "Database operations, data mutations",
        "keywords": ["database", "db", "sql", "delete", "drop", "migrate", "mutation"],
        "baseRisk": 0.9,
        "reversible": False,
        "userFacing": True,
        "dataLoss": True
    }
}


def load_risk_profiles():
    """Load risk profiles, merging user overrides with defaults."""
    profiles = dict(DEFAULT_RISK_PROFILES)
    if RISK_PATH.exists():
        try:
            user_profiles = json.loads(RISK_PATH.read_text())
            profiles.update(user_profiles)
        except json.JSONDecodeError:
            pass
    return profiles


def score_risk(description, fix_type="heal"):
    """Score the risk of applying a fix. Returns 0.0-1.0 with reasoning."""
    profiles = load_risk_profiles()
    desc_lower = description.lower()

    matched = []
    for name, profile in profiles.items():
        keyword_hits = sum(1 for kw in profile["keywords"] if kw in desc_lower)
        if keyword_hits > 0:
            matched.append((name, profile, keyword_hits))

    matched.sort(key=lambda x: x[2], reverse=True)

    if not matched:
        base_risk = 0.5
        reasoning = ["Unknown system type — defaulting to moderate risk"]
        profile_name = "unknown"
    else:
        profile_name, profile, _ = matched[0]
        base_risk = profile["baseRisk"]
        reasoning = [f"Matched profile: {profile_name} ({profile['description']})"]
        if not profile.get("reversible", True):
            reasoning.append("⚠️ Not easily reversible")
        if profile.get("dataLoss", False):
            reasoning.append("⚠️ Potential data loss")
        if profile.get("userFacing", False):
            reasoning.append("User-facing system")

    fix_modifiers = {"retry": -0.15, "patch": 0.0, "heal": 0.1}
    modifier = fix_modifiers.get(fix_type, 0.05)
    reasoning.append(f"Fix type '{fix_type}': {'reduces' if modifier < 0 else 'increases'} risk by {abs(modifier):.0%}")

    final_risk = max(0.0, min(1.0, base_risk + modifier))

    if final_risk <= 0.3:
        decision = "auto_apply"
        decision_text = "✅ Low risk — safe to auto-apply"
    elif final_risk <= 0.6:
        decision = "apply_with_caution"
        decision_text = "⚠️ Moderate risk — apply but verify carefully"
    elif final_risk <= 0.8:
        decision = "human_review"
        decision_text = "🔶 High risk — recommend human review before applying"
    else:
        decision = "escalate"
        decision_text = "🔴 Critical risk — escalate to human, do not auto-apply"

    return {
        "riskScore": round(final_risk, 2),
        "decision": decision,
        "decisionText": decision_text,
        "profile": profile_name,
        "reasoning": reasoning
    }


# ─── Commands ──────────────────────────────────────────────────────────────────

def load_db():
    if DB_PATH.exists():
        try:
            return json.loads(DB_PATH.read_text())
        except json.JSONDecodeError:
            return []
    return []


def save_db(db):
    DB_PATH.write_text(json.dumps(db, indent=2) + "\n")


def cmd_check(error_text):
    """Search known fixes with smart multi-signal matching."""
    db = load_db()
    if not db:
        print(json.dumps({"match": False, "message": "Known-fixes database is empty. No matches possible."}))
        return

    matches = []
    for entry in db:
        score, signals = smart_match(error_text, entry.get("pattern", ""), entry.get("patternRegex"))
        if score >= 0.5:
            matches.append({
                **entry,
                "confidence": score,
                "matchSignals": [{"signal": s[0], "strength": s[1]} for s in signals]
            })

    matches.sort(key=lambda x: x["confidence"], reverse=True)

    if matches:
        best = matches[0]
        risk = score_risk(
            f"{best.get('source', 'unknown')} {best.get('pattern', '')} {' '.join(best.get('filesChanged', []))}",
            best.get("fixType", "heal")
        )
        auto_apply = best["confidence"] >= 0.8 and risk["decision"] in ("auto_apply", "apply_with_caution")

        print(json.dumps({
            "match": True,
            "confidence": best["confidence"],
            "autoApply": auto_apply,
            "matchSignals": best["matchSignals"],
            "risk": risk,
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
        error_classes = classify_error(error_text)
        print(json.dumps({
            "match": False,
            "errorClasses": list(error_classes) if error_classes else ["unknown"],
            "message": "No known fix for this error pattern. Diagnosis needed.",
            "suggestion": "After fixing, run `self-heal log` to record the fix for future matching."
        }, indent=2))


def cmd_log(error, cause, fix, fix_type="heal", files_changed=None, commit=None,
            risk_level=None, severity=None, source=None):
    """Log a new known fix to the database."""
    db = load_db()

    # Check for existing similar pattern using smart matching
    for entry in db:
        score, _ = smart_match(error, entry.get("pattern", ""), entry.get("patternRegex"))
        if score >= 0.85:
            entry["healCount"] = entry.get("healCount", 1) + 1
            entry["timestamp"] = datetime.now(timezone.utc).isoformat()
            if commit:
                entry["commit"] = commit
            save_db(db)
            print(json.dumps({
                "action": "updated",
                "id": entry["id"],
                "healCount": entry["healCount"],
                "message": f"Updated existing fix (seen {entry['healCount']} times)"
            }, indent=2))
            return

    # Create new entry
    pattern_regex = re.sub(r'[/\\][\w._-]+', r'[/\\\\][\\w.-]+', re.escape(error))
    error_classes = classify_error(error)

    entry = {
        "id": str(uuid.uuid4())[:8],
        "pattern": error,
        "patternRegex": pattern_regex,
        "errorClasses": list(error_classes),
        "cause": cause,
        "fix": fix,
        "fixType": fix_type,
        "riskLevel": risk_level or "",
        "severity": severity or "warning",
        "filesChanged": files_changed or [],
        "commit": commit or "",
        "source": source or "manual",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "healCount": 1
    }

    db.append(entry)
    save_db(db)
    print(json.dumps({
        "action": "created",
        "id": entry["id"],
        "errorClasses": entry["errorClasses"],
        "message": f"Logged new known fix: {entry['cause'][:80]}"
    }, indent=2))


def cmd_log_from_args(args):
    """Parse log args from CLI argument list (backward compat)."""
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
        print("Usage: self-heal log --error '...' --cause '...' --fix '...' --fix-type heal")
        sys.exit(1)

    files_changed = params.get("files_changed", "").split(",") if params.get("files_changed") else None

    cmd_log(
        error=params["error"],
        cause=params["cause"],
        fix=params["fix"],
        fix_type=params.get("fix_type", "heal"),
        files_changed=files_changed,
        commit=params.get("commit"),
        risk_level=params.get("risk_level"),
        severity=params.get("severity"),
        source=params.get("source"),
    )


def cmd_risk(description):
    """Score the risk of a fix or system change."""
    risk = score_risk(description)
    print(json.dumps(risk, indent=2))


def cmd_list():
    """List all known fixes."""
    db = load_db()
    if not db:
        print("No known fixes recorded yet.")
        return

    print(f"📋 {len(db)} known fix(es):\n")
    for entry in db:
        icon = {"heal": "🩹", "patch": "🔧", "retry": "🔄"}.get(entry.get("fixType", ""), "❓")
        classes = entry.get("errorClasses", [])
        class_str = f" [{', '.join(classes)}]" if classes else ""
        print(f"  {icon} [{entry.get('id', '?')}] {entry.get('pattern', 'unknown')[:80]}{class_str}")
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
    by_class = {}
    for e in db:
        for c in e.get("errorClasses", []):
            by_class[c] = by_class.get(c, 0) + 1

    print(json.dumps({
        "totalPatterns": len(db),
        "totalHeals": total_heals,
        "byType": by_type,
        "bySource": by_source,
        "byErrorClass": by_class,
        "mostCommon": sorted(db, key=lambda e: e.get("healCount", 1), reverse=True)[0].get("pattern", "")[:80] if db else None
    }, indent=2))


def main():
    """CLI entry point for self-heal.py (backward compat)."""
    if len(sys.argv) < 2:
        print("Usage: self-heal <command> [args]")
        print("Commands: check, log, list, stats, risk")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "check":
        if len(sys.argv) < 3:
            print("Usage: self-heal check \"<error message>\"")
            sys.exit(1)
        cmd_check(sys.argv[2])
    elif cmd == "log":
        cmd_log_from_args(sys.argv[2:])
    elif cmd == "list":
        cmd_list()
    elif cmd == "stats":
        cmd_stats()
    elif cmd == "risk":
        if len(sys.argv) < 3:
            print("Usage: self-heal risk \"<description of system/fix>\"")
            sys.exit(1)
        cmd_risk(sys.argv[2])
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
