---
name: ruff-check
description: Run Ruff lint checks for this repository, ensuring the local virtual environment is ready first. Use when asked to lint code or validate style violations.
---

Use this skill when the user asks to run Ruff lint checks (`ruff check`) or fix/check code quality issues caught by Ruff.

## Steps

1. Ensure the project virtual environment exists:

   ```bash
   test -x .venv/bin/python || python3 -m venv .venv --upgrade-deps
   ```

2. Ensure dev dependencies are installed (includes Ruff):

   ```bash
   .venv/bin/python -m pip install -r src/requirements/local.txt
   ```

3. Run Ruff check from `src/`:

   ```bash
   cd src && ../.venv/bin/ruff check .
   ```

## Notes

- Do not silently auto-fix unless the user asks for fixes.
- Report full Ruff output summary (files/errors) back to the user.
- If dependency resolution warnings appear, surface them in your report.
