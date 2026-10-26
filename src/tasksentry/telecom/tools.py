"""Telecom 5G RAN diagnostic and remediation tools governed by TaskSentry.

Implements safe, sandboxed execution with strict risk classifications:
read, reversible_write, system_write.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from tasksentry.tools.registry import Tool


class PingArgs(BaseModel):
    host: str = Field(description="Target host IP address or hostname to ping")
    count: int = Field(default=4, description="Number of ICMP packets to send")


class K8sPodsArgs(BaseModel):
    gnb_du: str = Field(default="", description="GNB DU identifier to grep for")
    namespace: str = Field(default="all", description="Kubernetes namespace (or 'all' for -A)")


class ConfdCliArgs(BaseModel):
    service_ip: str = Field(default="127.0.0.1", description="Confd service IP or hostname")
    command: str = Field(
        description="Confd CLI command to execute (e.g. show nr-cell, show du-f1c)"
    )


class NotifmgrLogArgs(BaseModel):
    log_path: str = Field(
        default="/var/log/ani/notifmgr.log", description="Path to notifmgr log file"
    )
    filter_pattern: str = Field(default="", description="Managed element or cell path to filter")
    event_time: str = Field(default="", description="Event time string for window filtering")
    alarm_keywords: list[str] = Field(
        default_factory=lambda: [
            "notifAniRuConnectivityOk",
            "notifAniTimingUnlocked",
            "notifAniCoolingFanBroken",
            "aniNoExternalSyncSource",
            "notifAniRuConnectivityFailure",
            "notifAniCertAboutToExpire",
            "aniInterfaceFault",
            "Application DOWN indication received",
            "notifAniTiminglocked",
            "aniTemperatureFailure",
            "softwarefailure",
            "aniCellDown",
            "aniOperationWarning",
            "midhaulfailure",
            "mgmtoperation",
            "lbmfailure",
        ],
        description="Alarm names to correlate in notifmgr logs",
    )


class PlatformCheckArgs(BaseModel):
    du_host: str = Field(default="", description="DU host identifier or IP")
    check_type: str = Field(
        default="all",
        description="Type: 'sysmon' (reboot), 'snapshots', 'ipmitool', or 'all'",
    )
    date_filter: str = Field(default="", description="Date string to filter logs")


class TimedatectlArgs(BaseModel):
    detail: bool = Field(default=True, description="Whether to include rs-timing sync status")
    restart_sync: bool = Field(default=False, description="Attempt PTP resynchronization")


class OruStatusArgs(BaseModel):
    mplane_ip: str = Field(default="", description="O-RU M-Plane IP address")


class RedeployPodArgs(BaseModel):
    pod_name: str = Field(description="Name of the crashed/missing DU application pod to redeploy")
    namespace: str = Field(default="default", description="Namespace of the pod")


class PowerCycleArgs(BaseModel):
    bmc_ip: str = Field(description="Target BMC IP to issue power cycle")
    force: bool = Field(
        default=False, description="Whether to force immediate hardware power reset"
    )


class TelecomSimulationState:
    """Configurable state for Telecom sandbox simulation and testing."""

    def __init__(
        self,
        host_reachable: bool = True,
        crashed_pods: list[str] | None = None,
        cell_active: bool = False,
        carriers_transmitting: bool = False,
        oru_timing_locked: bool = True,
        admin_state: str = "UNLOCKED",
        f1c_connected: bool = False,
        first_alarm: str = "midhaulfailure",
        has_snapshot_failure: bool = False,
        has_sysmon_reboot: bool = False,
        has_bmc_watchdog: bool = False,
    ) -> None:
        self.host_reachable = host_reachable
        self.crashed_pods = list(crashed_pods or [])
        self.cell_active = cell_active
        self.carriers_transmitting = carriers_transmitting
        self.oru_timing_locked = oru_timing_locked
        self.admin_state = admin_state
        self.f1c_connected = f1c_connected
        self.first_alarm = first_alarm
        self.has_snapshot_failure = has_snapshot_failure
        self.has_sysmon_reboot = has_sysmon_reboot
        self.has_bmc_watchdog = has_bmc_watchdog

    @classmethod
    def from_ticket_failure_type(cls, failure_type: str) -> TelecomSimulationState:
        """Seed simulation state based on ticket failure classification."""
        ft = failure_type.lower()
        if "midhaul" in ft:
            return cls(
                host_reachable=True,
                cell_active=False,
                f1c_connected=False,
                first_alarm="midhaulfailure",
            )
        if "software" in ft:
            return cls(
                host_reachable=True,
                crashed_pods=["duapp-nrconfd-01 (CrashLoopBackOff)", "duapp-l2-agent (Error)"],
                cell_active=False,
                f1c_connected=True,
                first_alarm="softwarefailure",
            )
        if "timing" in ft or "sync" in ft or "holdover" in ft:
            return cls(
                host_reachable=True,
                oru_timing_locked=False,
                cell_active=False,
                first_alarm="notifAniTimingUnlocked",
            )
        if "fronthaul" in ft:
            return cls(
                host_reachable=True,
                cell_active=False,
                first_alarm="notifAniRuConnectivityFailure",
            )
        if "admin" in ft or "lock" in ft:
            return cls(
                host_reachable=True,
                cell_active=False,
                admin_state="LOCKED",
                first_alarm="mgmtoperation",
            )
        return cls()


def create_telecom_tools(sim_state: TelecomSimulationState | None = None) -> list[Tool]:
    """Create TaskSentry Tool instances configured with the given simulation state."""
    state = sim_state or TelecomSimulationState()

    def run_ping(host: str, count: int = 4) -> dict[str, Any]:
        if not state.host_reachable:
            return {
                "status": "FAIL",
                "packet_loss_percent": 100,
                "output": (
                    f"PING6 {host}: 4 packets transmitted, 0 received, 100% packet loss. "
                    "Destination Host Unreachable."
                ),
            }
        return {
            "status": "PASS",
            "packet_loss_percent": 0,
            "output": (
                f"PING6 {host}: 4 packets transmitted, 4 received, 0% packet loss. "
                "rtt min/avg/max = 0.42/0.65/0.89 ms"
            ),
        }

    def run_k8s_pods(gnb_du: str = "", namespace: str = "all") -> dict[str, Any]:
        if state.crashed_pods:
            return {
                "status": "FAIL",
                "healthy": False,
                "crashed_pods": state.crashed_pods,
                "output": "\n".join(state.crashed_pods),
            }
        return {
            "status": "PASS",
            "healthy": True,
            "crashed_pods": [],
            "output": (
                "All 18 DU application pods Running (1/1 Ready). "
                "No CrashLoopBackOff or OOMKilled detected."
            ),
        }

    def run_confd_cli(service_ip: str, command: str) -> dict[str, Any]:
        cmd_lower = command.lower()
        if "show nr-cell" in cmd_lower:
            st = "NRCELL_DU_ACTIVE" if state.cell_active else "NRCELL_DU_IDLE"
            return {
                "status": "PASS" if state.cell_active else "FAIL",
                "cell_state": st,
                "output": f"cell-state: {st}",
            }

        if "show nr-sector-carrier" in cmd_lower:
            c_st = (
                "NRSECTOR_CARRIER_TRANSMITTING"
                if state.carriers_transmitting
                else "NRSECTOR_CARRIER_BASEBAND_CONFIGURED"
            )
            return {
                "status": "PASS" if state.carriers_transmitting else "FAIL",
                "carrier_state": c_st,
                "output": f"carrier-state: {c_st}",
            }

        if "show rumgr-state" in cmd_lower:
            r_st = "RU_TIMING_LOCKED" if state.oru_timing_locked else "RU_WAIT_FOR_CALL_HOME"
            return {
                "status": "PASS" if state.oru_timing_locked else "FAIL",
                "ru_state": r_st,
                "output": f"rumgr: {r_st}",
            }

        if "show du-f1c" in cmd_lower:
            f1_st = "SETUP_COMPLETE" if state.f1c_connected else "DOWN"
            return {
                "status": "PASS" if state.f1c_connected else "FAIL",
                "f1c_state": f1_st,
                "output": f"DU-F1C: {f1_st}",
            }

        if "administrative" in cmd_lower:
            return {
                "status": "PASS",
                "administrative_state": state.admin_state,
                "output": f"administrativeState: {state.admin_state}",
            }

        if "unlock" in cmd_lower:
            state.admin_state = "UNLOCKED"
            state.cell_active = True
            state.carriers_transmitting = True
            return {
                "status": "PASS",
                "cell_state": "NRCELL_DU_ACTIVE",
                "output": (
                    "nr-cell administrativeState set to UNLOCKED. "
                    "Cell operational state transitioned to NRCELL_DU_ACTIVE."
                ),
            }

        return {"status": "PASS", "output": f"Command '{command}' executed successfully."}

    def run_notifmgr(
        log_path: str = "/var/log/ani/notifmgr.log",
        filter_pattern: str = "",
        event_time: str = "",
        alarm_keywords: list[str] | None = None,
    ) -> dict[str, Any]:
        first_alarm = state.first_alarm or "aniCellDown"
        return {
            "status": "CORRELATED",
            "first_alarm_in_sequence": first_alarm,
            "alarm_history": [
                {"timestamp": "2026-10-26T10:14:02Z", "alarm": first_alarm, "severity": "CRITICAL"},
                {"timestamp": "2026-10-26T10:14:05Z", "alarm": "aniCellDown", "severity": "MAJOR"},
            ],
            "rca_driver": first_alarm,
            "output": (
                f"Found alarm sequence at {event_time or 'event_time'}. "
                f"First alarm in sequence is '{first_alarm}'."
            ),
        }

    def run_platform_check(
        du_host: str = "", check_type: str = "all", date_filter: str = ""
    ) -> dict[str, Any]:
        issues = []
        if state.has_snapshot_failure:
            issues.append("snapshot_push_failure detected in /rs_obsrv/snapshots_push_failure/")
        if state.has_sysmon_reboot:
            issues.append(
                "reboot triggered by sysmon watchdog in /var/log/arc/sysmon/sysmonRebootInfo.txt"
            )
        if state.has_bmc_watchdog:
            issues.append("IPMI SEL: Processor Watchdog Power cycle event recorded")

        has_failure = len(issues) > 0
        return {
            "status": "FAIL" if has_failure else "PASS",
            "hardware_issues": issues,
            "output": "; ".join(issues)
            if issues
            else "No snapshot failures, sysmon reboots, or IPMI SEL errors found.",
        }

    def run_timedatectl(detail: bool = True, restart_sync: bool = False) -> dict[str, Any]:
        if restart_sync:
            state.oru_timing_locked = True
            state.cell_active = True
            return {
                "status": "PASS",
                "system_clock_synchronized": "yes",
                "rs_timing_sync_status": "LOCKED",
                "output": (
                    "rs-timing service restarted. PTP GNSS/1588v2 locked. "
                    "Frequency and phase offset < 15ns."
                ),
            }
        sync = "yes" if state.oru_timing_locked else "no"
        ptp = "LOCKED" if state.oru_timing_locked else "HOLDOVER"
        return {
            "status": "PASS" if state.oru_timing_locked else "FAIL",
            "system_clock_synchronized": sync,
            "rs_timing_sync_status": ptp,
            "output": (
                f"System clock synchronized: {sync}\nrs-timing service: active\nsync_status: {ptp}"
            ),
        }

    def run_oru_status(mplane_ip: str = "") -> dict[str, Any]:
        return {
            "status": "PASS" if state.oru_timing_locked else "FAIL",
            "mplane_established": True,
            "ptp_locked": state.oru_timing_locked,
            "optical_power_dbm": -2.4,
            "output": (
                f"O-RU M-Plane established. PTP locked: {state.oru_timing_locked}. "
                "Optical Rx: -2.4 dBm. Alarms: 0"
            ),
        }

    def run_redeploy_pod(pod_name: str, namespace: str = "default") -> dict[str, Any]:
        # Remediation action: Clears crashed pods and restores healthy pod state
        state.crashed_pods.clear()
        state.cell_active = True
        return {
            "status": "SUCCESS",
            "message": (
                f"DU application pod '{pod_name}' successfully redeployed in "
                f"namespace '{namespace}'. Pod status: Running."
            ),
        }

    def run_power_cycle(bmc_ip: str, force: bool = False) -> dict[str, Any]:
        # High-risk remediation action: Resets BMC and reboots DU
        state.host_reachable = True
        state.crashed_pods.clear()
        state.cell_active = True
        state.carriers_transmitting = True
        state.f1c_connected = True
        return {
            "status": "SUCCESS",
            "message": (
                f"BMC at {bmc_ip} hardware power cycle executed. Host successfully rebooted."
            ),
        }

    tools = [
        Tool(
            name="telecom_ping",
            description="Pings a DU host to verify NOC/jump server network reachability.",
            callable=run_ping,
            input_model=PingArgs,
            risk="read",
            idempotent=True,
            timeout_seconds=5.0,
        ),
        Tool(
            name="telecom_k8s_pods",
            description="Inspects Kubernetes DU application pods health and finds crashed pods.",
            callable=run_k8s_pods,
            input_model=K8sPodsArgs,
            risk="read",
            idempotent=True,
            timeout_seconds=8.0,
        ),
        Tool(
            name="telecom_confd_cli",
            description="Queries confd CLI for cell states, rumgr states, and F1C connectivity.",
            callable=run_confd_cli,
            input_model=ConfdCliArgs,
            risk="read",
            idempotent=True,
            timeout_seconds=8.0,
        ),
        Tool(
            name="telecom_notifmgr_logs",
            description="Correlates notifmgr log events around incident time window for RCA.",
            callable=run_notifmgr,
            input_model=NotifmgrLogArgs,
            risk="read",
            idempotent=True,
            timeout_seconds=10.0,
        ),
        Tool(
            name="telecom_platform_check",
            description="Checks DU platform health including sysmon reboots and IPMI SEL logs.",
            callable=run_platform_check,
            input_model=PlatformCheckArgs,
            risk="read",
            idempotent=True,
            timeout_seconds=8.0,
        ),
        Tool(
            name="telecom_timedatectl",
            description="Validates system clock synchronization, rs-timing, and PTP timing lock.",
            callable=run_timedatectl,
            input_model=TimedatectlArgs,
            risk="read",
            idempotent=True,
            timeout_seconds=5.0,
        ),
        Tool(
            name="telecom_oru_status",
            description="Validates O-RU M-Plane, PTP, packets, and optical power status.",
            callable=run_oru_status,
            input_model=OruStatusArgs,
            risk="read",
            idempotent=True,
            timeout_seconds=8.0,
        ),
        Tool(
            name="telecom_redeploy_pod",
            description="Redeploys a crashed DU application pod to restore cell activity.",
            callable=run_redeploy_pod,
            input_model=RedeployPodArgs,
            risk="reversible_write",
            idempotent=False,
            timeout_seconds=15.0,
        ),
        Tool(
            name="telecom_ipmi_power_cycle",
            description="Executes BMC hardware power cycle. High-risk write requiring approval.",
            callable=run_power_cycle,
            input_model=PowerCycleArgs,
            risk="system_write",
            idempotent=False,
            timeout_seconds=30.0,
        ),
    ]
    return tools


class TelecomSolveArgs(BaseModel):
    ticket_id: str = Field(
        description="5G RAN ticket ID (e.g. 'tsd_000001', 'tsd_000002') or problem description"
    )
    enable_self_healing: bool = Field(
        default=True,
        description=(
            "Whether to attempt autonomous self-healing for remediable failures "
            "(pod crash, admin lock, PTP drift)"
        ),
    )


class TelecomInspectArgs(BaseModel):
    ticket_id: str = Field(
        description="5G RAN ticket ID to inspect metadata and SOP steps for (e.g. 'tsd_000001')"
    )


class TelecomListArgs(BaseModel):
    limit: int = Field(default=5, description="Maximum number of tickets to retrieve")
    failure_type: str = Field(
        default="",
        description="Optional filter by failure type (e.g. 'softwarefailure', 'midhaulfailure')",
    )


def get_telecom_agent_tools() -> list[Tool]:
    """High-level telecom investigation tools for the main TaskSentry Chat Agent."""

    def handle_solve(ticket_id: str, enable_self_healing: bool = True) -> dict[str, Any]:
        from tasksentry.telecom.loader import resolve_or_create_ticket
        from tasksentry.telecom.runner import TelecomBatchRunner

        ticket = resolve_or_create_ticket(ticket_id)
        runner = TelecomBatchRunner(
            enable_llm_reasoning=True,
            enable_self_healing=enable_self_healing,
        )
        res = runner.run_ticket(ticket, enable_self_healing=enable_self_healing)
        return {
            "ticket_id": res.ticket_id,
            "category": res.category,
            "status": res.status,
            "rca_driver": res.rca_driver,
            "escalation_team": res.escalation_team,
            "self_healing_applied": res.self_healing_applied,
            "self_healing_action": res.self_healing_action,
            "compliance_score": res.compliance_score,
            "3gpp_brain_analysis": res.llm_analysis,
            "steps_trace": [
                {
                    "step": s.step_number,
                    "title": s.title,
                    "status": s.status,
                    "stdout": s.stdout,
                    "subissue": s.subissue_detected,
                    "escalate_to": s.escalate_to,
                }
                for s in res.steps_executed
            ],
            "audit_receipt": res.audit_receipt_hash,
        }

    def handle_inspect(ticket_id: str) -> dict[str, Any]:
        from tasksentry.telecom.loader import resolve_or_create_ticket

        ticket = resolve_or_create_ticket(ticket_id)
        return {
            "ticket_id": ticket.id,
            "metadata": ticket.metadata.model_dump(),
            "problem_category": ticket.sop.problem_category,
            "sop_steps": [
                {
                    "step": s.step_number,
                    "title": s.title,
                    "commands": s.commands,
                    "escalate_to": s.escalate_to,
                    "stop_on_fail": s.stop_on_fail,
                }
                for s in ticket.sop.steps
            ],
            "verification_criteria": ticket.sop.verification_criteria,
        }

    def handle_list(limit: int = 5, failure_type: str = "") -> dict[str, Any]:
        from tasksentry.telecom.loader import filter_tickets, load_tickets

        if failure_type:
            tickets = filter_tickets(failure_type=failure_type, limit=limit)
        else:
            tickets = load_tickets(limit=limit)

        return {
            "count": len(tickets),
            "tickets": [
                {
                    "id": t.id,
                    "gnb_id": t.metadata.gnb_id,
                    "du_id": t.metadata.du_id,
                    "cell_id": t.metadata.cell_id,
                    "cluster": t.metadata.prefecture,
                    "failure_type": t.metadata.failure_type,
                    "oper_status": t.metadata.oper_status,
                }
                for t in tickets
            ],
        }

    return [
        Tool(
            name="telecom_solve_ticket",
            description=(
                "Executes Macro-Graph 3GPP SOP and autonomous self-healing on any 5G RAN ticket. "
                "Returns the root cause analysis (RCA), escalation team, trace, and audit receipt."
            ),
            callable=handle_solve,
            input_model=TelecomSolveArgs,
            risk="read",
            idempotent=True,
            timeout_seconds=30.0,
        ),
        Tool(
            name="telecom_inspect_ticket",
            description=(
                "Inspects 5G RAN ticket metadata, gNB/DU/Cell parameters, and the 6-step SOP."
            ),
            callable=handle_inspect,
            input_model=TelecomInspectArgs,
            risk="read",
            idempotent=True,
            timeout_seconds=10.0,
        ),
        Tool(
            name="telecom_list_tickets",
            description="Lists available production 5G RAN tickets from the 3,813 dataset.",
            callable=handle_list,
            input_model=TelecomListArgs,
            risk="read",
            idempotent=True,
            timeout_seconds=10.0,
        ),
    ]
