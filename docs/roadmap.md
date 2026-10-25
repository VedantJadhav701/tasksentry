# TaskSentry Project Roadmap

This roadmap outlines planned features, architectural evolutions, and research initiatives for TaskSentry post-v0.1.0.

---

## Phase 6 (Completed: v0.1.0)
- [x] Canonical task state hashing and progress tracking.
- [x] Multi-dimensional budget meter and pricing catalog.
- [x] Tool registry, schema validation, repetition governor, and sandbox.
- [x] Verification gates and automated recovery engine.
- [x] CASE agent runtime loop.
- [x] Public Python SDK and persistent SQLite receipt storage.
- [x] TaskSentryBench v0.1 (offline regression track and local Ollama track).
- [x] Local developer dashboard (`http://127.0.0.1:8321`).
- [x] Packaging, CI workflows, and release documentation.

---

## Near-Term (v0.2.0 - v0.3.0)

### 1. Framework Adapters & First-Class Integrations
- **LangGraph Adapter**: Drop-in node wrapper for governing LangGraph StateGraphs.
- **CrewAI / AutoGen Hooks**: Interceptor middleware for multi-agent workflows.
- **OpenAI Agents SDK Support**: Direct wrapper around client-level tool dispatches.

### 2. Enhanced Sandboxing
- **Container Sandbox**: Docker and Podman container driver for untrusted code execution.
- **MicroVM Integration**: Optional Firecracker microVM support for ultra-fast, isolated tool execution.

### 3. Empirical Benchmark Expansion
- **Live Ollama Leaderboard**: Continuous benchmark matrix tracking open-weights models (`qwen2.5`, `llama3.2`, `gemma2`) across hardware architectures.
- **Automated Regression Tracking**: Automated PR benchmark comparisons against the offline regression suite.

---

## Long-Term (v0.4.0+)

### 1. Hosted Control Plane & Multi-Tenant Dashboard
- Centralized team dashboard with role-based access control (RBAC), team budgets, and audit receipts.
- Real-time SSE / WebSocket streaming of agent execution steps.

### 2. Learned Policy & Dynamic Budget Allocation
- Adaptive APG weighting based on task family characteristics.
- Dynamic token allocation between reasoning/planning models and routine execution models.

### 3. Context Compaction & Checkpoint Branching
- Semantic state summarization during long-horizon workflows.
- Rollback and branch execution from verified milestone checkpoints.
