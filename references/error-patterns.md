# Common Error Patterns & Root Causes

Quick reference for diagnosing common failures in OpenClaw agent operations.

## File System Errors

| Pattern | Likely Cause | Fix Type |
|---------|-------------|----------|
| `FileNotFoundError: /tmp/...` | macOS /tmp cleanup purged file | **Heal** — move to permanent location |
| `Permission denied` | File perms too restrictive, or running as wrong user | **Patch** — chmod/chown |
| `No space left on device` | Disk full (often /tmp or build artifacts) | **Patch** — clean old files |
| `IsADirectoryError` | Code expects file but path is directory | **Heal** — fix path logic |

## Git / Deploy Errors

| Pattern | Likely Cause | Fix Type |
|---------|-------------|----------|
| `git push rejected: remote ahead` | Concurrent pushes from multiple agents | **Heal** — add `git pull --rebase` before push |
| `merge conflict` | Overlapping file changes | **Escalate** — needs human judgment |
| `fatal: not a git repository` | Wrong working directory | **Patch** — cd to correct repo |
| `Cloudflare 404 after push` | Deploy not propagated yet, or path issue | **Retry** — wait 30s, check again |

## API / Network Errors

| Pattern | Likely Cause | Fix Type |
|---------|-------------|----------|
| `429 Too Many Requests` | Rate limited | **Retry** — back off, retry after delay |
| `401 Unauthorized` | Token expired or wrong key | **Escalate** — may need new credentials |
| `Connection refused` | Service not running | **Patch** — start the service |
| `timeout` (generic) | Slow API or network issue | **Retry** — increase timeout, retry |
| `SSL certificate verify failed` | Clock skew or expired cert | **Escalate** — check system time |

## Python / Script Errors

| Pattern | Likely Cause | Fix Type |
|---------|-------------|----------|
| `ModuleNotFoundError` | Missing pip package | **Patch** — pip install |
| `JSONDecodeError` | Malformed JSON (often from LLM output) | **Retry** — re-run with stricter prompt |
| `KeyError` in data processing | Unexpected data shape | **Heal** — add defensive .get() |
| `UnicodeDecodeError` | Binary file read as text | **Heal** — add encoding param |

## OpenClaw Specific

| Pattern | Likely Cause | Fix Type |
|---------|-------------|----------|
| `cron job: error status` | Task failed in last run | Check cron logs, diagnose per above |
| `sub-agent timeout` | Task too large or agent stuck | **Heal** — split task, add timeout |
| `Message failed` | Missing `to` or wrong `channel` in delivery | **Heal** — fix delivery config |
| `Gateway not responding` | Config change broke gateway | **Escalate** — careful config review |

## Diagnosis Decision Tree

```
Error occurred
├── Is it a known pattern? → Check known-fixes.json → Apply fix
├── Is it transient? (timeout, 429, network) → Retry with backoff
├── Is it environmental? (file missing, perms, disk) → Fix environment
├── Is it a code bug? (KeyError, logic error) → Fix code, commit
├── Is it external? (API changed, service down) → Adapt or wait
└── Unsure? → Escalate to human
```

## Severity Classification

- **Critical**: Data loss risk, user-facing breakage, deploy failure, payment/order issues
- **Warning**: Cron failure, sub-agent crash, non-blocking errors
- **Info**: Transient errors that self-resolved, informational warnings
