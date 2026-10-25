# Contributing to TaskSentry

Thank you for your interest in contributing to TaskSentry! TaskSentry is an open-source, budget-native agent harness and control plane for task-level cost, latency, reliability, and safety control.

## Code of Conduct

All contributors and participants are expected to adhere to our [Code of Conduct](CODE_OF_CONDUCT.md).

## Development Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/VedantJadhav701/tasksentry.git
   cd tasksentry
   ```

2. **Set up a development environment**:
   Python 3.11 or 3.12 is required.
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -e ".[dev,dashboard,ollama,openai,benchmark]"
   ```

3. **Verify the environment**:
   ```bash
   python -m pytest -q
   ruff check .
   ruff format --check .
   mypy src/tasksentry
   ```

## Development Workflow

1. Create a feature branch from `master`:
   ```bash
   git checkout -b feature/my-new-feature
   ```

2. Make changes following these architectural guidelines:
   - **Canonical state purity**: Canonical task states must only contain durable facts, milestones, and goals. Never leak wall-clock timestamps, trace IDs, ephemeral logs, or budget counters into canonical state hashes.
   - **Mathematical invariants**: Any adjustments to APG, information gain, or the stop policy must preserve existing unit test invariants.
   - **Process isolation**: Heavy or untrusted tool execution must remain isolated.
   - **Documentation**: Update docstrings and relevant documentation under `docs/` for new features or public API changes.

3. Run quality gates before submitting a pull request:
   ```bash
   ruff check .
   ruff format .
   mypy src/tasksentry
   python -m pytest -q
   ```

4. Submit a Pull Request targeting the `master` branch with a clear description of the problem solved and test evidence.

## Reporting Issues

- Bug reports: Use the GitHub issue tracker with our [Bug Report Template](.github/ISSUE_TEMPLATE/bug_report.yml).
- Feature requests: Propose design ideas using the [Feature Request Template](.github/ISSUE_TEMPLATE/feature_request.yml).
- Security vulnerabilities: Please follow our [Security Policy](SECURITY.md) and do not file public issues for security vulnerabilities.
