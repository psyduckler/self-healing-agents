---
name: self-healing
description: "AI self-healing error handler. Use when a cron job fails, a sub-agent crashes, a deploy breaks, a script errors, or any automated process reports a failure. Also use proactively during heartbeats to scan for recent failures. Detects failures, diagnoses root causes, applies fixes (preferring permanent fixes over band-aids), verifies the fix works, and logs everything to a known-fixes database for faster future resolution. Triggers on error handling, failure recovery, self-healing, diagnose error, fix broken, cron failed, deploy failed, sub-agent crashed, script error."
---

# Self-Healing

Autonomous error detection, diagnosis, and repair for OpenClaw agents.

## Overview

Self-healing turns your agent from "alert and wait for human" into "detect, diagnose, fix, verify, and learn." It's not retry logic — it's root-cause analysis and permanent fixes.

## Architecture

```
Failure Signal → Triage → Diagnosis → Fix → Verify → Log
                   ↓                           ↑
              Known Fixes DB ─── match? ───────┘
```

## Files

- `scripts/self-heal.py` — CLI entry point for diagnosing and healing errors
- `scripts/scan-failures.py` — Scans cron jobs, recent sub-agents, and logs for failures
- `references/error-patterns.md` — Common error patterns and their root causes
- `known-fixes.json` lives in your workspace root (created on first run)

## When This Skill Activates

1. **Reactive:** A failure is reported (cron error, sub-agent crash, deploy failure, script error)
2. **Proactive:** During heartbeats, run the scanner to catch silent failures
3. **Manual:** Human asks you to investigate/fix something broken

## Workflow

### Step 1: Detect

Gather failure context. Run the scanner to find recent failures:

```bash
python3 <skill-dir>/scripts/scan-failures.py
```

This outputs a JSON array of detected failures with:
- `source` (cron | subagent | exec | deploy)
- `id` (cron job ID, session key, etc.)
- `name` (human-readable label)
- `error` (error message or status)
- `timestamp` (when it failed)
- `severity` (critical | warning | info)

### Step 2: Triage

For each failure, check the known-fixes database:

```bash
python3 <skill-dir>/scripts/self-heal.py check "<error_message_or_pattern>"
```

If a known fix exists, the script returns the fix details and confidence score. If confidence ≥ 0.8, apply it directly. Otherwise, proceed to manual diagnosis.

### Step 3: Diagnose

For unknown errors, investigate the root cause:

1. Read error logs/output from the failed process
2. Trace the error to its source (file, config, dependency, external service)
3. Determine if the issue is:
   - **Transient** (network timeout, rate limit, temporary outage) → retry is appropriate
   - **Environmental** (file missing, path wrong, permissions) → fix the environment
   - **Code bug** (logic error, bad assumption) → fix the code
   - **External** (API changed, service down) → adapt or wait

### Step 4: Fix

Apply the fix. Always prefer *permanent* fixes over band-aids:

| Level | Example | When to use |
|-------|---------|-------------|
| **Retry** | Re-run the job | Transient errors only |
| **Patch** | Recreate a deleted file | You're sure the root cause won't recur |
| **Heal** | Move file from /tmp to permanent path + update code | The root cause is structural |

After applying the fix:
- If code was changed: commit with descriptive message prefixed `fix:`
- If config was changed: verify with restart/reload

### Step 5: Verify

Always verify the fix works:

1. Re-run the failed operation
2. Check for the expected output (file exists, page returns 200, job succeeds)
3. If verification fails: revert and escalate to human

### Step 6: Log

Record the incident in the known-fixes database:

```bash
python3 <skill-dir>/scripts/self-heal.py log \
  --error "<error pattern>" \
  --cause "<root cause>" \
  --fix "<what was done>" \
  --fix-type "retry|patch|heal" \
  --files-changed "file1.py,file2.sh" \
  --commit "<hash if applicable>"
```

This appends to `known-fixes.json` in your workspace root.

## Escalation Rules

Escalate to human instead of self-healing when:

- The fix requires changing auth credentials or API keys
- The error involves data loss or corruption
- You've already tried fixing and it failed
- The fix would change user-facing behavior
- Confidence in diagnosis is low
- The system is in a degraded state with multiple simultaneous failures

## Heartbeat Integration

Add to your HEARTBEAT.md:

```markdown
## Self-Healing Scan (every heartbeat)
Run: `python3 <skill-dir>/scripts/scan-failures.py`
- If failures found: attempt self-heal workflow for each
- Post to #mission-control: `🔧 Self-healing: [what was fixed]` or `🚨 Needs attention: [what failed and why]`
```

### No Repeat Notifications

Once you've reported a self-heal to a channel, **do not re-report the same fix on subsequent heartbeats.** Use the notification dedup system:

1. **Before notifying:** Check if already reported:
   ```bash
   self-heal notified "<error message>"
   ```
   If `alreadyNotified: true` → skip the notification silently.

2. **After notifying:** Mark it:
   ```bash
   self-heal mark-notified "<error message>" --fix-id "<id>" --fix "<what was done>"
   ```

3. **If the same error recurs** (fix didn't hold) → that's a *new* occurrence. Clear the old notification and report again:
   ```bash
   self-heal clear-notified "<fix-id>"
   ```

This prevents noisy channels where the same "🔧 Self-healed: re-enabled X" message appears every 30 minutes. Only genuinely new heals get reported.

## Known Fixes Database Schema

`known-fixes.json` stores learned fixes:

```json
[
  {
    "id": "uuid",
    "pattern": "FileNotFoundError: /tmp/compare-shell-template.json",
    "patternRegex": "FileNotFoundError.*\\/tmp\\/.*template",
    "cause": "macOS /tmp cleanup removed file from volatile directory",
    "fix": "Move file to permanent location, update code to use relative path",
    "fixType": "heal",
    "severity": "critical",
    "filesChanged": ["scripts/batch-compare-gen.py", "scripts/compare-shell-template.json"],
    "commit": "b605c306",
    "timestamp": "2026-03-29T06:21:02Z",
    "source": "cron",
    "healCount": 1
  }
]
```

When `check` finds a match (regex or fuzzy on `pattern`), it returns the entry so the agent can apply the known fix immediately — or adapt it if the context differs.
