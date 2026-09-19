---
name: checks
description: Runs agent-runtime's full verification suite — pytest, ruff, and mypy — against the project's Windows venv. Use before committing, after any code change, or when the user asks to check/verify/lint/typecheck/run tests.
allowed-tools: Bash(./venv/Scripts/python.exe -m pytest*) Bash(./venv/Scripts/python.exe -m ruff*) Bash(./venv/Scripts/python.exe -m mypy*)
---

## Verify the codebase

Runs the same three checks CI/reviewers expect to be clean, in order,
stopping to report the first failure with its full output rather than
suppressing it.

### 1. Tests

```bash
./venv/Scripts/python.exe -m pytest -q
```

### 2. Lint

```bash
./venv/Scripts/python.exe -m ruff check .
```

### 3. Types

```bash
./venv/Scripts/python.exe -m mypy
```

### Reporting

- If everything passes, say so in one line — don't paste clean output.
- If something fails, show the relevant failing output (not the whole
  log) and either fix it or explain what's blocking a fix.
- Never mark a step "passed" without actually having run it this turn.
