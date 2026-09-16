---
name: ruff-format
description: Run Ruff formatter for this repository, ensuring the local virtual environment is ready first. Use when asked to format Python code.
---

Use this skill when the user asks to format code with Ruff (`ruff format`).

## Steps

1. Ensure the project virtual environment exists:

   ```bash
   test -x .venv/bin/python || python3 -m venv .venv --upgrade-deps
   ```

2. Ensure dev dependencies are installed (includes Ruff):

   ```bash
   .venv/bin/python -m pip install -r src/requirements/local.txt
   ```

3. Run Ruff format from `src/`:

   ```bash
   cd src && ../.venv/bin/ruff format .
   ```

## Notes

- Formatting changes files in-place; mention which files changed.
- Run `ruff check` afterward if the user wants validation after formatting.
