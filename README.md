# Self-Healing

**Autonomous error detection, diagnosis, and repair for AI agents.**

![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)
![License MIT](https://img.shields.io/badge/license-MIT-green.svg)

---

## Why This Exists

AI agents run cron jobs, deploy code, manage infrastructure, post to social media, sync APIs. All of it breaks eventually — at 4 AM, on a weekend, during a demo.

The current playbook: detect failure → alert human → wait. Sometimes for hours. Sometimes the fix is "restart the service" or "delete a lock file." A human shouldn't need to wake up for that.

Self-healing turns agents from **"detect and alert"** into **"detect, diagnose, fix, verify, and learn."**

It's not retry logic. It's root-cause analysis, risk-scored fix application, cascading failure detection, and a known-fixes database that gets smarter over time. When the same error happens twice, the agent already knows what to do.

---

## Architecture

```
Failure Signal → Scanner → Triage → Known Fix?
                                    ├─ Yes → Apply → Verify → Done
                                    └─ No  → Diagnose → Fix → Verify → Log Fix
                                                                         ↓
                                                              Known Fixes DB (learns)
```

The **Scanner** pulls failures from pluggable sources (cron jobs, log files, JSONL streams, custom integrations). **Triage** checks each failure against the known-fixes database using a multi-signal matching engine. If a match is found with high confidence and acceptable risk, the fix is applied automatically. If not, the agent diagnoses the root cause, applies a fix, verifies it, and logs the fix for next time.

Every fix makes the system smarter.

---

## Quick Start

### Install

```bash
# Clone or copy the skill
cd ~/.openclaw/workspace/skills/self-healing

# Install dependencies (just PyYAML — everything else is stdlib)
pip install -r requirements.txt

# Or install as a package
pip install -e .
```

### Scan for failures

```bash
# Default: scans OpenClaw cron jobs + sub-agents + /tmp logs
python3 scripts/scan-failures.py

# JSON output for programmatic use
python3 scripts/scan-failures.py --json

# Scan last 24 hours
python3 scripts/scan-failures.py --hours 24

# Scan specific source only
python3 scripts/scan-failures.py --source openclaw
python3 scripts/scan-failures.py --source logfile

# Use a config file
python3 scripts/scan-failures.py --config self-healing.yaml
```

### Check for a known fix

```bash
python3 scripts/self-heal.py check "FileNotFoundError: /tmp/template.json"
```

Returns:
```json
{
  "match": true,
  "confidence": 0.95,
  "autoApply": true,
  "knownFix": {
    "cause": "macOS /tmp cleanup removed file from volatile directory",
    "fix": "Move file to permanent location, update code to use relative path",
    "fixType": "heal"
  },
  "risk": {
    "riskScore": 0.2,
    "decision": "auto_apply"
  }
}
```

### Log a new fix

```bash
python3 scripts/self-heal.py log \
  --error "FileNotFoundError: /tmp/template.json" \
  --cause "macOS /tmp cleanup" \
  --fix "Moved to permanent path" \
  --fix-type heal \
  --files-changed "scripts/batch.py"
```

### With OpenClaw

If you're running inside OpenClaw, self-healing works as a skill. The agent reads `SKILL.md` and follows the detect → triage → diagnose → fix → verify → log workflow automatically. Add it to your heartbeat for proactive scanning.

---

## Source Plugins

Self-healing uses a plugin architecture for failure sources. Each source scans a different system for errors and returns a consistent failure schema.

### Built-in Sources

| Source | What it scans | Config |
|--------|--------------|--------|
| `openclaw` | Cron jobs + sub-agent runs | None needed (auto-detects) |
| `logfile` | Log files matching glob patterns | `paths`, `error_patterns`, `severity_map` |
| `jsonl` | JSONL files with structured error records | `path`, `error_field`, `timestamp_field`, `severity_field` |

### Failure Schema

Every source returns dicts with this shape:

```python
{
    "source": "logfile",          # Source identifier
    "id": "/var/log/app.log",     # Unique failure ID
    "name": "app.log",            # Human-readable label
    "error": "Connection refused", # Error message (truncated to 500 chars)
    "timestamp": "2026-03-29T...", # ISO 8601
    "severity": "warning"         # "critical", "warning", or "info"
}
```

### Writing a Custom Source

```python
from sources.base import FailureSource

class SlackAlertSource(FailureSource):
    name = "slack_alerts"

    def __init__(self, channel: str = "#alerts"):
        self.channel = channel

    def scan(self, hours: int = 6) -> list[dict]:
        # Your logic: poll Slack, filter by time, return failures
        return [
            {
                "source": "slack",
                "id": "msg-123",
                "name": "Production alert",
                "error": "CPU usage at 98% on worker-3",
                "timestamp": "2026-03-29T10:00:00Z",
                "severity": "critical",
            }
        ]

    @classmethod
    def from_config(cls, config: dict) -> "SlackAlertSource":
        return cls(channel=config.get("channel", "#alerts"))
```

Register it:

```python
from sources import register_source
register_source("slack_alerts", SlackAlertSource)
```

---

## Known-Fixes Database

Fixes are stored in `known-fixes.json` in your workspace root. Each entry:

```json
{
  "id": "a1b2c3d4",
  "pattern": "FileNotFoundError: /tmp/compare-shell-template.json",
  "patternRegex": "FileNotFoundError.*\\/tmp\\/.*template",
  "errorClasses": ["file_not_found"],
  "cause": "macOS /tmp cleanup removed file from volatile directory",
  "fix": "Move file to permanent location, update code to use relative path",
  "fixType": "heal",
  "severity": "critical",
  "filesChanged": ["scripts/batch.py", "scripts/template.json"],
  "commit": "b605c306",
  "timestamp": "2026-03-29T06:21:02Z",
  "source": "cron",
  "healCount": 3
}
```

`healCount` increments every time the same fix is applied. Patterns that fire often are battle-tested.

### Smart Matching Engine

When checking an error against known fixes, the engine uses **six independent signals**:

| Signal | Weight | What it measures |
|--------|--------|-----------------|
| **Regex match** | 0.90 | Pattern author wrote a specific regex |
| **Exact substring** | 0.95 | Pattern is literally contained in the error |
| **Token overlap** | ≤0.80 | Shared meaningful words (minus stop words) |
| **Error class** | 0.75 | Same error category (e.g., both are `file_not_found`) |
| **Path similarity** | ≤0.70 | Similar file paths in both errors |
| **N-gram overlap** | ≤0.85 | Character-level structural similarity |

The final score takes the strongest signal, with a bonus if 3+ signals agree. A score ≥ 0.8 with acceptable risk → auto-apply.

### Error Classes

Errors are classified into categories for cross-matching:

`file_not_found`, `permission`, `connection`, `timeout`, `rate_limit`, `auth`, `json_parse`, `import`, `git_push`, `disk`, `memory`

Two errors in the same class (e.g., `FileNotFoundError` and `No such file or directory`) get a baseline match even if the text is different.

---

## Risk Scoring

Every fix is scored for risk before application. The engine checks:

1. **System profile** — What kind of system is affected?
2. **Fix type** — `retry` (low risk), `patch` (moderate), `heal` (higher — changes code)
3. **Reversibility** — Can this be undone?
4. **User-facing impact** — Will users see the change?
5. **Data loss potential** — Could data be destroyed?

### Built-in Risk Profiles

| Profile | Base Risk | Reversible | User-Facing | Data Loss |
|---------|-----------|------------|-------------|-----------|
| `static_site` | 0.2 | ✅ | ✅ | ❌ |
| `cron_job` | 0.3 | ✅ | ❌ | ❌ |
| `social_media` | 0.5 | ❌ | ✅ | ❌ |
| `deployment` | 0.5 | ✅ | ✅ | ❌ |
| `email` | 0.7 | ❌ | ✅ | ❌ |
| `config` | 0.8 | ✅ | ❌ | ❌ |
| `payment` | 0.9 | ❌ | ✅ | ✅ |
| `database` | 0.9 | ❌ | ✅ | ✅ |

### Decisions

| Risk Score | Decision | Meaning |
|-----------|----------|---------|
| ≤ 0.3 | `auto_apply` | Safe to apply without human review |
| 0.3 – 0.6 | `apply_with_caution` | Apply but verify carefully |
| 0.6 – 0.8 | `human_review` | Recommend human review first |
| > 0.8 | `escalate` | Do not auto-apply. Alert a human. |

```bash
# Score a fix
python3 scripts/self-heal.py risk "Fix email notification template"
```

```json
{
  "riskScore": 0.7,
  "decision": "human_review",
  "profile": "email",
  "reasoning": [
    "Matched profile: email (Outbound emails to users/customers)",
    "⚠️ Not easily reversible",
    "User-facing system",
    "Fix type 'heal': increases risk by 10%"
  ]
}
```

---

## Cascading Failure Detection

When multiple things break at once, they usually share a root cause. Self-healing detects cascades using three strategies:

### 1. Signature Matching

Known root causes that produce multiple failures:

| Cascade | Patterns | Severity |
|---------|----------|----------|
| `gateway_down` | `ECONNREFUSED`, `RPC fail`, `gateway` | 🔴 Critical |
| `disk_full` | `No space left`, `ENOSPC` | 🔴 Critical |
| `network_down` | `ENETUNREACH`, `DNS fail` | 🔴 Critical |
| `git_locked` | `.git/index.lock`, `Another git process` | 🟡 Warning |
| `auth_expired` | `401`, `token expired`, `Unauthorized` | 🟡 Warning |
| `api_outage` | `503`, `502`, `500 Internal Server` | 🟡 Warning |
| `tmp_cleanup` | `FileNotFoundError: /tmp/` | 🟡 Warning |

### 2. Time Proximity

Failures within a 5-minute window are grouped — if 3 cron jobs all fail at 3:12 AM, that's probably one problem, not three.

### 3. Source Correlation

If 3+ cron jobs are in error state simultaneously, the system flags it as systemic rather than individual failures.

When a cascade is detected, the recommendation is always: **fix the root cause first.** Individual failures will resolve once the shared dependency is restored.

---

## Configuration

Create `self-healing.yaml` (or `.json`) in the skill directory:

```yaml
sources:
  openclaw:
    enabled: true
  logfile:
    enabled: true
    paths:
      - /tmp/*.log
      - /var/log/myapp/*.log
    error_patterns:
      - "ERROR|FATAL|CRITICAL"
      - "Traceback"
    severity_map:
      FATAL: critical
      ERROR: warning
  jsonl:
    enabled: true
    path: /tmp/agent-errors.jsonl
    error_field: message
    timestamp_field: ts
    severity_field: level

cascades:
  my_custom_cascade:
    patterns:
      - "my-service.*down"
      - "my-service.*unreachable"
    description: "My service is down"
    severity: critical

risk_profiles:
  my_system:
    description: "My critical system"
    keywords: ["my-system", "critical-db"]
    baseRisk: 0.9
    reversible: false
    userFacing: true
    dataLoss: true
```

Without a config file, the scanner defaults to OpenClaw sources + `/tmp/*.log` scanning.

---

## Stats & Metrics

```bash
python3 scripts/self-heal.py stats
```

```json
{
  "totalPatterns": 12,
  "totalHeals": 47,
  "byType": {
    "heal": 7,
    "patch": 3,
    "retry": 2
  },
  "bySource": {
    "cron": 8,
    "manual": 4
  },
  "byErrorClass": {
    "file_not_found": 5,
    "connection": 3,
    "git_push": 2,
    "auth": 2
  },
  "mostCommon": "FileNotFoundError: /tmp/compare-shell-template.json"
}
```

Other commands:

```bash
# List all known fixes
python3 scripts/self-heal.py list

# Check risk of a system change
python3 scripts/self-heal.py risk "deploy new config to production"
```

---

## Project Structure

```
self-healing/
├── SKILL.md                 # Agent-facing instructions (OpenClaw skill)
├── README.md                # This file
├── LICENSE                  # MIT
├── pyproject.toml           # Package config
├── requirements.txt         # pyyaml
├── scripts/
│   ├── scan-failures.py     # Multi-source failure scanner
│   └── self-heal.py         # Known-fixes DB manager + risk engine
├── sources/
│   ├── __init__.py          # Plugin registry
│   ├── base.py              # Abstract base class
│   ├── openclaw.py          # OpenClaw cron + sub-agent source
│   ├── logfile.py           # Log file glob scanner
│   └── jsonl.py             # JSONL structured error source
├── references/
│   └── error-patterns.md    # Common error patterns reference
└── tests/
    ├── test_matching.py     # Smart match engine tests
    ├── test_risk.py         # Risk scoring tests
    ├── test_sources.py      # Source plugin tests
    └── test_cascades.py     # Cascade detection tests
```

---

## Contributing

1. Fork / clone
2. `pip install -e ".[dev]"`
3. `python3 -m pytest tests/`
4. Make changes, add tests
5. Open a PR

### Adding a Source Plugin

1. Create `sources/my_source.py` with a class extending `FailureSource`
2. Implement `scan()` and `from_config()`
3. Register it in `sources/__init__.py`
4. Add tests in `tests/test_sources.py`

### Adding a Cascade Signature

Add to `CASCADE_SIGNATURES` in `scan-failures.py`, or use the config file for user-defined cascades.

---

## License

MIT. See [LICENSE](LICENSE).
