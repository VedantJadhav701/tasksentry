# TaskSentry CLI Reference

TaskSentry includes a command-line interface (`tasksentry`) for executing tasks, managing storage, running benchmarks, checking local Ollama health, and hosting the dashboard.

---

## Global Options

```bash
tasksentry [--version] [-v | --verbose] <command> [options]
```

Exit codes:
- `0`: Success / normal exit.
- `1`: Execution failure, test failure, or configuration error.
- `2`: Command line argument syntax error.

---

## Commands

### `tasksentry demo`
Runs the built-in offline coding agent demonstration.
```bash
tasksentry demo
```
**Exit Code**: `0` on success.

---

### `tasksentry run --task <path>`
Executes an agent task contract defined in YAML or JSON format.
```bash
tasksentry run --task examples/coding_task.yaml
```
Options:
- `--task`: Path to task contract definition file.
- `--db`: SQLite database file path (defaults to `tasksentry.db`).

---

### `tasksentry tasks`
Lists all executed tasks stored in the SQLite database.
```bash
tasksentry tasks [--limit 20]
```

---

### `tasksentry task <task-id>`
Inspects the detailed status, metadata, and results of a specific task.
```bash
tasksentry task task-offline-demo
```

---

### `tasksentry receipt <task-id>`
Outputs the complete JSON execution receipt for a task.
```bash
tasksentry receipt task-offline-demo
```

---

### `tasksentry benchmark`
Executes the TaskSentryBench evaluation suite.
```bash
# Run offline regression suite
tasksentry benchmark --suite offline-v0.1 --output reports/offline-benchmark.json

# Run local Ollama benchmark suite
tasksentry benchmark --suite ollama-v0.1 --routine-model llama3.2:1b --reasoning-model qwen3:4b-instruct-2507-q4_K_M
```
Options:
- `--suite`: Suite identifier (`offline-v0.1` or `ollama-v0.1`).
- `--routine-model`: Ollama model name for routine tasks.
- `--reasoning-model`: Ollama model name for reasoning tasks.
- `--seed`: Deterministic pseudo-random seed (default: `42`).
- `--output`: Path to write the JSON and Markdown report.

---

### `tasksentry ollama-health`
Probes local Ollama connectivity, response latency, and available models.
```bash
tasksentry ollama-health [--url http://127.0.0.1:11434]
```

---

### `tasksentry dashboard`
Starts the local-only developer dashboard server.
```bash
tasksentry dashboard [--host 127.0.0.1] [--port 8321]
```
Note: strictly binds to `127.0.0.1` by default for local security.

---

### `tasksentry benchmark-report`
Renders a structured Markdown report from an existing benchmark JSON file.
```bash
tasksentry benchmark-report --input reports/benchmark.json --output reports/benchmark.md
```
