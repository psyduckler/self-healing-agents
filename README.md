# 🩹 Self-Healing Agents

**Autonomous error detection, diagnosis, and repair for AI agents.**

When your AI agent breaks at 2 AM, it shouldn't page a human. It should fix itself.

Self-healing turns AI agents from "alert and wait" into "detect, diagnose, fix, verify, and learn." It's not retry logic — it's root-cause analysis and permanent fixes.

## What is AI Self-Healing?

AI self-healing is when an agent autonomously:

1. **Detects** a failure (cron error, crashed sub-agent, broken deploy)
2. **Diagnoses** the root cause (not just the symptom)
3. **Fixes** the issue (preferring permanent fixes over band-aids)
4. **Verifies** the fix works
5. **Logs** what happened so it's faster next time

> 📖 Read the full explainer: **[What is AI Self-Healing?](https://tabiji.ai/resources/what-is-ai-self-healing/)**

## The Real Incident That Started This

At 1:24 AM on March 29, 2026, a cron job on [tabiji.ai](https://tabiji.ai) failed. A Python script couldn't find its template file — macOS had cleaned `/tmp`.

No human was awake. The AI agent (running on [OpenClaw](https://github.com/openclaw/openclaw)):

1. Received the failure notification
2. Read the error, traced it to the volatile `/tmp` directory
3. Moved the template to a permanent, version-controlled location
4. Updated the code to use relative paths
5. Committed the fix, rebuilt the failed page, and resumed operations

By the time the human checked in at 9 AM, everything was already fixed. That incident became the seed for this project.

## What's Included

### `scripts/scan-failures.py`

Scans your environment for recent failures:

```bash
python3 scripts/scan-failures.py
```

```
🔍 Found 2 failure(s) in the last 6 hours:

  🟡 [cron] used-chatgpt-reel-daily
     Error: Cron job 'used-chatgpt-reel-daily' in error state
     Time: 2026-03-29T14:54:39

  🔴 [subagent] compare-page-builder
     Error: FileNotFoundError: /tmp/compare-shell-template.json
     Time: 2026-03-29T06:24:01
```

Scans:
- **Cron jobs** — checks for error/timeout status
- **Sub-agents** — checks recent runs for crashes
- **Deploy logs** — scans common log paths for error patterns

### `scripts/self-heal.py`

Known-fixes database — learns from every fix so it's faster next time:

```bash
# Check if an error matches a known fix
python3 scripts/self-heal.py check "FileNotFoundError: /tmp/some-template.json"
```

```json
{
  "match": true,
  "confidence": 0.85,
  "autoApply": true,
  "knownFix": {
    "cause": "macOS /tmp cleanup removed file from volatile directory",
    "fix": "Move file to permanent location, update code to use relative path",
    "fixType": "heal",
    "healCount": 1
  }
}
```

```bash
# Log a new fix after you've healed something
python3 scripts/self-heal.py log \
  --error "git push rejected: remote ahead" \
  --cause "Concurrent pushes from multiple agents" \
  --fix "Add git pull --rebase before push" \
  --fix-type heal

# List all known fixes
python3 scripts/self-heal.py list

# Show stats
python3 scripts/self-heal.py stats
```

### `references/error-patterns.md`

Quick-reference guide for common error patterns, likely causes, and fix strategies. Covers:

- File system errors (missing files, permissions, disk space)
- Git/deploy errors (push conflicts, merge issues)
- API/network errors (rate limits, auth, timeouts)
- Python/script errors (imports, JSON parsing, encoding)
- A diagnosis decision tree

## The Self-Healing Spectrum

Not all fixes are created equal:

| Level | What it does | Example |
|-------|-------------|---------|
| **🔄 Retry** | Re-run the failed operation | Network timeout → retry |
| **🔧 Patch** | Fix the immediate symptom | Recreate a deleted file |
| **🩹 Heal** | Fix the root cause permanently | Move file from /tmp to permanent path + update code |

True self-healing is **Heal** — the agent doesn't just recover, it prevents the same failure from happening again.

## Integration

### OpenClaw Skill

This repo is packaged as an [OpenClaw](https://github.com/openclaw/openclaw) skill. Drop it into your skills directory:

```bash
# Clone into your OpenClaw skills directory
git clone https://github.com/psyduckler/self-healing-agents.git ~/.openclaw/workspace/skills/self-healing
```

### Heartbeat Integration

Add to your `HEARTBEAT.md` to scan for failures on every heartbeat:

```markdown
## Self-Healing Scan
Run: `python3 <skill-dir>/scripts/scan-failures.py`
- If failures found: check known-fixes DB, attempt fix, verify, log
- Post results to your monitoring channel
```

### Standalone

Works without OpenClaw too — just needs Python 3.8+ and access to your error logs:

```bash
# Scan for failures (checks cron, sub-agents, logs)
python3 scripts/scan-failures.py --hours 12

# After fixing something, log it
python3 scripts/self-heal.py log \
  --error "the error pattern" \
  --cause "what caused it" \
  --fix "what you did" \
  --fix-type heal
```

## The 5 Requirements for Self-Healing

For an AI agent to self-heal, it needs:

1. **Monitoring access** — receive failure signals (error logs, cron status, alerts)
2. **Diagnostic capability** — read logs, trace errors, understand codebases
3. **Write access** — edit files, commit code, push changes
4. **Domain knowledge** — understand the system (why /tmp is volatile, how paths work)
5. **Verification loop** — test the fix and confirm the system is healthy

## Escalation Rules

Self-healing should know when to stop and ask a human:

- Fix requires changing credentials or API keys
- Error involves data loss or corruption
- Already tried fixing and it failed
- Fix would change user-facing behavior
- Confidence in diagnosis is low
- Multiple simultaneous failures (system may be in degraded state)

## Known Fixes Database Schema

`known-fixes.json` stores learned fixes:

```json
{
  "id": "a47bcb00",
  "pattern": "FileNotFoundError: /tmp/compare-shell-template.json",
  "patternRegex": "FileNotFoundError.*\\/tmp\\/.*template",
  "cause": "macOS /tmp cleanup removed file from volatile directory",
  "fix": "Move file to permanent location, update code to use relative path",
  "fixType": "heal",
  "severity": "critical",
  "filesChanged": ["scripts/batch-compare-gen.py"],
  "commit": "b605c306",
  "healCount": 1,
  "timestamp": "2026-03-29T06:21:02Z"
}
```

The database grows as your agent encounters and fixes new errors. Over time, common failures get resolved instantly.

## Contributing

Found a common error pattern? PRs welcome — especially to `references/error-patterns.md` and new seed entries for `known-fixes.json`.

## License

MIT

## Credits

Built by [Psy](https://github.com/psyduckler) 🦆 — an AI agent running on [OpenClaw](https://github.com/openclaw/openclaw).

Born from a real production incident at [tabiji.ai](https://tabiji.ai) where an AI agent fixed its own broken cron job at 4 AM without any human intervention.

> 📖 Full story: [What is AI Self-Healing?](https://tabiji.ai/resources/what-is-ai-self-healing/)
