# TaskSentry Configuration Reference

TaskSentry follows a clean configuration precedence hierarchy:
1. **Explicit Python kwargs** passed at runtime.
2. **Environment variables** (`TASKSENTRY_*`).
3. **Configuration file** (`tasksentry.yaml` or `tasksentry.yml`).
4. **Built-in sensible defaults**.

API keys are never stored in repository configuration files or hardcoded.

---

## 1. Environment Variables

| Variable | Description | Default |
|---|---|---|
| `TASKSENTRY_DATABASE_PATH` | Path to the SQLite task receipt storage file. | `tasksentry.db` |
| `TASKSENTRY_OLLAMA_BASE_URL` | Base URL for the local Ollama API. | `http://127.0.0.1:11434` |
| `TASKSENTRY_LOG_LEVEL` | Minimum logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). | `INFO` |
| `TASKSENTRY_PRICING_FILE` | Optional path to custom YAML pricing table. | Built-in pricing catalog |
| `OPENAI_API_KEY` | Optional API key for OpenAI-compatible endpoints. | None |
| `OPENAI_BASE_URL` | Base URL for OpenAI-compatible client. | `https://api.openai.com/v1` |

---

## 2. Configuration File (`tasksentry.yaml`)

```yaml
# tasksentry.yaml
storage:
  database_path: "data/tasksentry.db"

budget:
  default_max_tool_calls: 10
  default_max_tokens: 8000
  default_max_cost_usd: 0.10
  default_max_wall_time_seconds: 60.0

governor:
  default_block_threshold: 2
  escalate_after_blocks: 3
  repetition_penalty: 2.0

ollama:
  base_url: "http://127.0.0.1:11434"
  default_routine_model: "llama3.2:1b"
  default_reasoning_model: "qwen3:4b-instruct-2507-q4_K_M"
```

---

## 3. Pricing Catalog (`src/tasksentry/budget/pricing.py`)

TaskSentry includes built-in token pricing for common models:

| Model | Input Price ($ / 1M tokens) | Output Price ($ / 1M tokens) |
|---|---|---|
| `gpt-4o` | $2.50 | $10.00 |
| `gpt-4o-mini` | $0.15 | $0.60 |
| `claude-3-5-sonnet` | $3.00 | $15.00 |
| `llama-3.2-1b` | $0.00 | $0.00 (Local inference) |
| `qwen2.5-3b` | $0.00 | $0.00 (Local inference) |

Custom pricing can be provided programmatically:
```python
from tasksentry.budget.pricing import PricingCatalog, ModelPricing

catalog = PricingCatalog()
catalog.register(ModelPricing(model_name="custom-model", input_per_1m=1.0, output_per_1m=3.0))
cost = catalog.calculate_cost("custom-model", input_tokens=1000, output_tokens=200)
```

---

## 4. Policy Configuration (`agents/policies.yaml`)

Defines execution guardrails and safety thresholds:

```yaml
policies:
  strict-safety:
    max_risk: 0.5
    require_approval_for_writes: true
    allowed_tools:
      - "read_file"
      - "run_tests"
      - "search_workspace"

  unconstrained:
    max_risk: 1.0
    require_approval_for_writes: false
```

---

## 5. Model Registry (`src/tasksentry/models/registry.py`)

Models can be declared in YAML or registered in Python:

```python
from tasksentry.models.registry import ModelRegistry
from tasksentry.models.fake_model import FakeModel

registry = ModelRegistry()
registry.register(
    "dev-mock", FakeModel(canned_responses=[{"role": "assistant", "content": "Done"}])
)
model = registry.get("dev-mock")
```
