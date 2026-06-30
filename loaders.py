"""Dataset loaders. Each returns a Task (field schema + instruction + samples) in one
canonical shape, so arms/scoring stay task-agnostic across extraction AND classification.

  synthetic      — 6 hand-written invoices (v0)
  invoices_ocr   — mychen76/invoices-and-receipts_ocr_v1 (HF): OCR text + structured GT
  support_triage — mteb/banking77 (HF): customer messages → 1 of 77 intent labels
                   (classification / ticket routing; tests generality beyond extraction)

Text-only loaders use HuggingFace's datasets-server rows API (no image bytes, no hang).
"""
from dataclasses import dataclass
import ast
import json
import os
import time
import urllib.error
import urllib.request

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
ROWS_API = "https://datasets-server.huggingface.co/rows"

INVOICE_INSTRUCTION = (
    "You extract structured data from invoices. Copy values verbatim from the document. "
    "total_amount is the gross total payable as a number (keep the document's own decimal "
    "format). If a field is absent, use null.")


@dataclass
class Task:
    name: str
    fields: list
    numeric_fields: tuple
    required_fields: list
    samples: list
    instruction: str = ""
    enum: dict = None          # {field: [allowed values]} for classification


def _rows(dataset, split, config="default", offset=0, length=100):
    url = f"{ROWS_API}?dataset={dataset}&config={config}&split={split}&offset={offset}&length={length}"
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
    last = None
    for attempt in range(6):
        try:
            return json.load(urllib.request.urlopen(req, timeout=60)).get("rows", [])
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503):
                time.sleep(2.0 * (attempt + 1))
                continue
            raise
        except Exception as e:
            last = e
            time.sleep(2.0 * (attempt + 1))
    raise last


def load_synthetic(limit=None, seed=0):
    rows = []
    with open(os.path.join(DATA_DIR, "invoices_sample.jsonl")) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if limit:
        rows = rows[:limit]
    return Task("synthetic_invoices",
                ["invoice_number", "invoice_date", "vendor_name", "total_amount", "currency"],
                ("total_amount",), ["invoice_number", "total_amount"], rows,
                instruction=INVOICE_INSTRUCTION)


def load_invoices_ocr(limit=40, seed=0, hard=False):
    samples, offset = [], 0
    while len(samples) < limit:
        batch = _rows("mychen76/invoices-and-receipts_ocr_v1", "train", offset=offset)
        if not batch:
            break
        for item in batch:
            row = item["row"]
            try:
                gt = ast.literal_eval(json.loads(row["parsed_data"])["json"])
                header, summary = gt.get("header", {}), gt.get("summary", {})
                words = json.loads(row["raw_data"]).get("ocr_words")
                if isinstance(words, str):
                    words = ast.literal_eval(words)
                fields = {
                    "invoice_number": header.get("invoice_no"),
                    "invoice_date": header.get("invoice_date"),
                    "total_amount": summary.get("total_gross_worth"),
                    "iban": header.get("iban"),
                    "seller_tax_id": header.get("seller_tax_id"),
                }
                if not fields["invoice_number"] or not fields["total_amount"]:
                    continue
                samples.append({"text": "\n".join(str(w) for w in words), "fields": fields})
                if len(samples) >= limit:
                    break
            except Exception:
                continue
        offset += len(batch)
    score_fields = (["invoice_number", "invoice_date", "total_amount", "iban", "seller_tax_id"]
                    if hard else ["invoice_number", "invoice_date", "total_amount"])
    return Task("invoices_ocr" + ("_hard" if hard else ""), score_fields, ("total_amount",),
                ["invoice_number", "total_amount"], samples, instruction=INVOICE_INSTRUCTION)


