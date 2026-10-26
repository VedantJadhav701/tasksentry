import json
from pathlib import Path

from tasksentry.onboarding import pipeline
from tasksentry.onboarding.infer import profile_record

SAMPLE = (Path(__file__).parent.parent / "webapp" / "sample_ticket.json").read_text()


def test_recognizes_sample_ticket():
    p = profile_record(SAMPLE)
    assert p.format == "instruction-output-sop" and p.confidence >= 0.9
    assert len(p.steps) == 6 and p.label_hint == "softwarefailure"
    assert p.entities["gnb_id"] == "4522435" and p.entities["data_center"] == "TotsukaCDC"
    assert len(p.steps[4].mappings) == 4 and p.steps[0].stop


def test_spec_is_derived():
    a = pipeline.analyze(SAMPLE)
    hyps = a["spec"]["hypotheses"]
    assert {"fronthaul", "administrative"} <= set(hyps) and len(hyps) >= 8
    assert max(a["spec"]["priors"], key=a["spec"]["priors"].get).endswith("software_crash")
    assert a["graph"]["nodes"] and a["graph"]["edges"]


def test_end_to_end_run_and_every_truth():
    spec = pipeline.analyze(SAMPLE)["spec"]
    ok = 0
    for h in spec["hypotheses"]:
        out = pipeline.run(SAMPLE, truth=h, approve_high_risk=True)
        r = out["result"]
        assert r["chain_valid"] and out["events"]
        ok += r["diagnosis"]["hypothesis"] == h
    assert ok == len(spec["hypotheses"])


def test_software_ticket_self_heals():
    out = pipeline.run(SAMPLE)
    assert out["result"]["status"] == "resolved" and out["simulated"]


def test_llm_cannot_lower_risk_and_failure_is_safe():
    base = pipeline.analyze(SAMPLE)["spec"]
    h = next(r["hypothesis"] for r in base["remediations"])

    def low(_p):
        return json.dumps({"risk_overrides": {h: "reversible_write"}})

    assert pipeline.analyze(SAMPLE, low)["spec"]["remediations"][0]["risk"] == "reversible_write"

    def up(_p):
        return json.dumps({"risk_overrides": {h: "system_write"}, "sensitivity_overrides": {}})

    assert pipeline.analyze(SAMPLE, up)["spec"]["remediations"][0]["risk"] == "system_write"

    def boom(_p):
        raise RuntimeError("cloud down")

    s = pipeline.analyze(SAMPLE, boom)["spec"]
    assert s["source"] == "deterministic" and any("unavailable" in n for n in s["notes"])


def test_unknown_format_uses_llm_mapping():
    step1 = (
        "Check link. Command(s): 'ping a'. Expected: PASS: ok. FAIL: down. "
        "If it fails: subissue: link down; action: restart link.; escalate: NetOps"
    )
    step2 = (
        "Check disk. Command(s): 'df'. Expected: PASS: ok. FAIL: full. "
        "If it fails: subissue: disk full; action: reset disk.; escalate: Storage"
    )
    rec = {
        "case": "x",
        "plan": {
            "procedure": [
                {"t": step1},
                {"t": step2},
            ]
        },
    }

    def llm(_p):
        return '{"steps_path": "plan.procedure", "text_key": "t"}'

    a = pipeline.analyze(json.dumps(rec), llm)
    assert a["profile"]["format"] == "llm-mapped" and len(a["spec"]["hypotheses"]) == 2


def test_normalize_unstructured_json_to_agent_record():
    raw = {
        "ticket_id": "customer-42",
        "description": "Investigate a failed service deployment.",
        "customer": {"region": "eu-west"},
        "events": [{"message": "deployment unavailable"}],
    }

    result = pipeline.normalize(raw)
    normalized = result["normalized_record"]

    assert normalized["id"] == "customer-42"
    assert normalized["instruction"] == raw["description"]
    assert normalized["input"] == raw
    assert normalized["_tasksentry"]["normalized"] is True
    assert normalized["output"]["problem_category"] == "unclassified"
