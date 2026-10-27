# Domain DSLM Workflow

TaskSentry's domain layer turns service-company records into a versioned,
redacted, replayable dataset that remains governed by the existing harness.
The first vertical is telecom 5G RAN L2 operations.

## Canonical schema

`tasksentry.domain.schema` defines `Ticket`, `SopDoc`, `CommandSpec`, `Step`,
`Trajectory`, and `Outcome`. Every record carries `schema_version`,
`tenant_id`, and `label_source` (`human_confirmed`, `auto_verified`, or
`inferred`). A trajectory follows the contract in `plan.md`: ticket/context,
typed command steps with observations/posteriors, decision, remediation, and
outcome.

Ticket text, SOP text, and observations are untrusted data. They never set a
risk tier or approval rule.

## Ingestion and privacy

`domain.ingest` recognizes JSON, JSONL, CSV, and ChatML deterministically and
returns row-level issues. An optional recognizer protocol is disabled unless a
caller explicitly enables it. `TenantRedactor` replaces emails, optional IPs,
tokens, and keys with tenant-local reversible placeholders. The map is kept
outside exported records. Deduplication is stable and first-wins.

`split_records` is chronological and can group records by customer. Random
splitting is rejected to prevent customer/future leakage.

## Typed command catalog

`domain.catalog.CommandCatalog` is the only domain execution surface. A
command has an ID, typed JSON-schema arguments, an argv template, risk tier,
preconditions, verifier, rollback link, and tenant scope. `render()` returns
an argument list; it never builds a shell string. Unknown arguments, wrong
types, shell control characters, missing placeholders, unmet preconditions,
unknown commands, and invalid rollback links fail closed.

Catalog drafts generated from SOP steps are unapproved until a human promotes
them. `build_registry()` exposes only catalog IDs through the existing
`ToolRegistry`/`ToolGovernor` path.

## Dataset exports

`export_datasets()` writes deterministic JSONL artifacts:

- `sft.jsonl`: one typed action per verified step plus verified final decisions.
- `preference.jsonl`: verified-good vs verified-bad/escalated pairs.
- `refusal.jsonl`: verified escalation examples.
- `format_repair.jsonl`: only explicitly recorded malformed/corrected pairs.
- `dataset_card.json` and `dataset_card.md`: counts, splits, labels, redaction
  statistics, versions, and source hash.

Only `human_confirmed` and `auto_verified` labels can train decision or
remediation targets.

## Autonomy ladder

`domain.autonomy` is per tenant and command risk class:

- **L0:** shadow/propose only.
- **L1:** read-only automatic execution; remediation remains proposed.
- **L2:** reversible writes with verification and rollback evidence.
- **L3:** approval is always required.

The kill switch, hourly action cap, and blast-radius cap are checked before
execution. Unknown commands, failed verification, budget failures, and policy
errors escalate or deny. Promotion requires a minimum sample count, Wilson
lower confidence bound, zero unsafe actions/policy violations, and tested
rollback evidence.

## Replay evaluation

`domain.replay` uses a read-only simulated backend containing recorded
observations. It reports root-cause top-1/top-3, calibration ECE, probe
efficiency, escalation precision/recall, format/tool validity, unsafe actions,
and lane cost/latency with sample sizes and confidence intervals. The
harness-only baseline is deterministic; plugins implement the `ReplayModel`
protocol. `compare_baseline()` provides a regression gate.

## CLI and demo

```bash
python -m tasksentry.cli domain ingest --input tickets.jsonl --tenant acme --out build/acme
python -m tasksentry.cli domain catalog --input sop.json --tenant acme --out build/catalog.json
python -m tasksentry.cli domain export --input trajectories.jsonl --tenant acme --out build/dataset
python -m tasksentry.cli domain eval --input trajectories.jsonl --tenant acme --split test --out reports/replay
python examples/domain_5g_demo.py --out reports/domain-demo
```

The demo is offline and marks simulated observations/results explicitly.

## Honest limitations

The replay backend is simulated and does not prove production network safety.
The harness-only baseline is not a fine-tuned DSLM. Hypotheses and labels are
only as reliable as the source records and human verification. Real customer
backends, vault injection, model training, constrained decoding, and external
audit anchoring remain future work.
