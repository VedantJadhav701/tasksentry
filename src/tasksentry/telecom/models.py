"""Data models for Telecom 5G RAN ticket troubleshooting, SOP contracts, and execution traces."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TelecomTicketMetadata(BaseModel):
    """Metadata extracted from telecom ticket instruction."""

    model_config = ConfigDict(extra="ignore")

    ticket_id: str = ""
    gnb_id: int | None = None
    du_id: int | None = None
    cell_id: int | None = None
    datacenter: str = ""
    prefecture: str = ""
    failure_type: str = ""  # midhaulfailure, softwarefailure, radiotimingunlock, etc.
    oper_status: str = "down"
    host_ip: str | None = None
    bmc_ip: str | None = None

    @property
    def cluster(self) -> str:
        """Alias for prefecture/cluster."""
        return self.prefecture

    @property
    def failure_alert(self) -> str:
        """Alias for failure_type."""
        return self.failure_type

    @property
    def category(self) -> str:
        """Category description based on failure type."""
        return f"Telecom RAN L2 - {self.failure_type} / aniCellDown"

    @classmethod
    def from_instruction(cls, text: str) -> TelecomTicketMetadata:
        """Parse structured metadata out of a ticket instruction string."""
        ticket_match = re.search(r"Ticket\s+([A-Za-z0-9_\-]+):", text)
        ticket_id = ticket_match.group(1) if ticket_match else ""

        gnb_match = re.search(r"gnb_id\s+(\d+)", text)
        gnb_id = int(gnb_match.group(1)) if gnb_match else None

        du_match = re.search(r"du_id\s+(\d+)", text)
        du_id = int(du_match.group(1)) if du_match else None

        cell_match = re.search(r"cell_id\s+(\d+)", text)
        cell_id = int(cell_match.group(1)) if cell_match else None

        dc_match = re.search(r"data\s+center\s+([A-Za-z0-9_\-]+)", text)
        datacenter = dc_match.group(1) if dc_match else ""

        pref_match = re.search(r"prefecture/cluster\s+([A-Za-z0-9_\-]+)", text)
        prefecture = pref_match.group(1) if pref_match else ""

        fail_match = re.search(r"'aniCellLastFailure':\s*'([^']+)'", text)
        failure_type = fail_match.group(1) if fail_match else ""

        oper_match = re.search(r"'OperStatus':\s*'([^']+)'", text)
        oper_status = oper_match.group(1) if oper_match else "down"

        host_match = re.search(r"Host\s+IP\s+([0-9a-fA-F:]+)", text)
        host_ip = host_match.group(1) if host_match else None

        bmc_match = re.search(r"BMC\s+IP\s+([0-9a-fA-F:]+)", text)
        bmc_ip = bmc_match.group(1) if bmc_match else None

        return cls(
            ticket_id=ticket_id,
            gnb_id=gnb_id,
            du_id=du_id,
            cell_id=cell_id,
            datacenter=datacenter,
            prefecture=prefecture,
            failure_type=failure_type,
            oper_status=oper_status,
            host_ip=host_ip,
            bmc_ip=bmc_ip,
        )


class TelecomStep(BaseModel):
    """An individual SOP step extracted from telecom actions."""

    model_config = ConfigDict(extra="ignore")

    step_number: int
    title: str = ""
    description: str = ""
    commands: list[str] = Field(default_factory=list)
    expected_pass: str = ""
    expected_fail: str = ""
    subissue: str = ""
    remediation_actions: list[str] = Field(default_factory=list)
    escalate_to: str | None = None
    stop_on_fail: bool = False

    @classmethod
    def parse_raw_action(cls, step_num: int, raw_text: str) -> TelecomStep:
        """Parse commands, expected conditions, and failure escalations from action text."""
        # Title is often before the first period
        parts = raw_text.split(".", 1)
        title = parts[0].strip() if parts else f"Step {step_num}"
        desc = parts[1].strip() if len(parts) > 1 else raw_text

        # Extract commands
        cmd_matches = re.findall(r"'([^']+)'", raw_text)
        commands = [c for c in cmd_matches if not c.startswith("PASS") and not c.startswith("FAIL")]

        # Extract expected PASS / FAIL
        expected_pass = ""
        expected_fail = ""
        exp_match = re.search(
            r"Expected:\s*PASS:\s*(.*?)\.\s*FAIL:\s*(.*?)(?:\. If it fails:|$)", raw_text, re.DOTALL
        )
        if exp_match:
            expected_pass = exp_match.group(1).strip()
            expected_fail = exp_match.group(2).strip()

        # Extract subissue
        sub_match = re.search(r"subissue:\s*([^;]+);", raw_text)
        subissue = sub_match.group(1).strip() if sub_match else ""

        # Extract remediation actions
        act_matches = re.findall(r"action:\s*([^;]+);", raw_text)
        remediation_actions = [a.strip() for a in act_matches]

        # Extract escalation
        esc_match = re.search(r"escalate:\s*([^;]+?)(?:;\s*stop|$)", raw_text, re.IGNORECASE)
        escalate_to = esc_match.group(1).strip() if esc_match else None

        stop_on_fail = "; stop" in raw_text.lower() or ";stop" in raw_text.lower()

        return cls(
            step_number=step_num,
            title=title,
            description=desc,
            commands=commands,
            expected_pass=expected_pass,
            expected_fail=expected_fail,
            subissue=subissue,
            remediation_actions=remediation_actions,
            escalate_to=escalate_to,
            stop_on_fail=stop_on_fail,
        )


class TelecomSOP(BaseModel):
    """Structured Standard Operating Procedure plan."""

    model_config = ConfigDict(extra="ignore")

    problem_category: str
    task_plan: list[str] = Field(default_factory=list)
    steps: list[TelecomStep] = Field(default_factory=list)
    verification_criteria: list[str] = Field(default_factory=list)
    next_step_if_failed: list[str] = Field(default_factory=list)


class TelecomTicket(BaseModel):
    """Complete representation of a telecom ticket problem."""

    model_config = ConfigDict(extra="ignore")

    id: str
    instruction: str
    metadata: TelecomTicketMetadata
    sop: TelecomSOP

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TelecomTicket:
        meta = TelecomTicketMetadata.from_instruction(data.get("instruction", ""))
        output_data = data.get("output", {})
        actions_raw = output_data.get("actions", [])
        parsed_steps = [
            TelecomStep.parse_raw_action(a.get("step", idx + 1), a.get("action", ""))
            for idx, a in enumerate(actions_raw)
        ]
        sop = TelecomSOP(
            problem_category=output_data.get("problem_category", ""),
            task_plan=output_data.get("task_plan", []),
            steps=parsed_steps,
            verification_criteria=output_data.get("verification", []),
            next_step_if_failed=output_data.get("next_step_if_failed", []),
        )
        return cls(
            id=data.get("id", ""),
            instruction=data.get("instruction", ""),
            metadata=meta,
            sop=sop,
        )


class StepExecutionRecord(BaseModel):
    """Trace of a single step execution during ticket resolution."""

    model_config = ConfigDict(extra="ignore")

    step_number: int
    title: str
    command_executed: str
    exit_code: int = 0
    stdout: str = ""
    status: str = "PASS"  # PASS, FAIL, BLOCKED, ESCALATED
    subissue_detected: str | None = None
    escalate_to: str | None = None
    duration_seconds: float = 0.0


class TelecomResolutionResult(BaseModel):
    """Final resolution outcome for a telecom ticket."""

    model_config = ConfigDict(extra="ignore")

    ticket_id: str
    category: str
    status: str  # resolved, escalated, failed
    rca_driver: str = ""
    escalation_team: str | None = None
    steps_executed: list[StepExecutionRecord] = Field(default_factory=list)
    verification_passed: bool = False
    compliance_score: float = 1.0  # Percentage of SOP steps followed accurately
    wall_time_seconds: float = 0.0
    tokens_consumed: int = 0
    brain_model: str = "telco:latest"
    llm_analysis: str = ""
    audit_receipt_hash: str = ""
