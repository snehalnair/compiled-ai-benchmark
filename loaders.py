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


LOADERS = {"synthetic": load_synthetic,
           "invoices_ocr": load_invoices_ocr,
           "support_triage": load_support_triage}
