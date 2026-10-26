"""Unit and integration tests for Telecom 5G RAN ticket troubleshooting harness."""

from __future__ import annotations

import json
from pathlib import Path

from tasksentry.telecom.agent import TelecomAgent
from tasksentry.telecom.graph import TelecomSOPGraph
from tasksentry.telecom.models import (
    TelecomSOP,
    TelecomStep,
    TelecomTicket,
    TelecomTicketMetadata,
)
from tasksentry.telecom.runner import TelecomBatchRunner
from tasksentry.telecom.tools import (
    TelecomSimulationState,
    create_telecom_tools,
)

SAMPLE_INSTRUCTION = (
    "Ticket RAE25A3002395-10047-aniCellDown-aniCellDown-shiga01rdc: "
    "(gnb_id 9022434, du_id 8, cell_id 30, data center shiga01rdc, prefecture/cluster SHIGA-KEN) "
    "is reporting: {'aniCellLastFailure': 'midhaulfailure', 'OperStatus': 'down'}. "
    "How do I troubleshoot and resolve this issue?"
)

SAMPLE_STEP_1_ACTION = (
    "DU Reachability. From NOC / jump server, verify DU/NGDU management reachability. "
    "Command(s): 'ping6 <DU_MGMT_IP> -c 4'. Expected: PASS: 0% packet loss / DU reachable. "
    "FAIL: 100% packet loss. If it fails: subissue: Host unreachable; "
    "action: Check BMC reachability.; escalate: Cloud / RCP / Field or IP team; stop"
)

SAMPLE_STEP_2_ACTION = (
    "Kubernetes Pods Check. Inside DU/NGDU, check DU software health and pods. "
    "Command(s): 'kubectl get pods -A'; 'kubectl get pods -o wide | grep -i <GNB_DU>'. "
    "Expected: PASS: All DU pods Running. FAIL: CrashLoopBackOff or OOMKilled. "
    "If it fails: subissue: DU software pod crash/missing; "
    "action: Redeploy DU apps or escalate to DU Software / L2.; escalate: DU Software / L2"
)

SAMPLE_STEP_3_ACTION = (
    "Cell State and ORU State Check. Inside master confd pod, validate cell operational state. "
    "Command(s): 'cd ASN_log_collection_script/'; 'sh ConfdPodCli.sh duapp-<GNB_DU>-nrconfd-01'; "
    "'show nr-cell'; 'show rumgr-state'. "
    "Expected: PASS: NRCELL_DU_ACTIVE, RU_TIMING_LOCKED, DU-F1C complete/connected. "
    "FAIL: NRCELL_DU_IDLE, RU_WAIT_FOR_CALL_HOME, or DU-F1C down. "
    "If it fails: subissue: State indicates fronthaul/timing/admin/midhaul path; "
    "action: Map failure per KB decision thinking."
)

SAMPLE_STEP_4_ACTION = (
    "F1C / CU Path Check. Inside confd CLI, confirm whether cell down is related to DU-CU/F1C. "
    "Command(s): 'show du-f1c'; 'show nr-cell'; 'show nr-sector-carrier'. "
    "Expected: PASS: DU-F1C connected. FAIL: DU-F1C down. "
    "If it fails: subissue: Midhaul/CU path down; "
    "action: Escalate to IP/CU/Core team.; escalate: IP/CU/Core team (depending on evidence)"
)


def test_metadata_parsing() -> None:
    meta = TelecomTicketMetadata.from_instruction(SAMPLE_INSTRUCTION)
    assert meta.gnb_id == 9022434
    assert meta.du_id == 8
    assert meta.cell_id == 30
    assert meta.datacenter == "shiga01rdc"
    assert meta.cluster == "SHIGA-KEN"
    assert meta.failure_type == "midhaulfailure"
    assert meta.oper_status == "down"


