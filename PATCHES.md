# Patches to existing files (3 small fixes)

## 1. telecom/agent.py — compliance score is always 1.0
`sop_steps_correct += 1` runs unconditionally, so `compliance_score` can never drop.
Replace
```python
            node_res = self._execute_sop_step(step_num, step_def, ticket)
            sop_steps_correct += 1
```
with
```python
            node_res = self._execute_sop_step(step_num, step_def, ticket)
            if step_num in (1, 2, 3, 4, 5, 6) and step_def is not None:
                sop_steps_correct += 1
```

## 2. telecom/tools.py — simulator makes timing/fronthaul/admin look like midhaul
`TelecomSimulationState.from_ticket_failure_type` leaves `f1c_connected=False` (the default) for the
timing, fronthaul and admin cases. Add `f1c_connected=True` to those three `cls(...)` calls.
`telecom/analytics.py::state_for_label` already does this for benchmarks.

## 3. console/runs.py — receipt reports success even when verification failed
- `success=not run.is_stopped()` and `final_answer="Task processed and verified."` are hardcoded.
  Track `verified = v_res.passed` where `verification_passed/failed` is emitted (init `verified = False`
  before the loop), then use `success=(verified and not run.is_stopped())` and
  `final_answer=` the last `action.get("answer")` or "Stopped/unverified".
- `RoutingDecision(latency_ms=120.0, tokens={"input": 450, "output": 35})` are made-up constants.
  Use measured values (time the `agent.step` call; read tokens from `task.runtime.budget`).
