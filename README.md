# TaskSentry

**TaskSentry is an open-source, budget-native agent harness and control plane for task-level
cost, latency, reliability, and safety control.**

> Agent frameworks help you build agents. TaskSentry helps you run them safely, affordably,
> and predictably in production.

TaskSentry does not replace LangGraph, CrewAI, AutoGen, or the OpenAI Agents SDK. It is a
control layer for running agents.

## Status: Phase 1 (math and state core)

This snapshot contains only the foundation that every later phase builds on:

| Module | What it provides |
|---|---|
| `tasksentry.core.state` | Canonical task state `s_t = (g, M_t, K_t, W_t)`, volatile-free progress hash, action fingerprint that includes the state hash |
| `tasksentry.core.contract` | Task contract with verifier-backed success criteria and milestones, budget limits, safety rules, hypothesis set |
| `tasksentry.math.similarity` | Volatile-field normalization, exact-hash + Jaccard similarity, optional embedding backend, evidence novelty |
| `tasksentry.math.information_gain` | `HypothesisBeliefTracker` (Bayes + entropy), labelled **proxy** fallback |
| `tasksentry.math.progress` | Agent Progress Gain, rolling window, EMA, the canonical stop policy, duplicate-block bookkeeping |

The harness, tool governor, budget wrapper, benchmark, and dashboard arrive in later phases.

## Install and test

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -q
ruff check .
mypy src/tasksentry
```

## The math in one page

```
APG_t =  1.0 * StateChange  + 1.0 * MilestoneProgress + 0.8 * EstimatedInformationGain
       + 0.8 * EvidenceNovelty - 2.0 * EffectiveRepetitionPenalty - 0.1 * NormalizedCost
WindowGain_t = sum of the last 5 APG values        EMA_t = 0.3 * APG_t + 0.7 * EMA_{t-1}
```

All weights are configurable **heuristic defaults**, not derived constants. The stop policy:
fewer than 5 steps continue (cold start); `WindowGain > 0` continue; `-1 < WindowGain <= 0` warn
and require a new approach; `-2 < WindowGain <= -1` force a replan; `WindowGain <= -2` stop or
escalate.

`StateChange` hashes only the canonical task state (never budget, history, timestamps, or trace
IDs). A repeated action is exempt from the repetition penalty after a transient failure, an
error, changed arguments, changed durable state, new evidence, milestone progress, or when
explicitly marked idempotent and safe.

`EstimatedInformationGain` is real entropy reduction over the contract's hypothesis set. Without
hypotheses a **proxy** based on open failures, passed checks, and milestones is used. The proxy is
not mutual information.

## License

Apache-2.0. See `LICENSE`.
