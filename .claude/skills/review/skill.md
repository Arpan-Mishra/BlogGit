---
name: review
description: Run code-reviewer and python-reviewer agents on current changes. Checks quality, security, Pythonic idioms, type hints, and PEP 8 compliance.
---

Run a two-pass code review on all current changes using the following agents in sequence:

## Pass 1: code-reviewer agent

Use the `code-reviewer` agent to review the current changes. It will:
- Run `git diff --staged` and `git diff` to find all changes
- Check for security issues (injection, hardcoded secrets, path traversal)
- Check code quality (function size, nesting, error handling, immutability)
- Check Python backend patterns (FastAPI, Pydantic validation, N+1 queries)
- Produce severity-rated findings (CRITICAL / HIGH / MEDIUM / LOW)

## Pass 2: python-reviewer agent

Use the `python-reviewer` agent to review the same changes. It will:
- Run `ruff check .`, `mypy .`, `black --check .`, `bandit -r .`
- Check PEP 8 compliance, type hints, Pythonic idioms
- Flag anti-patterns (bare except, mutable defaults, print() in production, == None)
- Check framework-specific issues (FastAPI async, Pydantic models)

## Output

After both passes, produce a combined summary:

```
## Review Summary

### code-reviewer findings
| Severity | Count | Status |
|----------|-------|--------|
| CRITICAL | 0     | pass   |
| HIGH     | ?     | ...    |
| MEDIUM   | ?     | ...    |
| LOW      | ?     | ...    |

### python-reviewer findings
| Severity | Count | Status |
|----------|-------|--------|
| CRITICAL | 0     | pass   |
| HIGH     | ?     | ...    |
| MEDIUM   | ?     | ...    |
| LOW      | ?     | ...    |

### Verdict
APPROVE / WARN / BLOCK — with reason
```

**Block** if either agent finds CRITICAL issues. **Warn** if either finds HIGH issues. **Approve** only if both pass clean.
