# Contributing to PURR

Thank you for your interest in contributing to PURR!

## Development Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/Cipher208/py-purr.git
   cd py-purr
   ```

2. Install dependencies with `uv` (recommended) or `pip`:
   ```bash
   uv sync --extra dev
   # or: pip install -e ".[dev]"
   ```

3. Run the test suite:
   ```bash
   uv run pytest -v
   ```

## Guidelines

- Keep changes minimal and focused.
- Add tests for any new features or bug fixes.
- Follow existing code style and typing conventions.

### Before you open a pull request

All three must pass — they are exactly what CI runs:

```bash
uv run ruff check purr tests
uv run ruff format --check purr tests
uv run pytest --cov=purr --cov-fail-under=85
```

The coverage gate is real: a pull request that adds a module without tests
turns it red. If you are adding a feature, the test usually belongs next to the
existing contract tests in `tests/`.

## Reporting security issues

Do not open a public issue — see [SECURITY.md](SECURITY.md).

## Code of Conduct

By participating you agree to the
[Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md).