def test_step_parsing() -> None:
    step1 = TelecomStep.parse_raw_action(1, SAMPLE_STEP_1_ACTION)
    assert step1.step_number == 1
    assert "DU Reachability" in step1.title
    assert "ping6 <DU_MGMT_IP> -c 4" in step1.commands
    assert step1.escalate_to == "Cloud / RCP / Field or IP team"
    assert step1.stop_on_fail is True

    step2 = TelecomStep.parse_raw_action(2, SAMPLE_STEP_2_ACTION)
    assert step2.step_number == 2
    assert "Kubernetes Pods Check" in step2.title
    assert "kubectl get pods -A" in step2.commands
    assert step2.escalate_to == "DU Software / L2"
    assert step2.stop_on_fail is False


def test_sop_graph_construction() -> None:
    meta = TelecomTicketMetadata.from_instruction(SAMPLE_INSTRUCTION)
    sop = TelecomSOP(
        problem_category="Telecom RAN L2 - midhaulfailure / aniCellDown",
        steps=[
            TelecomStep.parse_raw_action(1, SAMPLE_STEP_1_ACTION),
            TelecomStep.parse_raw_action(2, SAMPLE_STEP_2_ACTION),
        ],
    )
    ticket = TelecomTicket(
        id="test_sop",
        instruction=SAMPLE_INSTRUCTION,
        metadata=meta,
        sop=sop,
    )

    graph = TelecomSOPGraph(ticket)
    assert "node_step_1" in graph.nodes
    assert "node_step_2" in graph.nodes
    assert "node_escalation" in graph.nodes
    assert "node_resolved" in graph.nodes
    assert graph.entry_node_id == "node_step_1"

    node1 = graph.nodes["node_step_1"]
    assert "DU Reachability" in node1.title
    assert node1.step_number == 1

    # PASS advances to step 2
    from tasksentry.telecom.graph import NodeEvaluationResult

    pass_res = NodeEvaluationResult(status="PASS", stdout="0% loss")
    next_node = graph.step_next("node_step_1", pass_res)
    assert next_node == "node_step_2"

    # FAIL routes to escalation
    fail_res = NodeEvaluationResult(status="FAIL", stdout="100% loss")
    esc_node = graph.step_next("node_step_1", fail_res)
    assert esc_node == "node_escalation"


def test_telecom_tools() -> None:
    sim = TelecomSimulationState(
        host_reachable=True,
        crashed_pods=[],
        cell_active=False,
        f1c_connected=False,
    )
    tools = create_telecom_tools(sim)
    tools_by_name = {t.name: t for t in tools}

    assert "telecom_ping" in tools_by_name
    assert "telecom_k8s_pods" in tools_by_name
    assert "telecom_confd_cli" in tools_by_name
    assert "telecom_redeploy_pod" in tools_by_name
    assert "telecom_ipmi_power_cycle" in tools_by_name

    ping_res = tools_by_name["telecom_ping"].callable(host="2001:db8::1", count=4)
    assert ping_res["status"] == "PASS"
    assert "0% packet loss" in ping_res["output"]

    k8s_res = tools_by_name["telecom_k8s_pods"].callable(namespace="all")
    assert k8s_res["status"] == "PASS"
    assert "Running" in k8s_res["output"]

    confd_res = tools_by_name["telecom_confd_cli"].callable(
        service_ip="127.0.0.1", command="show nr-cell"
    )
    assert confd_res["status"] == "FAIL"
    assert "NRCELL_DU_IDLE" in confd_res["output"]


