from __future__ import annotations

from typing import NotRequired, TypedDict


class ModelPricing(TypedDict):
    input_per_1m: float | None
    output_per_1m: float | None
    currency: NotRequired[str]
    source: NotRequired[str]
    updated_at: NotRequired[str]


MODEL_PRICING: dict[tuple[str, str], ModelPricing] = {
    ("openai", "gpt-5.4-mini"): {
        "input_per_1m": 0.75,
        "output_per_1m": 4.50,
        "currency": "USD",
        "source": "https://developers.openai.com/api/docs/models/gpt-5.4-mini",
        "updated_at": "2026-10-17",
    },
}


def estimate_llm_cost_usd(
    *,
    provider: str,
    model: str,
    prompt_tokens: int | None,
    output_tokens: int | None,
) -> float | None:
    if model == "gpt-5.4-mini-2026-03-17":
        model = "gpt-5.4-mini"
    pricing = MODEL_PRICING.get((provider, model)) or MODEL_PRICING.get((provider, "*"))
    if pricing is None:
        return None
    input_price = pricing.get("input_per_1m")
    output_price = pricing.get("output_per_1m")
    if input_price is None or output_price is None or prompt_tokens is None or output_tokens is None:
        return None
    return round((prompt_tokens / 1_000_000 * input_price) + (output_tokens / 1_000_000 * output_price), 8)
