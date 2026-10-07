## What changed

<!-- One paragraph: what was wrong or missing before, and what it does now. -->

## Why

<!-- The reasoning. If the diff is obvious, this can be short — but say why
     this approach rather than another. -->

## How it was checked

- [ ] `uv run ruff check purr tests` passes
- [ ] `uv run ruff format --check purr tests` passes
- [ ] `uv run pytest --cov=purr --cov-fail-under=85` passes
- [ ] New behaviour has a test

## Notes for the reviewer

<!-- Anything you were unsure about or want a second opinion on. Saying "I was
     not sure about this part" is useful, not weak. -->

---

- [ ] One concern per pull request
- [ ] Commit messages say what changed and why
