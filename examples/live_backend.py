"""Register a customer-owned live backend for universal onboarding.

The functions in this example are intentionally placeholders.  Replace them
with authenticated SDK calls to the customer's observability and remediation
systems, then register the backend during service startup.  The web/API layer
can select it with ``execution_mode=live`` and ``backend_id=customer-ran``.
"""

from __future__ import annotations

from tasksentry.harness.backend import CallableBackend, default_backend_registry


def register_customer_backend() -> None:
    def probe_pods() -> bool:
        # Query the customer's Kubernetes API and return True for abnormal.
        raise NotImplementedError("connect this probe to the customer Kubernetes API")

    def remediate_pods() -> dict[str, object]:
        # Use an allowlisted deployment rollout, never arbitrary model commands.
        raise NotImplementedError("connect this action to the approved rollout API")

    def verify_cell() -> bool:
        # Query the authoritative post-state from the customer's control plane.
        raise NotImplementedError("connect this verifier to the customer control plane")

    default_backend_registry.register(
        CallableBackend(
            name="customer-ran",
            probes={"pods": probe_pods},
            remediations={"redeploy_action": remediate_pods},
            verifier=verify_cell,
            metadata={"owner": "customer-operations", "environment": "production"},
        )
    )


if __name__ == "__main__":
    register_customer_backend()
    print(default_backend_registry.names())
