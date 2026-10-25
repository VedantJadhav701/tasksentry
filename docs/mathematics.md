# Mathematical Foundations of TaskSentry

TaskSentry grounds autonomous agent supervision in rigorous progress metrics, information theory, and canonical task state hashing.

---

## 1. Canonical Task State & Hashing

Let the canonical task state at step $t$ be defined as the tuple:
$$s_t = (g, M_t, K_t, W_t)$$
where:
- $g$: Immutable task goal string.
- $M_t$: Frozenset of verified milestone IDs achieved up to step $t$.
- $K_t$: Sorted tuple of success criteria IDs declared in the task contract.
- $W_t$: Immutable mapping of durable world facts (e.g., created artifacts, verified facts).

### Progress Hash
The canonical state hash is computed using SHA-256 over normalized canonical representations:
$$\text{hash}(s_t) = \text{SHA256}(\text{repr}(g) \,\|\, \text{sorted}(M_t) \,\|\, K_t \,\|\, \text{sorted}(W_t))$$

**Critical Property**: Volatile data—such as timestamps, execution duration, trace IDs, budget counters, and conversation logs—are strictly excluded from $s_t$. Thus:
$$\text{hash}(s_{t+1}) = \text{hash}(s_t) \iff \text{no durable milestone or fact changed}$$

---

## 2. Action Fingerprints

To detect repetition cycles across identical states:
$$\text{fp}_t = \text{SHA256}(\text{tool\_name} \,\|\, \text{canonical\_json}(\text{args}) \,\|\, \text{hash}(s_t))$$

Embedding the pre-action state hash $\text{hash}(s_t)$ into the fingerprint ensures that calling `run_tests()` before and after editing code generates different fingerprints, preventing false-positive duplicate blocking.

---

## 3. Bayesian Belief Tracking & Information Gain

When the agent evaluates competing hypotheses $H = \{h_1, h_2, \dots, h_m\}$ (e.g., possible root causes of a failure):

### Prior & Likelihood Update
Given prior $P(h_i)$ and evidence $e_t$ observed from tool execution with likelihood $P(e_t \mid h_i)$:
$$P(h_i \mid e_t) = \frac{P(e_t \mid h_i) P(h_i)}{\sum_{j=1}^m P(e_t \mid h_j) P(h_j)}$$

### Shannon Entropy & Information Gain
The entropy of the belief distribution over hypotheses is:
$$H(t) = -\sum_{i=1}^m P_t(h_i) \log_2 P_t(h_i)$$
The True Information Gain (entropy reduction) is:
$$\text{IG}_t = \max(0, H(t-1) - H(t))$$

### Proxy Information Gain (Fallback)
When an explicit hypothesis set is not supplied in the contract, TaskSentry employs a bounded heuristic proxy:
$$\text{ProxyIG}_t = \text{clamp}\left(0.4 \cdot \Delta \text{PassedChecks} + 0.4 \cdot \Delta M_t - 0.2 \cdot \text{OpenFailures}, \, 0.0, \, 1.0\right)$$

---

## 4. Agent Progress Gain (APG)

At each step $t$, the scalar Agent Progress Gain ($APG_t$) balances forward progress against repetition and cost:

$$APG_t = \alpha_1 \cdot \text{StateChange}_t + \alpha_2 \cdot \text{MilestoneProgress}_t + \alpha_3 \cdot \widehat{IG}_t + \alpha_4 \cdot \text{EvidenceNovelty}_t - \alpha_5 \cdot \text{RepetitionPenalty}_t - \alpha_6 \cdot \text{NormalizedCost}_t$$

### Default Heuristic Weights
- $\alpha_1 = 1.0$ (State Change: binary indicator whether $\text{hash}(s_{t+1}) \neq \text{hash}(s_t)$)
- $\alpha_2 = 1.0$ (Milestone Progress: $|M_{t+1}| - |M_t|$)
- $\alpha_3 = 0.8$ (Estimated or Proxy Information Gain)
- $\alpha_4 = 0.8$ (Evidence Novelty: $1 - \max_{j < t} \text{JaccardSimilarity}(o_t, o_j)$)
- $\alpha_5 = 2.0$ (Effective Repetition Penalty)
- $\alpha_6 = 0.1$ (Normalized Cost: $\min(\text{cost}_t / \text{cost\_cap}, 1.0)$)

### Repetition Penalty & Exemptions
$$\text{RepetitionPenalty}_t = 0 \quad \text{if retry is exempted}$$
$$\text{RepetitionPenalty}_t = \min(2.0, \text{duplicate\_count} + \text{semantic\_similarity}) \quad \text{otherwise}$$

**Exemption Rules**: An action is exempt from repetition penalty if:
1. The previous call encountered a transient error (e.g., timeout, network reset).
2. Arguments changed meaningfully.
3. Durable state $s_t$ changed.
4. Output produced novel evidence ($\text{novelty} \ge 0.5$).
5. Milestone progress occurred.
6. The tool is declared `idempotent = True` and safe.

---

## 5. Rolling Window Gain & Exponential Moving Average

### Rolling Window Gain
For rolling window length $n$ (default $n=5$):
$$\text{WindowGain}_t = \sum_{k=t-n+1}^t APG_k$$

### Exponential Moving Average (EMA)
$$\text{EMA}_t = \beta \cdot APG_t + (1 - \beta) \cdot \text{EMA}_{t-1} \quad (\text{default } \beta = 0.3, \, \text{EMA}_0 = 0)$$

---

## 6. Canonical Stop Policy

The canonical stop policy evaluates $\text{WindowGain}_t$ once $t \ge n$ (cold start protection for $t < n$):

| Condition | Action | Description |
|---|---|---|
| $t < n$ | `CONTINUE` | Cold start grace period. |
| $\text{WindowGain}_t > 0$ | `CONTINUE` | Net forward progress. |
| $-1 < \text{WindowGain}_t \le 0$ | `WARN` | Low progress warning emitted; require new strategy. |
| $-2 < \text{WindowGain}_t \le -1$ | `FORCE_REPLAN` | Stagnation detected; force recovery replan. |
| $\text{WindowGain}_t \le -2$ | `STOP` / `ESCALATE` | Deadlock; terminate loop and escalate to human. |

### Blocked Duplicates Bookkeeping
Actions that are blocked pre-execution by `ActionGate` **do not enter `WindowGain`**. They carry a fixed controller penalty of $-0.5$, are tracked separately, and trigger immediate task escalation upon reaching 3 blocked calls.

---

## 7. Benchmark Performance Metrics

- **Task Success Rate**: $\frac{N_{\text{success}}}{N_{\text{total}}}$
- **Wasted Action Rate**: $\frac{\sum \mathbb{I}(APG_t \le 0)}{\sum N_{\text{actions}}}$
- **Loop Escape Rate**: $\frac{N_{\text{recovered\_after\_warning}}}{N_{\text{warned}}}$
- **Efficiency-Adjusted Success Rate**: $\text{SuccessRate} \cdot (1 - \text{WastedActionRate})$
