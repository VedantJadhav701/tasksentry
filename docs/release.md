# TaskSentry Release Process

This guide provides step-by-step instructions for maintainers cutting official releases of TaskSentry.

---

## 1. Preparing the v0.1.0 Release

1. **Verify Baseline Quality Gates**:
   ```bash
   conda activate thermo_agent
   python -m pytest -q
   ruff check .
   ruff format --check .
   mypy src/tasksentry
   ```

2. **Run the Benchmark Smoke Test**:
   ```bash
   python -m tasksentry.benchmark.runner --suite offline-v0.1 --output reports/release-smoke.json
   ```

3. **Verify Version Numbers**:
   Ensure `0.1.0` is consistently configured in:
   - `src/tasksentry/version.py`: `__version__ = "0.1.0"`
   - `pyproject.toml`: `version = "0.1.0"`
   - `CHANGELOG.md`: Entry for `## [0.1.0] - 2026-10-26`

4. **Verify Package Build**:
   ```bash
   python -m build
   twine check dist/*
   ```

---

## 2. Tagging the Release in Git

```bash
git add src/tasksentry/version.py pyproject.toml CHANGELOG.md
git commit -m "chore: release v0.1.0"
git tag -a v0.1.0 -m "Release v0.1.0"
```

*Note: Do NOT push the tag until you are explicitly authorized to push to GitHub.*

When authorized:
```bash
git push origin master
git push origin v0.1.0
```

---

## 3. GitHub Release Creation

1. When the `v0.1.0` tag is pushed, GitHub Actions automatically executes `.github/workflows/release.yml`.
2. The workflow verifies quality gates, builds distribution archives (`.tar.gz` and `.whl`), and creates a GitHub Release with attached assets.
3. Review the generated release draft on GitHub, verify the release notes from `CHANGELOG.md`, and publish the release.

---

## 4. PyPI Publication (Manual Approval)

PyPI publishing is not automated on tag push to prevent accidental or unverified releases.

To publish to PyPI:
1. Verify built packages locally:
   ```bash
   twine check dist/*
   ```
2. Upload to PyPI via Twine using an API token:
   ```bash
   twine upload dist/*
   ```
3. Verify installation in a clean environment:
   ```bash
   pip install --no-cache-dir tasksentry==0.1.0
   tasksentry --version
   ```
