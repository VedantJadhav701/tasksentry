"""Telecom 5G RAN domain pack for the universal engine.

Wraps the existing sandboxed telecom tools (tools.py) as Bayesian probes and
remediations. Sensitivities below are expert priors; re-estimate them from the
labelled ticket dataset (see analytics.estimate_priors) for production.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any

from tasksentry.harness.domain import DomainPack, Remediation
from tasksentry.math.bayes_rca import Probe, dirichlet_prior

HYPOTHESES = ["software", "midhaul", "timing", "fronthaul", "admin_lock", "hardware"]

# P(probe abnormal | hypothesis)
SENSITIVITY: dict[str, dict[str, float]] = {
    "ping": {
        "software": 0.02,
        "midhaul": 0.03,
        "timing": 0.02,
        "fronthaul": 0.02,
        "admin_lock": 0.02,
        "hardware": 0.60,
    },
    "pods": {
        "software": 0.95,
        "midhaul": 0.05,
        "timing": 0.03,
        "fronthaul": 0.03,
        "admin_lock": 0.02,
        "hardware": 0.30,
    },
    "cell_state": {
        "software": 0.95,
        "midhaul": 0.95,
        "timing": 0.95,
        "fronthaul": 0.95,
        "admin_lock": 0.95,
        "hardware": 0.90,
    },
    "f1c": {
        "software": 0.10,
        "midhaul": 0.97,
        "timing": 0.10,
        "fronthaul": 0.10,
        "admin_lock": 0.05,
        "hardware": 0.50,
    },
    "timing": {
        "software": 0.03,
        "midhaul": 0.03,
        "timing": 0.97,
        "fronthaul": 0.10,
        "admin_lock": 0.02,
        "hardware": 0.05,
    },
    "admin": {
        "software": 0.01,
        "midhaul": 0.01,
        "timing": 0.01,
        "fronthaul": 0.01,
        "admin_lock": 0.98,
        "hardware": 0.01,
    },
    "ru_alarm": {
        "software": 0.05,
        "midhaul": 0.05,
        "timing": 0.05,
        "fronthaul": 0.95,
        "admin_lock": 0.03,
        "hardware": 0.05,
    },
    "platform": {
        "software": 0.05,
        "midhaul": 0.05,
        "timing": 0.05,
        "fronthaul": 0.05,
        "admin_lock": 0.03,
        "hardware": 0.90,
    },
}
COST = {
    "ping": 1,
    "pods": 2,
    "cell_state": 1,
    "f1c": 1,
    "timing": 1,
    "admin": 1,
    "ru_alarm": 2,
    "platform": 3,
}

FAILURE_TO_HYPOTHESIS = (
    ("midhaul", "midhaul"),
    ("software", "software"),
    ("timing", "timing"),
    ("sync", "timing"),
    ("holdover", "timing"),
    ("fronthaul", "fronthaul"),
    ("ruconnectivity", "fronthaul"),
    ("admin", "admin_lock"),
    ("lock", "admin_lock"),
    ("hardware", "hardware"),
    ("sysmon", "hardware"),
)

ESCALATION = {
    "midhaul": "IP / CU / Core team",
    "fronthaul": "Field / O-RU team",
    "hardware": "Platform / Hardware team",
    "software": "DU Software / L2",
    "timing": "Transport / Timing team",
    "admin_lock": "NOC L2",
}


def hypothesis_of_failure(failure_type: str) -> str | None:
    ft = failure_type.lower()
    for needle, hyp in FAILURE_TO_HYPOTHESIS:
        if needle in ft:
            return hyp
    return None


def default_priors(counts: dict[str, int] | None = None) -> dict[str, float]:
    return dirichlet_prior(counts or {}, HYPOTHESES, alpha=1.0)


def build_telecom_pack(
    tools: dict[str, Callable[..., dict[str, Any]]],
    priors: dict[str, float] | None = None,
    flip_prob: float = 0.0,
    rng: random.Random | None = None,
) -> DomainPack:
    """`tools` maps telecom tool name -> callable (as created by create_telecom_tools).

    flip_prob simulates sensor noise / false alarms on probe outcomes.
    """
    r = rng or random.Random(0)

    def raw_probe(name: str) -> bool:
        if name == "ping":
            return bool(tools["telecom_ping"](host="DU")["status"] == "FAIL")
        if name == "pods":
            return bool(tools["telecom_k8s_pods"]()["status"] == "FAIL")
        if name == "cell_state":
            return bool(
                tools["telecom_confd_cli"](service_ip="127.0.0.1", command="show nr-cell")["status"]
                == "FAIL"
            )
        if name == "f1c":
            return bool(
                tools["telecom_confd_cli"](service_ip="127.0.0.1", command="show du-f1c")["status"]
                == "FAIL"
            )
        if name == "timing":
            return bool(tools["telecom_timedatectl"]()["status"] == "FAIL")
        if name == "admin":
            res = tools["telecom_confd_cli"](service_ip="127.0.0.1", command="administrative state")
            return bool(res.get("administrative_state") == "LOCKED")
        if name == "ru_alarm":
            return bool(
                tools["telecom_notifmgr_logs"]().get("first_alarm_in_sequence")
                == "notifAniRuConnectivityFailure"
            )
        if name == "platform":
            return bool(tools["telecom_platform_check"]()["status"] == "FAIL")
        raise KeyError(name)

    def run_probe(name: str) -> bool:
        out = raw_probe(name)
        return bool((not out) if (flip_prob > 0 and r.random() < flip_prob) else out)

    def verify() -> bool:
        return bool(
            tools["telecom_confd_cli"](service_ip="127.0.0.1", command="show nr-cell")["status"]
            == "PASS"
        )

    remediations = {
        "software": Remediation(
            "redeploy_du_pod",
            "reversible_write",
            lambda: tools["telecom_redeploy_pod"](pod_name="duapp-nrconfd-01"),
            success_prob=0.90,
            benefit=100,
            harm=20,
            cost=1,
        ),
        "timing": Remediation(
            "ptp_resync",
            "reversible_write",
            lambda: tools["telecom_timedatectl"](restart_sync=True),
            success_prob=0.85,
            benefit=100,
            harm=15,
            cost=1,
        ),
        "admin_lock": Remediation(
            "unlock_nr_cell",
            "reversible_write",
            lambda: tools["telecom_confd_cli"](service_ip="127.0.0.1", command="unlock nr-cell"),
            success_prob=0.95,
            benefit=100,
            harm=10,
            cost=1,
        ),
        "hardware": Remediation(
            "bmc_power_cycle",
            "system_write",
            lambda: tools["telecom_ipmi_power_cycle"](bmc_ip="<BMC_IP>"),
            success_prob=0.80,
            benefit=100,
            harm=80,
            cost=5,
        ),
    }
    return DomainPack(
        name="telecom-5g-ran",
        priors=priors or default_priors(),
        probes=[Probe(n, SENSITIVITY[n], float(COST[n])) for n in SENSITIVITY],
        run_probe=run_probe,
        verify=verify,
        remediations=remediations,
        escalation=ESCALATION,
        default_escalation="Field / L2 Support",
    )


def build_from_state(state: Any, **kwargs: Any) -> DomainPack:
    """Convenience: build the pack from a TelecomSimulationState."""
    from tasksentry.telecom.tools import create_telecom_tools

    return build_telecom_pack({t.name: t.callable for t in create_telecom_tools(state)}, **kwargs)
