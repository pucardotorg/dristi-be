---
name: check-and-test
description: Run Django system checks and pytest for this repository, ensuring the local virtual environment and dependencies are ready first.
---

Use this skill when the user asks to run both Django checks and tests together.

## Steps

1. Ensure the project virtual environment exists:

   ```bash
   test -x .venv/bin/python || python3 -m venv .venv --upgrade-deps
   ```

2. Ensure dev dependencies are installed:

   ```bash
   .venv/bin/python -m pip install -r src/requirements/local.txt
   ```

3. Run Django system checks (test settings by default):

   ```bash
   cd src && DJANGO_SETTINGS_MODULE=config.settings.test ../.venv/bin/python manage.py check
   ```

4. Run pytest with test settings:

   ```bash
   cd src && DJANGO_SETTINGS_MODULE=config.settings.test ../.venv/bin/pytest
   ```

## Notes

- Report Django check and pytest results separately.
- If either command fails, include the failing command and key error output.
- If the user needs another environment validated, allow overriding `DJANGO_SETTINGS_MODULE`.