def load_support_triage(limit=50, seed=0):
    """Banking77 test split. The split is class-sorted (40 per class), so we scan it
    fully (for all 77 labels) and take an evenly-strided sample that spans the classes
    — deterministic and representative."""
    cache = os.path.join(DATA_DIR, "banking77_test_pool.jsonl")
    pool = []
    if os.path.isfile(cache):
        with open(cache) as f:
            for line in f:
                line = line.strip()
                if line:
                    o = json.loads(line)
                    pool.append((o["text"], o["intent"]))
    else:
        offset = 0
        while offset < 3200:  # full test split ~3080 rows
            batch = _rows("mteb/banking77", "test", offset=offset, length=100)
            if not batch:
                break
            for item in batch:
                row = item["row"]
                if row.get("text") and row.get("label_text"):
                    pool.append((row["text"], row["label_text"]))
            offset += len(batch)
            time.sleep(0.2)  # be gentle with the datasets-server
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(cache, "w") as f:
            for t, lt in pool:
                f.write(json.dumps({"text": t, "intent": lt}) + "\n")
    labels = sorted({lt for _, lt in pool})
    stride = max(1, len(pool) // limit) if pool else 1
    picked = pool[::stride][:limit]
    samples = [{"text": t, "fields": {"intent": lt}} for t, lt in picked]
    instruction = ("You triage customer banking support messages. Read the message and "
                   "classify it as the single best-matching intent.")
    return Task("support_triage", ["intent"], (), ["intent"], samples,
                instruction=instruction, enum={"intent": labels})


def _field_names(fields):
    names = []
    for f in fields or []:
        names.append(f["name"] if isinstance(f, dict) else str(f))
    return names


def _numeric_fields(fields, explicit=()):
    numeric = set(explicit or ())
    for f in fields or []:
        if isinstance(f, dict) and f.get("type") in ("number", "numeric", "money"):
            numeric.add(f["name"])
    return tuple(numeric)


def _enum_fields(fields, explicit=None):
    enum = dict(explicit or {})
    for f in fields or []:
        if isinstance(f, dict) and f.get("enum"):
            enum[f["name"]] = list(f["enum"])
    return enum or None


def load_yaml_task(path, limit=None, seed=0):
    """Load a user-defined task from YAML so new workflows do not require editing
    Python. Sample files are resolved relative to the YAML file.

    Minimal spec:

      name: my_task
      instruction: Extract ...
      fields:
        - name: invoice_number
        - name: total_amount
          type: money
      required_fields: [invoice_number, total_amount]
      samples: data/my_task.jsonl

    Each JSONL row: {"text": "...", "fields": {"invoice_number": "..."}}
    """
    try:
        import yaml
    except ImportError as e:
        raise RuntimeError("YAML task specs require PyYAML. Run: pip install -r requirements.txt") from e

    path = os.path.abspath(path)
    base = os.path.dirname(path)
    with open(path) as f:
        spec = yaml.safe_load(f) or {}

    raw_fields = spec.get("fields") or []
    fields = _field_names(raw_fields)
    if not fields:
        raise ValueError(f"{path}: task spec must define at least one field")

    samples = []
    if spec.get("samples_inline"):
        samples.extend(spec["samples_inline"])
    if spec.get("samples"):
        sample_path = spec["samples"]
        if not os.path.isabs(sample_path):
            sample_path = os.path.join(base, sample_path)
        with open(sample_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    samples.append(json.loads(line))
    if limit:
        samples = samples[:limit]
    if not samples:
        raise ValueError(f"{path}: task spec must provide samples or samples_inline")

    return Task(
        spec.get("name") or os.path.splitext(os.path.basename(path))[0],
        fields,
        _numeric_fields(raw_fields, spec.get("numeric_fields")),
        list(spec.get("required_fields") or fields),
        samples,
        instruction=spec.get("instruction", ""),
        enum=_enum_fields(raw_fields, spec.get("enum")),
    )


# LegalBench judgment-classification tasks (Guha et al.). Loaded from HuggingFace at
# runtime and cached locally; data is NOT redistributed (caches are gitignored).
LEGALBENCH_INSTRUCTIONS = {
    "hearsay": (
        "You are classifying whether a described piece of evidence is hearsay. Hearsay is an "
        "out-of-court statement offered to prove the truth of the matter asserted — not, for "
        "example, one offered only to show its effect on a listener or that it was said at all. "
        "Read the scenario and decide whether it is hearsay."),
    "personal_jurisdiction": (
        "You are deciding whether a U.S. court has personal jurisdiction over the defendant in "
        "the scenario, under the minimum-contacts / purposeful-availment standard. Read the facts "
        "and answer Yes if personal jurisdiction exists, No otherwise."),
    "diversity_1": (
        "You are deciding whether a U.S. federal court has diversity jurisdiction over the case. "
        "Diversity jurisdiction requires BOTH complete diversity of citizenship between all "
        "plaintiffs and all defendants AND an amount in controversy exceeding $75,000. Read the "
        "facts and answer Yes or No."),
}


def _legalbench(config, limit=50, seed=0, labels=("Yes", "No")):
    """Generic LegalBench binary/fixed-label loader (single text field → one `answer` enum)."""
    cache = os.path.join(DATA_DIR, f"legalbench_{config}_test.jsonl")
    pool = []
    if os.path.isfile(cache):
        with open(cache) as f:
            for line in f:
                line = line.strip()
                if line:
                    o = json.loads(line)
                    pool.append((o["text"], o["answer"]))
    else:
        offset = 0
        while offset < 4000:
            batch = _rows("nguha/legalbench", "test", config=config, offset=offset, length=100)
            if not batch:
                break
            for item in batch:
                row = item["row"]
                t, a = row.get("text"), row.get("answer")
                if t and a in labels:
                    pool.append((t, a))
            offset += len(batch)
            time.sleep(0.2)
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(cache, "w") as f:
            for t, a in pool:
                f.write(json.dumps({"text": t, "answer": a}) + "\n")
    samples = [{"text": t, "fields": {"answer": a}} for t, a in pool[:limit]]
    return Task(f"legalbench_{config}", ["answer"], (), ["answer"], samples,
                instruction=LEGALBENCH_INSTRUCTIONS[config], enum={"answer": list(labels)})


def _make_legalbench(cfg):
    return lambda limit=50, seed=0: _legalbench(cfg, limit, seed)


# --- Multiple-choice loader (assembles question + options into one text field, enum A–D).
# One-time unlock for cross-domain breadth: any MMLU subject is a one-line LOADERS entry. ---
MMLU_INSTRUCTION = ("Answer the following multiple-choice question. Respond with the single "
                    "letter (A, B, C, or D) of the best answer.")


def load_mmlu(subject, limit=50, seed=0):
    """MMLU subject as a fixed-enum classification task. Loaded at runtime, cached locally
    (gitignored, not redistributed). Cite MMLU (Hendrycks et al.)."""
    cache = os.path.join(DATA_DIR, f"mmlu_{subject}_test.jsonl")
    letters, pool = "ABCD", []
    if os.path.isfile(cache):
        with open(cache) as f:
            for line in f:
                line = line.strip()
                if line:
                    o = json.loads(line)
                    pool.append((o["text"], o["answer"]))
    else:
        offset = 0
        while offset < 3000:
            batch = _rows("cais/mmlu", "test", config=subject, offset=offset, length=100)
            if not batch:
                break
            for item in batch:
                row = item["row"]
                q, ch, a = row.get("question"), row.get("choices"), row.get("answer")
                if q and isinstance(ch, list) and len(ch) == 4 and isinstance(a, int) and 0 <= a < 4:
                    text = q + "\n" + "\n".join(f"{letters[i]}) {ch[i]}" for i in range(4))
                    pool.append((text, letters[a]))
            offset += len(batch)
            time.sleep(0.2)
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(cache, "w") as f:
            for t, a in pool:
                f.write(json.dumps({"text": t, "answer": a}) + "\n")
    samples = [{"text": t, "fields": {"answer": a}} for t, a in pool[:limit]]
    return Task(f"mmlu_{subject}", ["answer"], (), ["answer"], samples,
                instruction=MMLU_INSTRUCTION, enum={"answer": list("ABCD")})


def _make_mmlu(subject):
    return lambda limit=50, seed=0: load_mmlu(subject, limit, seed)


LOADERS = {"synthetic": load_synthetic,
           "invoices_ocr": load_invoices_ocr,
           "support_triage": load_support_triage,
           "legalbench_hearsay": _make_legalbench("hearsay"),
           "legalbench_personal_jurisdiction": _make_legalbench("personal_jurisdiction"),
           "legalbench_diversity": _make_legalbench("diversity_1"),
           "mmlu_professional_medicine": _make_mmlu("professional_medicine"),
           "mmlu_econometrics": _make_mmlu("econometrics"),
           "mmlu_professional_law": _make_mmlu("professional_law"),
           "mmlu_college_chemistry": _make_mmlu("college_chemistry")}