def test_telecom_agent_midhaul_escalation() -> None:
    meta = TelecomTicketMetadata.from_instruction(SAMPLE_INSTRUCTION)
    sop = TelecomSOP(
        problem_category="Telecom RAN L2 - midhaulfailure / aniCellDown",
        task_plan=["Step 1", "Step 2", "Step 3", "Step 4"],
        steps=[
            TelecomStep.parse_raw_action(1, SAMPLE_STEP_1_ACTION),
            TelecomStep.parse_raw_action(2, SAMPLE_STEP_2_ACTION),
            TelecomStep.parse_raw_action(3, SAMPLE_STEP_3_ACTION),
            TelecomStep.parse_raw_action(4, SAMPLE_STEP_4_ACTION),
        ],
    )
    ticket = TelecomTicket(
        id="tsd_000001",
        instruction=SAMPLE_INSTRUCTION,
        metadata=meta,
        sop=sop,
    )

    agent = TelecomAgent()
    result = agent.resolve_ticket(ticket)

    assert result.status == "escalated"
    assert result.rca_driver == "midhaulfailure"
    assert "IP/CU/Core" in str(result.escalation_team)
    assert result.compliance_score == 1.0
    assert result.audit_receipt_hash.startswith("ts-tel-")
    assert len(result.steps_executed) >= 3


def test_telecom_agent_crashloop_escalation() -> None:
    sim = TelecomSimulationState(
        host_reachable=True,
        crashed_pods=["duapp-nrconfd CrashLoopBackOff"],
    )
    meta = TelecomTicketMetadata(
        ticket_id="test_crash",
        gnb_id="999",
        du_id="1",
        cell_id="10",
        datacenter="tokyo01",
        cluster="TOKYO",
        failure_type="softwarefailure",
        oper_status="down",
    )
    sop = TelecomSOP(
        problem_category="Telecom RAN L2 - softwarefailure",
        steps=[
            TelecomStep.parse_raw_action(1, SAMPLE_STEP_1_ACTION),
            TelecomStep.parse_raw_action(2, SAMPLE_STEP_2_ACTION),
        ],
    )
    ticket = TelecomTicket(
        id="test_crash",
        instruction="Software failure ticket",
        metadata=meta,
        sop=sop,
    )

    agent = TelecomAgent(sim_state=sim, enable_self_healing=False)
    result = agent.resolve_ticket(ticket)

    assert result.status == "escalated"
    assert "DU Software / L2" in str(result.escalation_team)
    assert len(result.steps_executed) == 2


def test_telecom_agent_crashloop_self_healing() -> None:
    sim = TelecomSimulationState(
        host_reachable=True,
        crashed_pods=["duapp-nrconfd-01 (CrashLoopBackOff)"],
    )
    meta = TelecomTicketMetadata(
        ticket_id="test_heal_crash",
        gnb_id="999",
        du_id="1",
        cell_id="10",
        datacenter="tokyo01",
        cluster="TOKYO",
        failure_type="softwarefailure",
        oper_status="down",
    )
    sop = TelecomSOP(
        problem_category="Telecom RAN L2 - softwarefailure",
        steps=[
            TelecomStep.parse_raw_action(1, SAMPLE_STEP_1_ACTION),
            TelecomStep.parse_raw_action(2, SAMPLE_STEP_2_ACTION),
        ],
    )
    ticket = TelecomTicket(
        id="test_heal_crash",
        instruction="Software failure ticket with self healing",
        metadata=meta,
        sop=sop,
    )

    agent = TelecomAgent(sim_state=sim, enable_self_healing=True)
    result = agent.resolve_ticket(ticket)

    assert result.status == "resolved"
    assert result.self_healing_applied is True
    assert "redeploy" in str(result.self_healing_action).lower()
    assert result.verification_passed is True
    assert any("Self-Healing" in s.title for s in result.steps_executed)


