# Contributing to Room OS

Thanks for helping improve Room OS. Small, focused changes with tests are the
easiest to review.

## Before opening a change

1. Search existing issues and discussions.
2. Open an issue before large architecture or behavior changes.
3. Never attach face images, embeddings, API keys, logs with personal data or
   unredacted camera captures.

## Local workflow

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Create a branch, keep commits scoped and open a pull request against `main`.

## Architecture rules

- Communicate across modules through the `EventBus`.
- Keep capture, processing, visualization and actions separate.
- Add actions through `BaseAction` and the registry; do not special-case them in
  the action engine.
- Keep Windows-specific behavior under `platforms/windows`.
- Validate untrusted inputs at their boundary.
- Read credentials from environment variables only.
- Use parameterized queries if a database is introduced.
- Add or update tests for every behavior change.

## Pull requests

Explain what changed, why, how it was tested and any hardware limitations. Avoid
format-only rewrites mixed with functional changes.
