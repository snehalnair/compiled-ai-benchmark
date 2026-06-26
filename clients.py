"""Unified model-call interface with token + cost accounting.

Two backends:
  - frontier: the Anthropic SDK (Claude). Claude is ALWAYS called through the
    official `anthropic` package — never an OpenAI-compatible shim.
  - open:     an OpenAI-compatible endpoint (your hosted open-weight provider).
              This is the standard way to call open models — it is not a Claude shim.

Both return Result(text, usage), where usage carries token counts and USD cost
computed from the pinned price table in config.py.
"""
from dataclasses import dataclass
import time
import config


@dataclass
class UsageRecord:
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_s: float = 0.0


@dataclass
class Result:
    text: str
    usage: UsageRecord


def _cost(model, in_tok, out_tok):
    p_in, p_out = config.price_for(model)
    return in_tok * p_in + out_tok * p_out


# ---------- Frontier (Anthropic) ----------
_anthropic_client = None


def _anthropic():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic
        _anthropic_client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    return _anthropic_client


def call_frontier(system, user, *, model=None, thinking=False, max_tokens=512, json_schema=None):
    """One frontier call. thinking=True → adaptive thinking + high effort (the
    'naive expensive' mode). thinking=False → thinking off; if json_schema is given,
    structured outputs force clean JSON so we measure extraction cost, not reasoning."""
    model = model or config.FRONTIER_MODEL
    client = _anthropic()
    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    if thinking:
        kwargs["thinking"] = {"type": "adaptive"}
        kwargs["output_config"] = {"effort": "high"}
    else:
        kwargs["thinking"] = {"type": "disabled"}
        if json_schema is not None:
            kwargs["output_config"] = {"format": {"type": "json_schema", "schema": json_schema}}
    t0 = time.perf_counter()
    resp = client.messages.create(**kwargs)
    dt = time.perf_counter() - t0
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    u = resp.usage
    usage = UsageRecord(model, u.input_tokens, u.output_tokens,
                        _cost(model, u.input_tokens, u.output_tokens), dt)
    return Result(text, usage)


# ---------- Open-weight (OpenAI-compatible) ----------
_open_client = None


def _open():
    global _open_client
    if _open_client is None:
        from openai import OpenAI
        _open_client = OpenAI(base_url=config.OPEN_BASE_URL, api_key=config.OPEN_API_KEY)
    return _open_client


def call_open(system, user, *, model=None, max_tokens=512, json_mode=True):
    model = model or config.OPEN_MODEL
    client = _open()
    base = dict(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0,
    )
    resp, last, dt = None, None, 0.0
    for attempt in range(5):
        try:
            kwargs = dict(base)
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            t0 = time.perf_counter()
            resp = client.chat.completions.create(**kwargs)
            dt = time.perf_counter() - t0
            break
        except Exception as e:
            last = e
            try:
                t0 = time.perf_counter()
                resp = client.chat.completions.create(**base)  # retry without response_format
                dt = time.perf_counter() - t0
                break
            except Exception as e2:
                last = e2
                time.sleep(2.0 * (attempt + 1))  # back off transient 429 / 5xx
    if resp is None:
        raise last
    text = resp.choices[0].message.content or ""
    u = resp.usage
    in_tok = getattr(u, "prompt_tokens", 0) or 0
    out_tok = getattr(u, "completion_tokens", 0) or 0
    usage = UsageRecord(model, in_tok, out_tok, _cost(model, in_tok, out_tok), dt)
    return Result(text, usage)