def test_telecom_agent_admin_lock_self_healing() -> None:
    sim = TelecomSimulationState(
        host_reachable=True,
        cell_active=False,
        admin_state="LOCKED",
    )
    meta = TelecomTicketMetadata(
        ticket_id="test_admin_lock",
        gnb_id="888",
        du_id="2",
        cell_id="20",
        datacenter="osaka01",
        cluster="OSAKA",
        failure_type="administrative-locked",
        oper_status="down",
    )
    sop = TelecomSOP(
        problem_category="Telecom RAN L2 - administrative-locked",
        steps=[
            TelecomStep.parse_raw_action(1, SAMPLE_STEP_1_ACTION),
            TelecomStep.parse_raw_action(3, SAMPLE_STEP_3_ACTION),
        ],
    )
    ticket = TelecomTicket(
        id="test_admin_lock",
        instruction="Admin lock ticket with self healing",
        metadata=meta,
        sop=sop,
    )

    agent = TelecomAgent(sim_state=sim, enable_self_healing=True)
    result = agent.resolve_ticket(ticket)

    assert result.status == "resolved"
    assert result.self_healing_applied is True
    assert "unlock" in str(result.self_healing_action).lower()
    assert result.verification_passed is True


def test_telecom_batch_runner_and_metrics(tmp_path: Path) -> None:
    # 1. Test batch execution with a mock JSONL dataset file
    dummy_file = tmp_path / "dummy_dataset.jsonl"
    meta = TelecomTicketMetadata.from_instruction(SAMPLE_INSTRUCTION)
    sop = TelecomSOP(
        problem_category="Telecom RAN L2 - midhaulfailure",
        steps=[
            TelecomStep.parse_raw_action(1, SAMPLE_STEP_1_ACTION),
            TelecomStep.parse_raw_action(4, SAMPLE_STEP_4_ACTION),
        ],
    )
    sample_ticket = TelecomTicket(
        id="tsd_dummy_001",
        instruction=SAMPLE_INSTRUCTION,
        metadata=meta,
        sop=sop,
    )
    with open(dummy_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(sample_ticket.model_dump()) + "\n")

    runner = TelecomBatchRunner(dataset_path=str(dummy_file), max_tickets=3)
    report = runner.run_batch()

    assert report.total_tickets > 0
    assert report.average_compliance_score > 0.0
    assert (
        report.resolved_count + report.escalated_count + report.failed_count == report.total_tickets
    )

    # Test saving report
    output_file = tmp_path / "test_report.json"
    runner.save_report(report, str(output_file))
    assert output_file.exists()

    with open(output_file, encoding="utf-8") as f:
        data = json.load(f)
    assert "total_tickets" in data
    assert "results" in data

    # 2. Test fallback when dataset file does not exist (e.g. CI environments)
    runner_fallback = TelecomBatchRunner(
        dataset_path=str(tmp_path / "nonexistent.jsonl"), max_tickets=2
    )
    fallback_report = runner_fallback.run_batch()
    assert fallback_report.total_tickets == 2


def test_telecom_agent_brain_reasoning() -> None:
    meta = TelecomTicketMetadata.from_instruction(SAMPLE_INSTRUCTION)
    sop = TelecomSOP(
        problem_category="Telecom RAN L2 - midhaulfailure",
        steps=[
            TelecomStep.parse_raw_action(1, SAMPLE_STEP_1_ACTION),
            TelecomStep.parse_raw_action(4, SAMPLE_STEP_4_ACTION),
        ],
    )
    ticket = TelecomTicket(
        id="test_telco_brain",
        instruction=SAMPLE_INSTRUCTION,
        metadata=meta,
        sop=sop,
    )

    agent = TelecomAgent(
        brain_model="telco:latest",
        enable_llm_reasoning=True,
    )
    # Mock brain analysis method to test deterministic output without hitting network
    agent._generate_brain_analysis = (  # type: ignore[assignment]
        lambda ticket, status, rca_driver, escalation_team: (
            f"3GPP RAN Analysis: Root cause is {rca_driver}. Disruption on midhaul Xn-AP interface."
        )
    )

    res = agent.resolve_ticket(ticket)
    assert res.brain_model == "telco:latest"
    assert "3GPP RAN Analysis" in res.llm_analysis
    assert "midhaulfailure" in res.llm_analysis
