# Release Guide for TaskSentry

This document describes the release process and guidelines for TaskSentry maintainers.

## Versioning Principles

TaskSentry strictly adheres to [Semantic Versioning 2.0.0](https://semver.org/):
- **MAJOR** version increments indicate breaking public SDK or contract API changes.
- **MINOR** version increments introduce backwards-compatible features, benchmark tasks, or new model adapters.
- **PATCH** version increments introduce backwards-compatible bug fixes and security patches.

---

## Release Checklist

Before releasing a new version:

1. **Clean Workspace & Environment**:
   Ensure you are on the `master` branch with all changes merged:
   ```bash
   git checkout master
   git pull origin master
   ```

2. **Quality Gates Check**:
   All tests, linters, and type checks must pass cleanly:
   ```bash
   python -m pytest -q
   ruff check .
   ruff format --check .
   mypy src/tasksentry
   ```

3. **Offline Benchmark Smoke Test**:
   ```bash
   python -m tasksentry.benchmark.runner --suite offline-v0.1 --output reports/release-smoke.json
   ```

4. **Verify Version Consistency**:
   - `src/tasksentry/version.py`: Update `__version__ = "X.Y.Z"`.
   - `pyproject.toml`: Ensure version matches.
   - `CHANGELOG.md`: Record changes under `## [X.Y.Z] - YYYY-MM-DD`.

5. **Package Build Test**:
   Verify that sdist and wheel build without warnings:
   ```bash
   python -m build
   twine check dist/*
   ```

---

## Cutting a GitHub Release

1. **Commit and Tag**:
   ```bash
   git add src/tasksentry/version.py CHANGELOG.md
   git commit -m "chore: prepare release vX.Y.Z"
   git tag -a vX.Y.Z -m "Release vX.Y.Z"
   ```

2. **Push Tag to GitHub**:
   ```bash
   git push origin vX.Y.Z
   ```

3. **GitHub Release Workflow**:
   - The `.github/workflows/release.yml` workflow will automatically trigger on the tag.
   - It runs full test and lint matrices on Python 3.11 and 3.12.
   - It builds distribution artifacts (`.tar.gz` and `.whl`) and attaches them directly to the GitHub release draft.

---

## Future PyPI Publication

Publishing to PyPI is intentionally separated from GitHub tag creation to prevent accidental releases:

1. Ensure the GitHub release build succeeded.
2. Verify package artifacts locally or download from the GitHub release:
   ```bash
   twine check dist/*
   ```
3. Upload to PyPI using PyPI API tokens (or Trusted Publishing):
   ```bash
   twine upload dist/*
   ```
4. Verify the published package on PyPI:
   ```bash
   pip install --no-cache-dir tasksentry==X.Y.Z
   python -c "import tasksentry; print(tasksentry.__version__)"
   ```
