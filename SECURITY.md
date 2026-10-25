# Security Policy

The TaskSentry maintainers take the security of agent systems, execution harnesses, and developer environments seriously.

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |
| < 0.1   | :x:                |

## Reporting a Vulnerability

Please **DO NOT** report security vulnerabilities through public GitHub issues.

To report a vulnerability, please send an encrypted email or advisory to:
- **Email**: `security@tasksentry.org` or open a private GitHub Security Advisory at `https://github.com/VedantJadhav701/tasksentry/security/advisories/new`.

Please include:
- A description of the issue and potential impact
- Detailed reproduction steps or proof-of-concept
- Any affected components, tools, or configurations

We will acknowledge receipt of your report within 48 hours and provide a timeline for triage and remediation.

---

## Security Model & Trust Boundaries

### 1. In-Process Sandbox Is Not a Security Boundary
The default `Sandbox(mode="in_process")` is an execution wrapper designed for latency measurement, error capture, and exception handling. **It does NOT provide security virtualization, file system sandboxing, or memory isolation.** Any code executed in in-process mode runs with the full permissions of the host Python process.

### 2. Process-Isolated Sandbox Limitations
`Sandbox(mode="process_isolated")` launches tools in separate Python sub-processes using `multiprocessing`. While this protects the parent runtime from crashes, unhandled SIGSEGV, and infinite blocking via timeouts, **it is NOT an OS-level sandbox or container boundary**. Process-isolated sub-processes still have the OS user's disk and network access unless wrapped in external containerization (e.g., Docker, gVisor, or Firecracker).

### 3. Tool Approval & Risk Allowlists
Task contracts can enforce safety policies:
- `require_approval_for_writes`: Forces the harness to prompt for approval or check an authorization callback before executing `write` or `destructive` tools.
- `allowed_tools`: Restricts agent tool calls to an explicit allowlist.
- `max_risk`: Rejects any tool whose declared risk exceeds the task threshold.

**Recommendation**: When running untrusted model prompts, always require write approvals, enforce tool allowlists, and set conservative budget limits.

### 4. Local Dashboard Network Binding
The local dashboard runs via FastAPI and Uvicorn and is designed strictly for local developer inspection:
- It binds to `127.0.0.1` by default.
- It does **NOT** provide authentication, authorization, or TLS out of the box.
- **NEVER** expose the local dashboard port (`8321`) to the public internet or untrusted internal networks without putting a reverse proxy with authentication in front of it.

### 5. Untrusted Tools and Pickling
Process-isolated tool execution serializes inputs and outputs via Python's standard `multiprocessing` queues (pickle). Ensure that tool callables and their arguments come from trusted registries, and do not execute dynamically loaded untrusted bytecode.
