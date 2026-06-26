"""Central config for the v0 benchmark: models, prices, provider endpoints, router gate.

Prices are pinned to a dated snapshot — bump PRICES_AS_OF whenever you refresh them.
A benchmark with undated prices is worthless in six months.

Frontier (Anthropic), USD per 1M tokens (input / output):
  claude-opus-4-8   $5  / $25
  claude-sonnet-4-6 $3  / $15
  claude-haiku-4-5  $1  / $5
Open-weight prices depend on YOUR hosted provider — set them via env (OPEN_*).
"""
import os


def _load_dotenv():
    """Zero-dependency .env loader. Looks for a .env in this folder, then the
    project root. Real shell env vars always win (we only setdefault)."""
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (os.path.join(here, ".env"), os.path.join(os.path.dirname(here), ".env")):
        if not os.path.isfile(path):
            continue
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("export "):
                        line = line[len("export "):]
                    if "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key, val = key.strip(), val.strip()
                    if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                        val = val[1:-1]
                    os.environ.setdefault(key, val)
        except Exception:
            pass


_load_dotenv()

PRICES_AS_OF = "2026-06-26"

# ---- Frontier (Anthropic) ----
FRONTIER_MODEL = os.environ.get("FRONTIER_MODEL", "claude-opus-4-8")

# ---- Open-weight (OpenAI-compatible endpoint: Together / Fireworks / DeepInfra / OpenRouter / Groq …) ----
OPEN_BASE_URL = os.environ.get("OPEN_BASE_URL", "https://api.together.xyz/v1")
OPEN_MODEL    = os.environ.get("OPEN_MODEL", "Qwen/Qwen2.5-7B-Instruct-Turbo")
OPEN_API_KEY  = (os.environ.get("OPEN_API_KEY")
                 or os.environ.get("OPENROUTER_API_KEY")
                 or os.environ.get("OPENAI_API_KEY", ""))

# Price table: USD per *token* (input, output).
PRICES = {
    "claude-opus-4-8":   (5.0e-6, 25.0e-6),
    "claude-opus-4-7":   (5.0e-6, 25.0e-6),
    "claude-sonnet-4-6": (3.0e-6, 15.0e-6),
    "claude-haiku-4-5":  (1.0e-6,  5.0e-6),
}

# Open-weight price — SET THESE to your provider's real per-1M numbers via env.
# Defaults are placeholders; leaving them will make the cost story fiction.
OPEN_INPUT_PRICE_PER_M  = float(os.environ.get("OPEN_INPUT_PRICE_PER_M",  "0.20"))
OPEN_OUTPUT_PRICE_PER_M = float(os.environ.get("OPEN_OUTPUT_PRICE_PER_M", "0.20"))
PRICES[OPEN_MODEL] = (OPEN_INPUT_PRICE_PER_M / 1e6, OPEN_OUTPUT_PRICE_PER_M / 1e6)

# Second cheap open model — the disagreement-gate router (v1.2) runs both and
# escalates to the frontier only when they disagree. Same OpenRouter endpoint/key.
OPEN_MODEL_2 = os.environ.get("OPEN_MODEL_2", "meta-llama/llama-3.1-8b-instruct")
OPEN2_INPUT_PRICE_PER_M  = float(os.environ.get("OPEN2_INPUT_PRICE_PER_M",  "0.02"))
OPEN2_OUTPUT_PRICE_PER_M = float(os.environ.get("OPEN2_OUTPUT_PRICE_PER_M", "0.03"))
PRICES[OPEN_MODEL_2] = (OPEN2_INPUT_PRICE_PER_M / 1e6, OPEN2_OUTPUT_PRICE_PER_M / 1e6)

# Third cheap open model — completes the 3-model ensemble for the continuous
# confidence gate (v2). Different family (Mistral) for more independent errors.
OPEN_MODEL_3 = os.environ.get("OPEN_MODEL_3", "mistralai/mistral-small-24b-instruct-2501")
OPEN3_INPUT_PRICE_PER_M  = float(os.environ.get("OPEN3_INPUT_PRICE_PER_M",  "0.05"))
OPEN3_OUTPUT_PRICE_PER_M = float(os.environ.get("OPEN3_OUTPUT_PRICE_PER_M", "0.08"))
PRICES[OPEN_MODEL_3] = (OPEN3_INPUT_PRICE_PER_M / 1e6, OPEN3_OUTPUT_PRICE_PER_M / 1e6)


def price_for(model: str):
    if model not in PRICES:
        raise KeyError(f"No price for model {model!r}. Add it to PRICES in config.py.")
    return PRICES[model]


# ---- Archetype: invoice extraction ----
INVOICE_FIELDS = ["invoice_number", "invoice_date", "vendor_name", "total_amount", "currency"]

# ---- Router (arm R) gate ----
# v0 cascade: run the open model, escalate to frontier if the output fails validation
# (unparseable JSON, or a REQUIRED field missing/empty). The escalation strictness IS
# the threshold; widening REQUIRED_FIELDS sends more docs to the frontier. v1 sweeps a
# continuous confidence threshold to trace the full cost–quality Pareto curve.
REQUIRED_FIELDS = ["invoice_number", "total_amount"]
