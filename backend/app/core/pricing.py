from __future__ import annotations

from typing import NotRequired, TypedDict


class ModelPricing(TypedDict):
    input_per_1m: float | None
    output_per_1m: float | None
    currency: NotRequired[str]
    source: NotRequired[str]
    updated_at: NotRequired[str]


MODEL_PRICING: dict[tuple[str, str], ModelPricing] = {
    ("groq", "openai/gpt-oss-120b"): {
        "input_per_1m": 0.15,
        "output_per_1m": 0.60,
        "currency": "USD",
        "source": "https://console.groq.com/docs/models",
        "updated_at": "2026-10-10",
    },
}


def estimate_llm_cost_usd(
    *,
    provider: str,
    model: str,
    prompt_tokens: int | None,
    output_tokens: int | None,
) -> float | None:
    pricing = MODEL_PRICING.get((provider, model)) or MODEL_PRICING.get((provider, "*"))
    if pricing is None:
        return None
    input_price = pricing.get("input_per_1m")
    output_price = pricing.get("output_per_1m")
    if input_price is None or output_price is None or prompt_tokens is None or output_tokens is None:
        return None
    return round((prompt_tokens / 1_000_000 * input_price) + (output_tokens / 1_000_000 * output_price), 8)
