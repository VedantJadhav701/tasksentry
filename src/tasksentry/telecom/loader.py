"""Dataset loader and indexer for 5G RAN ticket logs."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterator
from pathlib import Path

from tasksentry.telecom.models import (
    TelecomSOP,
    TelecomStep,
    TelecomTicket,
    TelecomTicketMetadata,
)

DEFAULT_DATASET_PATH = "ran_5g_logs_resolution_sft_chatml_train.jsonl"


def create_standard_sop(failure_type: str = "softwarefailure") -> TelecomSOP:
    """Generate the standard 6-step 3GPP RAN troubleshooting SOP."""
    step1_raw = (
        "DU Reachability. From NOC / jump server, verify DU/NGDU management reachability. "
        "Command(s): 'ping6 <DU_MGMT_IP> -c 4'. Expected: PASS: 0% packet loss / DU reachable. "
        "FAIL: 100% packet loss. If it fails: subissue: Host unreachable; "
        "action: Check BMC reachability.; escalate: Cloud / RCP / Field or IP team; stop"
    )
    step2_raw = (
        "Kubernetes Pods Check. Inside DU/NGDU, check DU software health and pods. "
        "Command(s): 'kubectl get pods -A'; 'kubectl get pods -o wide | grep -i <GNB_DU>'. "
        "Expected: PASS: All DU pods Running. FAIL: CrashLoopBackOff or OOMKilled. "
        "If it fails: subissue: DU software pod crash/missing; "
        "action: Redeploy DU apps or escalate to DU Software / L2.; escalate: DU Software / L2"
    )
    step3_raw = (
        "Cell State and ORU State Check. Inside master confd pod, validate cell operational state. "
        "Command(s): 'cd ASN_log_collection_script/'; "
        "'sh ConfdPodCli.sh duapp-<GNB_DU>-nrconfd-01'; "
        "'show nr-cell'; 'show rumgr-state'. "
        "Expected: PASS: NRCELL_DU_ACTIVE, RU_TIMING_LOCKED, DU-F1C complete/connected. "
        "FAIL: NRCELL_DU_IDLE, RU_WAIT_FOR_CALL_HOME, or DU-F1C down. "
        "If it fails: subissue: State indicates fronthaul/timing/admin/midhaul path; "
        "action: Map failure per KB decision thinking."
    )
    step4_raw = (
        "F1C / CU Path Check. Inside confd CLI, confirm whether cell down is related to DU-CU/F1C. "
        "Command(s): 'show du-f1c'; 'show nr-cell'; 'show nr-sector-carrier'. "
        "Expected: PASS: DU-F1C connected. FAIL: DU-F1C down. "
        "If it fails: subissue: Midhaul/CU path down; "
        "action: Escalate to IP/CU/Core team.; escalate: IP/CU/Core team (depending on evidence)"
    )
    step5_raw = (
        "Alarm Correlation. Check notifmgr.log for first alarm in sequence. "
        "Command(s): 'cat /var/log/ani/notifmgr.log | grep -E \"notifAniRuConnectivityFailure\"'. "
        "Expected: PASS: Identify root-cause alarm triggering outage."
    )
    step6_raw = (
        "Platform Hardware & Snapshot Check. Inside DU OS, verify sysmon reboot and snapshots. "
        "Command(s): 'cat /var/log/arc/sysmon/sysmonRebootInfo.txt'; 'ls -l /rs_obsrv/'. "
        "Expected: PASS: No reboot or snapshot issues. FAIL: Hardware issues found. "
        "If it fails: subissue: Platform hardware reboot; "
        "action: Escalate to Platform/Hardware team.; escalate: Platform / Hardware team"
    )
    return TelecomSOP(
        problem_category=f"Telecom RAN L2 - {failure_type} / aniCellDown",
        task_plan=[
            "1. DU Reachability",
            "2. Kubernetes Pods Check",
            "3. Cell State and ORU State Check",
            "4. F1C / CU Path Check",
            "5. Alarm Correlation",
            "6. Platform Hardware & Snapshot Check",
        ],
        steps=[
            TelecomStep.parse_raw_action(1, step1_raw),
            TelecomStep.parse_raw_action(2, step2_raw),
            TelecomStep.parse_raw_action(3, step3_raw),
            TelecomStep.parse_raw_action(4, step4_raw),
            TelecomStep.parse_raw_action(5, step5_raw),
            TelecomStep.parse_raw_action(6, step6_raw),
        ],
        verification_criteria=["Cell state NRCELL_DU_ACTIVE", "RU_TIMING_LOCKED"],
        next_step_if_failed=["Escalate to specialized engineering tier"],
    )


def resolve_or_create_ticket(ticket_input: str, path: str = DEFAULT_DATASET_PATH) -> TelecomTicket:
    """Find a ticket by ID in dataset or dynamically construct one from text/alert."""
    cleaned = ticket_input.strip()
    if not cleaned:
        cleaned = "tsd_000001"

    # 1. Exact or partial ticket ID match from dataset
    existing = get_ticket_by_id(cleaned, path)
    if existing:
        return existing

    # 2. Extract ticket token like 'tsd_000002' or 'RAE...' embedded in text
    token_match = re.search(r"\b(tsd_\d{6}|RAE[A-Za-z0-9_\-]+)\b", cleaned, re.IGNORECASE)
    if token_match:
        found = get_ticket_by_id(token_match.group(1), path)
        if found:
            return found

    # 3. Dynamic ticket generation from user instruction / query
    meta = TelecomTicketMetadata.from_instruction(cleaned)
    # Infer failure type from text keywords if not explicitly matched
    if not meta.failure_type:
        text_lower = cleaned.lower()
        if "midhaul" in text_lower:
            meta.failure_type = "midhaulfailure"
        elif "timing" in text_lower or "ptp" in text_lower or "sync" in text_lower:
            meta.failure_type = "notifAniTimingUnlocked"
        elif "fronthaul" in text_lower or "m-plane" in text_lower or "mplane" in text_lower:
            meta.failure_type = "notifAniRuConnectivityFailure"
        elif "admin" in text_lower or "locked" in text_lower:
            meta.failure_type = "administrative-locked"
        else:
            meta.failure_type = "softwarefailure"

    if not meta.ticket_id:
        meta.ticket_id = f"tsd_custom_{uuid.uuid4().hex[:6]}"
    if meta.gnb_id is None:
        meta.gnb_id = 9022401
    if meta.du_id is None:
        meta.du_id = 1
    if meta.cell_id is None:
        meta.cell_id = 100
    if not meta.datacenter:
        meta.datacenter = "tokyo01rdc"
    if not meta.prefecture:
        meta.prefecture = "TOKYO-TO"

    sop = create_standard_sop(meta.failure_type)
    return TelecomTicket(
        id=meta.ticket_id,
        instruction=cleaned,
        metadata=meta,
        sop=sop,
    )


def iter_tickets(path: str = DEFAULT_DATASET_PATH) -> Iterator[TelecomTicket]:
    """Stream tickets from the JSONL dataset one by one."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Dataset file not found at: {path}")

    with file_path.open("r", encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if not line_str:
                continue
            data = json.loads(line_str)
            yield TelecomTicket.from_dict(data)


def load_tickets(path: str = DEFAULT_DATASET_PATH, limit: int | None = None) -> list[TelecomTicket]:
    """Load tickets up to an optional limit."""
    if not Path(path).exists():
        return []
    tickets: list[TelecomTicket] = []
    for t in iter_tickets(path):
        tickets.append(t)
        if limit is not None and len(tickets) >= limit:
            break
    return tickets


def get_ticket_by_id(ticket_id: str, path: str = DEFAULT_DATASET_PATH) -> TelecomTicket | None:
    """Retrieve a single ticket by its ID (e.g. 'tsd_000001')."""
    if not Path(path).exists():
        return None
    target = ticket_id.lower().strip()
    for t in iter_tickets(path):
        if t.id.lower() == target or target in t.metadata.ticket_id.lower():
            return t
    return None


def filter_tickets(
    path: str = DEFAULT_DATASET_PATH,
    category: str | None = None,
    failure_type: str | None = None,
    datacenter: str | None = None,
    limit: int = 20,
) -> list[TelecomTicket]:
    """Filter tickets by failure category, datacenter, or failure type."""
    if not Path(path).exists():
        return []
    results: list[TelecomTicket] = []
    for t in iter_tickets(path):
        if category and category.lower() not in t.sop.problem_category.lower():
            continue
        if failure_type and failure_type.lower() not in t.metadata.failure_type.lower():
            continue
        if datacenter and datacenter.lower() not in t.metadata.datacenter.lower():
            continue
        results.append(t)
        if len(results) >= limit:
            break
    return results


class TelecomDatasetLoader:
    """Convenience loader class for 5G RAN tickets."""

    def __init__(self, path: str = DEFAULT_DATASET_PATH) -> None:
        self.path = path

    def iter_all(self) -> Iterator[TelecomTicket]:
        return iter_tickets(self.path)

    def load(self, limit: int | None = None) -> list[TelecomTicket]:
        return load_tickets(self.path, limit=limit)

    def get(self, ticket_id: str) -> TelecomTicket | None:
        return get_ticket_by_id(ticket_id, self.path)

    def resolve_or_create(self, ticket_input: str) -> TelecomTicket:
        return resolve_or_create_ticket(ticket_input, self.path)

    def filter(
        self,
        category: str | None = None,
        failure_type: str | None = None,
        datacenter: str | None = None,
        limit: int = 20,
    ) -> list[TelecomTicket]:
        return filter_tickets(
            self.path,
            category=category,
            failure_type=failure_type,
            datacenter=datacenter,
            limit=limit,
        )
