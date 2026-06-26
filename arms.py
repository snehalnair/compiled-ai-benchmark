"""Experimental arms — fully task-driven (prompt + schema built from the task's
instruction, fields, and optional label enum). Works for extraction and classification.

A — Frontier 'naive': opus, adaptive thinking + high effort, free-form (expensive/un-tuned).
B — Frontier single-shot (optimized): opus, thinking off, structured-output JSON (the bar).
D — Compiled / open-weight: open model, JSON-instructed (the cheap arm).
R — Routed cascade (presence gate): run D; escalate to B if unparseable or a required
    field is missing. (The disagreement-gate router lives in sweep.py.)

Each arm returns (predicted_dict, [UsageRecord, ...], route ∈ {frontier,open,escalated}).
"""
import clients
import scoring


def _system(task):
    parts = [task.instruction.strip(),
             "Return ONLY a JSON object with exactly these keys: " + ", ".join(task.fields) + "."]
    if task.enum:
        for f, opts in task.enum.items():
            parts.append(f'For "{f}", choose exactly one of: ' + ", ".join(opts) + ".")
    parts.append("Output JSON only — no prose.")
    return " ".join(p for p in parts if p)


def _schema(task):
    props = {}
    for k in task.fields:
        if task.enum and k in task.enum:
            props[k] = {"type": "string", "enum": task.enum[k]}
        else:
            props[k] = {"type": ["string", "number", "null"]}
    return {"type": "object", "properties": props, "required": task.fields,
            "additionalProperties": False}


def _user(doc_text):
    return f"Document:\n\n{doc_text}\n\nReturn the JSON object now."


def arm_A(doc_text, task):
    r = clients.call_frontier(_system(task), _user(doc_text), thinking=True, max_tokens=2048)
    return scoring.extract_json(r.text), [r.usage], "frontier"


def arm_B(doc_text, task):
    r = clients.call_frontier(_system(task), _user(doc_text), thinking=False,
                              max_tokens=512, json_schema=_schema(task))
    return scoring.extract_json(r.text), [r.usage], "frontier"


def arm_D(doc_text, task):
    r = clients.call_open(_system(task), _user(doc_text), max_tokens=512)
    return scoring.extract_json(r.text), [r.usage], "open"


def arm_R(doc_text, task):
    r_open = clients.call_open(_system(task), _user(doc_text), max_tokens=512)
    pred = scoring.extract_json(r_open.text)
    if pred is None or scoring.missing_required(pred, task.required_fields):
        r_fr = clients.call_frontier(_system(task), _user(doc_text), thinking=False,
                                     max_tokens=512, json_schema=_schema(task))
        return scoring.extract_json(r_fr.text), [r_open.usage, r_fr.usage], "escalated"
    return pred, [r_open.usage], "open"


ARMS = {
    "A_frontier_naive": arm_A,
    "B_frontier_singleshot": arm_B,
    "D_compiled_open": arm_D,
    "R_routed_cascade": arm_R,
}
