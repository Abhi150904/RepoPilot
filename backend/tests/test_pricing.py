from __future__ import annotations

from app.core.pricing import estimate_llm_cost_usd


def test_estimates_openai_cost() -> None:
    assert (
        estimate_llm_cost_usd(
            provider="openai",
            model="gpt-5.4-mini",
            prompt_tokens=20_000,
            output_tokens=5_000,
        )
        == 0.0375
    )


def test_unknown_model_cost_is_unavailable() -> None:
    assert (
        estimate_llm_cost_usd(
            provider="openai",
            model="unknown-model",
            prompt_tokens=20_000,
            output_tokens=5_000,
        )
        is None
    )


def test_missing_usage_cost_is_unavailable() -> None:
    assert (
        estimate_llm_cost_usd(
            provider="openai",
            model="gpt-5.4-mini",
            prompt_tokens=20_000,
            output_tokens=None,
        )
        is None
    )
