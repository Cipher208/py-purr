# Contributing to PURR

Thank you for your interest in contributing to PURR!

## Development Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/Cipher208/PURR.git
   cd PURR
   ```

2. Install dependencies with `uv` or `pip`:
   ```bash
   pip install -e ".[dev]"
   ```

3. Run the test suite:
   ```bash
   pytest -v
   ```

## Guidelines

- Keep changes minimal and focused.
- Ensure all tests pass (`pytest -v`) before submitting a PR.
- Add tests for any new features or bug fixes.
- Follow existing code style and typing conventions.
