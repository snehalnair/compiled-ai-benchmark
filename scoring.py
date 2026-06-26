"""Field-type-aware scoring for invoice extraction against ground truth.

  - numeric fields (e.g. total_amount): compared as parsed money values, so
    "$8,25" (EU), "8.25", "$7,899.99" (US) all normalize correctly.
  - string fields: whitespace/case-normalized exact match.

Reports field_accuracy (soft) and exact_doc (strict — all fields right). The
router's escalation gate (missing_required) is here too.
"""
import json
import re


def extract_json(text):
    """Tolerant JSON extraction: strip fences, parse, else grab the first {...}."""
    if not text:
        return None
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def parse_money(s):
    """Parse a monetary string to float, handling US and EU decimal conventions.
    '$7,899.99'->7899.99 ; '$8,25'->8.25 ; '1.234,56'->1234.56 ; '12500'->12500."""
    s = re.sub(r"[^\d.,-]", "", str(s))
    if not s:
        raise ValueError("no number")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):       # comma is the decimal (EU: 1.234,56)
            s = s.replace(".", "").replace(",", ".")
        else:                                  # dot is the decimal (US: 1,234.56)
            s = s.replace(",", "")
    elif "," in s:
        # only commas: decimal if exactly two trailing digits and no thous-grouping
        if re.search(r",\d{2}$", s) and not re.search(r"\d,\d{3}", s):
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    return float(s)


def _norm_str(v):
    return "" if v is None else " ".join(str(v).strip().lower().split())


def _num_eq(a, b):
    try:
        return abs(parse_money(a) - parse_money(b)) < 0.01
    except Exception:
        return False


def score(predicted, truth, fields, numeric_fields=()):
    pred = predicted or {}
    numeric = set(numeric_fields)
    correct, per_field = 0, {}
    for k in fields:
        ok = _num_eq(pred.get(k), truth.get(k)) if k in numeric \
            else _norm_str(pred.get(k)) == _norm_str(truth.get(k))
        per_field[k] = ok
        correct += int(ok)
    return {"field_accuracy": correct / len(fields),
            "exact_doc": int(correct == len(fields)),
            "per_field": per_field}


def missing_required(predicted, required):
    """Router gate: True if any REQUIRED field is absent/empty → escalate."""
    pred = predicted or {}
    for k in required:
        v = pred.get(k)
        if v is None or str(v).strip() == "":
            return True
    return False


def _field_match(a, b, numeric):
    return _num_eq(a, b) if numeric else _norm_str(a) == _norm_str(b)


def disagreement(p1, p2, fields, numeric_fields=()):
    """Disagreement-gate signal: number of scored fields on which two predictions
    differ. An unparseable prediction counts as maximal disagreement (force escalate)."""
    if p1 is None or p2 is None:
        return len(fields)
    num = set(numeric_fields)
    return sum(0 if _field_match(p1.get(k), p2.get(k), k in num) else 1 for k in fields)
