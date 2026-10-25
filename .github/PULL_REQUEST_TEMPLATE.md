## Description
Briefly describe the purpose of this PR and what problem it solves.

## Type of Change
- [ ] Bug fix (non-breaking change fixing an issue)
- [ ] New feature (non-breaking change adding functionality)
- [ ] Breaking change (fix or feature causing existing functionality to change)
- [ ] Documentation update
- [ ] Benchmark task or metric addition

## Checklist
- [ ] My code follows the code style and formatting of this project (`ruff check .`, `ruff format .`).
- [ ] My changes pass static type analysis (`mypy src/tasksentry`).
- [ ] I have added tests that prove my fix is effective or that my feature works.
- [ ] All existing and new tests pass locally (`pytest -q`).
- [ ] I have updated relevant documentation under `docs/` if applicable.
- [ ] Canonical task state hashing invariants are strictly maintained (no volatile timestamps or counters in state hashes).
