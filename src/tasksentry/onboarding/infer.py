"""Auto-recognize the format of ONE sample record and extract a structured profile.

Deterministic first (JSON / JSONL / ChatML; finds the list of SOP-like steps anywhere in
the record). If confidence is low and an `llm` callable is supplied (e.g. Ollama
beam:cloud), the LLM proposes a field mapping which is validated against the record.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

TEXT_KEYS = ("action", "text", "step_text", "description", "instruction", "content")
NUM_KEYS = ("step", "step_number", "n", "index", "no", "id")
_SKIP_PREFIX = re.compile(
    r"^(escalate|classify|check|capture|invoke|redeploy|map platform|use|trigger|stop|for|if)\b",
    re.I,
)


@dataclass
class StepInfo:
    number: int
    title: str
    text: str
    commands: list[str] = field(default_factory=list)
    expected_pass: str = ""
    expected_fail: str = ""
    subissue: str = ""
    actions: list[str] = field(default_factory=list)
    escalate: str | None = None
    escalate_documented: bool = False
    stop: bool = False
    mappings: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class RecordProfile:
    format: str
    confidence: float
    record_id: str
    instruction: str
    category: str
    label_hint: str
    entities: dict[str, str]
    attributes: dict[str, str]
    steps: list[StepInfo]
    verification: list[str]
    warnings: list[str] = field(default_factory=list)


def extract_json(text: str) -> dict[str, Any] | None:
    """First JSON object embedded in free text (LLM replies often wrap JSON in prose)."""
    dec = json.JSONDecoder()
    for m in re.finditer(r"\{", text):
        try:
            obj, _ = dec.raw_decode(text[m.start() :])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None


def load_record(raw: Any) -> Any:
    if isinstance(raw, dict | list):
        rec = raw
    else:
        s = str(raw).strip()
        try:
            rec = json.loads(s)
        except json.JSONDecodeError:
            rec = json.loads(s.splitlines()[0])  # JSONL: first record
    if isinstance(rec, dict) and isinstance(rec.get("messages"), list):
        user = next((m.get("content", "") for m in rec["messages"] if m.get("role") == "user"), "")
        asst = next(
            (m.get("content", "") for m in rec["messages"] if m.get("role") == "assistant"), ""
        )
        out: Any = extract_json(asst) if isinstance(asst, str) else asst
        return {
            "id": rec.get("id", ""),
            "instruction": user,
            "output": out or {"text": asst},
            "_chatml": True,
        }
    return rec


def find_steps(obj: Any, path: str = "") -> tuple[str, list[dict[str, Any]]] | None:
    best: tuple[str, list[dict[str, Any]]] | None = None
    if isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj):
        ok = sum(
            1 for x in obj if any(isinstance(x.get(k), str) and len(x[k]) > 20 for k in TEXT_KEYS)
        )
        if ok >= max(1, int(0.6 * len(obj))):
            best = (path, obj)
    kids: list[tuple[str, Any]] = []
    if isinstance(obj, dict):
        kids = [(f"{path}.{k}" if path else k, v) for k, v in obj.items()]
    elif isinstance(obj, list):
        kids = [(f"{path}[{i}]", v) for i, v in enumerate(obj)]
    for p, v in kids:
        sub = find_steps(v, p)
        if sub and (best is None or len(sub[1]) > len(best[1])):
            best = sub
    return best


def parse_step(num: int, text: str) -> StepInfo:
    title = text.split(".", 1)[0].strip()[:120]
    seg = re.search(r"Command\(s\):(.*?)(?:Expected:|$)", text, re.S)
    commands = re.findall(r"'([^']+)'", seg.group(1)) if seg else []
    if not commands:
        commands = re.findall(r"`([^`]+)`", text)
        if not commands and ":" in text:
            after_colon = text.split(":", 1)[1].strip()
            first_cmd = after_colon.split(";")[0].strip()
            if any(
                first_cmd.startswith(w)
                for w in (
                    "ping",
                    "kubectl",
                    "systemctl",
                    "show ",
                    "cat ",
                    "ls ",
                    "curl",
                    "SELECT",
                    "ps ",
                    "df ",
                )
            ):
                commands = [first_cmd]
    ep = re.search(r"PASS:\s*(.*?)\s*FAIL:", text, re.S)
    ef = re.search(r"FAIL:\s*(.*?)(?:\.\s*If it fails:|$)", text, re.S)
    sub = re.search(r"subissue:\s*([^;]+?)\s*(?:;|$)", text)
    subissue_val = sub.group(1).strip() if sub else ""
    if not subissue_val:
        clean_title = re.sub(r"^\d+[\.\s\-]+", "", title).strip()
        if clean_title and not clean_title.lower().startswith("step"):
            subissue_val = f"{clean_title} issue"
        elif ef and ef.group(1).strip():
            subissue_val = ef.group(1).strip()
        elif ":" in text:
            subissue_val = text.split(":", 1)[0].strip()
        else:
            subissue_val = f"step_{num}_anomaly"
    actions = [a.strip(" .") for a in re.findall(r"action:\s*([^;]+?)\s*(?:;|$)", text)]
    esc = re.search(r"escalate:\s*(.+?)\s*(?:;\s*stop\s*$|$)", text, re.S)
    escalate = esc.group(1).strip() if esc else None
    documented = bool(escalate) and not (escalate or "").lower().startswith("unavailable")
    clauses = text.split(";")
    sub_idx = next((i for i, c in enumerate(clauses) if "subissue:" in c), None)
    maps: list[tuple[str, str]] = []
    if sub_idx is not None:
        for c in clauses[sub_idx + 1 :]:
            c = re.sub(r"^\s*action:\s*", "", c)
            c = re.sub(r"^Map failure per KB:\s*", "", c.strip())
            if c.lower().startswith("escalate:") or " to " not in c or _SKIP_PREFIX.match(c):
                continue
            m = re.match(r"^(.+?) to (.+?)[.\s]*$", c)
            if m:
                maps.append((m.group(1).strip(), m.group(2).strip()))
    return StepInfo(
        number=num,
        title=title,
        text=text,
        commands=commands,
        expected_pass=ep.group(1).strip() if ep else "",
        expected_fail=ef.group(1).strip() if ef else "",
        subissue=subissue_val,
        actions=actions,
        escalate=escalate if documented else None,
        escalate_documented=documented,
        stop=bool(re.search(r";\s*stop\s*$", text.strip())),
        mappings=maps if len(maps) >= 3 else [],
    )


def _entities(instruction: str) -> tuple[dict[str, str], dict[str, str]]:
    ents = dict(re.findall(r"\b([a-z]+_id)\s+(\d+)", instruction))
    for key, pat in (
        ("ticket", r"Ticket\s+([^\s:]+):"),
        ("data_center", r"data center\s+([^\s,)]+)"),
        ("cluster", r"(?:prefecture/)?cluster\s+([^\s,)]+)"),
    ):
        m = re.search(pat, instruction)
        if m:
            ents[key] = m.group(1)
    attrs = dict(re.findall(r"'(\w+)':\s*'([^']+)'", instruction))
    return ents, attrs


def profile_record(raw: Any, llm: Callable[[str], str] | None = None) -> RecordProfile:
    rec = load_record(raw)
    warnings: list[str] = []
    if not isinstance(rec, dict):
        raise ValueError("Record must be a JSON object (or JSONL/ChatML line).")
    found = find_steps(rec.get("output", rec))
    instruction = str(rec.get("instruction") or rec.get("input") or rec.get("prompt") or "")
    fmt = "chatml-sop" if rec.get("_chatml") else "instruction-output-sop"
    conf = 0.0
    items: list[dict[str, Any]] = found[1] if found else []
    if items:
        structured = sum(1 for x in items if re.search(r"Expected:|Command\(s\):", json.dumps(x)))
        conf = 0.95 if structured >= max(1, len(items) // 2) and instruction else 0.75
    if conf < 0.6 and llm is not None:
        mapped = _llm_mapping(rec, llm)
        if mapped:
            items, conf, fmt = mapped, 0.7, "llm-mapped"
            warnings.append("format recognized via LLM field mapping")
    if not items:
        out = rec.get("output") if isinstance(rec.get("output"), dict) else {}
        plan = out.get("task_plan") if isinstance(out, dict) else None
        if isinstance(plan, list) and plan:
            items = [{"step": i + 1, "action": str(s)} for i, s in enumerate(plan)]
            conf, fmt = 0.4, "task-plan-only"
            warnings.append("no structured steps found; derived from task_plan (low confidence)")
    if not items:
        for k in (
            "sop_steps",
            "steps",
            "actions",
            "plan",
            "task_plan",
            "procedure",
            "resolution_steps",
            "resolution_step",
            "diagnostic_command",
        ):
            val = rec.get(k)
            if isinstance(val, list) and val:
                items = [
                    {"step": i + 1, "action": x if isinstance(x, str) else json.dumps(x)}
                    for i, x in enumerate(val)
                ]
                conf, fmt = 0.7, f"{k}-list"
                warnings.append(f"derived steps from {k}")
                break
            elif isinstance(val, str) and val.strip():
                items = [{"step": 1, "action": val.strip()}]
                conf, fmt = 0.5, f"{k}-field"
                warnings.append(f"derived step from {k}")
                break
    if not instruction:
        instruction = str(
            rec.get("instruction")
            or rec.get("input")
            or rec.get("prompt")
            or rec.get("description")
            or rec.get("details")
            or rec.get("issue")
            or rec.get("title")
            or ""
        )
    if not items:
        warnings.append("could not recognize step structure; supply more records or enable LLM")
    steps: list[StepInfo] = []
    for i, it in enumerate(items):
        text = max(
            (str(it[k]) for k in TEXT_KEYS if isinstance(it.get(k), str)), key=len, default=""
        )
        num = next((int(it[k]) for k in NUM_KEYS if isinstance(it.get(k), int)), i + 1)
        steps.append(parse_step(num, text))
    ents, attrs = _entities(instruction)
    label = next((v for k, v in attrs.items() if "fail" in k.lower()), "")
    if not label:
        for k in (
            "failure_type",
            "issue",
            "alert_name",
            "error",
            "severity",
            "category",
            "service",
        ):
            val = rec.get(k)
            if isinstance(val, str) and val.strip():
                label = val.strip()
                break
    out_obj = rec.get("output") if isinstance(rec.get("output"), dict) else {}
    ver = out_obj.get("verification", []) if isinstance(out_obj, dict) else []
    return RecordProfile(
        format=fmt,
        confidence=conf,
        record_id=str(rec.get("id", "")),
        instruction=instruction,
        category=str(out_obj.get("problem_category", "")) if isinstance(out_obj, dict) else "",
        label_hint=label,
        entities=ents,
        attributes=attrs,
        steps=steps,
        verification=[str(v) for v in ver] if isinstance(ver, list) else [str(ver)],
        warnings=warnings,
    )


def normalize_record(
    raw: Any,
    llm: Callable[[str], str] | None = None,
    profile: RecordProfile | None = None,
) -> dict[str, Any]:
    """Convert an ordinary JSON object into TaskSentry's agent-record contract."""
    rec = load_record(raw)
    if not isinstance(rec, dict):
        raise ValueError("Record must be a JSON object before normalization.")
    profile = profile or profile_record(rec, llm)
    record_id = next(
        (
            str(rec[key])
            for key in ("id", "record_id", "ticket_id", "case_id", "case", "ticket")
            if rec.get(key) is not None
        ),
        "generated-record",
    )
    instruction = profile.instruction.strip()
    if not instruction:
        instruction = str(
            rec.get("description")
            or rec.get("title")
            or rec.get("question")
            or f"Process customer record {record_id}."
        )
    task_plan = [step.text for step in profile.steps if step.text]
    actions = [
        {
            "step": step.number,
            "action": step.text,
            "commands": step.commands,
            "expected_pass": step.expected_pass,
            "expected_fail": step.expected_fail,
            "escalate": step.escalate,
            "stop": step.stop,
        }
        for step in profile.steps
    ]
    return {
        "id": record_id,
        "instruction": instruction,
        "input": rec,
        "output": {
            "problem_category": profile.category or "unclassified",
            "task_plan": task_plan,
            "actions": actions,
            "verification": profile.verification,
        },
        "_tasksentry": {
            "normalized": True,
            "source_format": profile.format,
            "confidence": profile.confidence,
            "warnings": profile.warnings,
        },
    }


def _llm_mapping(rec: dict[str, Any], llm: Callable[[str], str]) -> list[dict[str, Any]] | None:
    prompt = (
        "You recognize dataset record formats. Given this JSON record, reply ONLY with JSON "
        '{"steps_path": "<dotted path to the list of procedure steps>", '
        '"text_key": "<key holding each step text>"}.\n\nRECORD:\n' + json.dumps(rec)[:6000]
    )
    try:
        hint = extract_json(llm(prompt)) or {}
        node: Any = rec
        for part in str(hint.get("steps_path", "")).split("."):
            node = node[part] if part else node
        key = str(hint.get("text_key", ""))
        if (
            isinstance(node, list)
            and node
            and all(isinstance(x, dict) and isinstance(x.get(key), str) for x in node)
        ):
            return [{"step": i + 1, "action": x[key]} for i, x in enumerate(node)]
    except Exception:
        return None
    return None
