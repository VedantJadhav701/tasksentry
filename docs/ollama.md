# Ollama Local Model Integration Guide

TaskSentry includes native support for running local real-model benchmarks and harness tasks via Ollama using its OpenAI-compatible API endpoints.

## Prerequisites

1. **Install Ollama**: Download and install Ollama from [ollama.com](https://ollama.com).
2. **Start the Ollama daemon**:
   ```bash
   ollama serve
   ```
   By default, Ollama listens on `http://127.0.0.1:11434`.

## Configured Models

TaskSentry defines role-specific models in `configs/benchmark_models.yaml`:

### Routine Task Models
- `llama3.2:1b` (Default routine model; fast, low VRAM footprint)
- `gemma2:2b`
- `qwen2.5:3b`

### Reasoning / Planning Models
- `qwen3:4b-instruct-2507-q4_K_M` (Default reasoning model; structured plans and failure recovery)
- `ornith:latest` (Optional)

Pull the models before executing the real-model benchmark track:
```bash
ollama pull llama3.2:1b
ollama pull gemma2:2b
ollama pull qwen2.5:3b
ollama pull qwen3:4b-instruct-2507-q4_K_M
```

## Health & Model Discovery

TaskSentry provides a dedicated CLI command to probe Ollama health, active models, and readiness:

```bash
tasksentry ollama-health
```

Or target a custom Ollama host:
```bash
tasksentry ollama-health --url http://192.168.1.50:11434
```

Python SDK usage:
```python
from tasksentry.models.ollama import OllamaClient, check_ollama_health

health = check_ollama_health("http://127.0.0.1:11434")
print("Ollama available:", health.available)
print("Loaded models:", health.models)

client = OllamaClient(model_name="llama3.2:1b", base_url="http://127.0.0.1:11434")
response = client.generate([{"role": "user", "content": "Hello world"}])
print(response.content, response.latency_seconds)
```

## Running the Ollama Benchmark Track

Run the full real-model benchmark suite against local Ollama models:

```bash
tasksentry benchmark --suite ollama-v0.1 --routine-model llama3.2:1b --reasoning-model qwen3:4b-instruct-2507-q4_K_M
```

Outputs will be saved to:
- `reports/benchmark.json`
- `reports/benchmark.md`
- `reports/tasks/*.json`

## Hardware & Environment Caveats

1. **VRAM Footprint**: Running 3B-4B quantized models locally typically requires at least 4GB to 8GB of GPU VRAM. When VRAM is insufficient, Ollama falls back to CPU inference, causing significant latency.
2. **Deterministic Sampling**: For reproducible benchmark runs, temperature is locked to `0.0` and top-p to `1.0`.
3. **Sequential Execution**: Local models are evaluated sequentially to prevent GPU context swapping and out-of-memory errors.
