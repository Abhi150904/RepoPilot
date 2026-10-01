from __future__ import annotations

import httpx
import pytest
from types import SimpleNamespace

from app.core.config import Settings
from app.core.llm import GeminiLLMProvider, LLMProviderError, get_llm
from app.schemas.code_change import SourceFile
from app.schemas.issue import IssueAnalysis
from app.schemas.plan import ImplementationPlan


def _analysis() -> IssueAnalysis:
    return IssueAnalysis(
        summary="Login fails when email is missing.",
        suspected_area="authentication flow",
        likely_cause="Missing request validation.",
        risk_level="medium",
    )


def _plan() -> ImplementationPlan:
    return ImplementationPlan(
        summary="Validate missing email.",
        steps=["Add email validation."],
        files_to_inspect=["src/routes/login.py"],
        tests_required=["missing email returns validation error"],
    )


def _gemini_payload(text: str) -> dict[str, object]:
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": text,
                        }
                    ]
                }
            }
        ]
    }


def _response(status_code: int, payload: dict[str, object]) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("POST", "https://generativelanguage.googleapis.com"),
    )


def test_get_llm_builds_gemini_provider_from_settings() -> None:
    provider = get_llm(
        "coder",
        settings=Settings(
            llm_provider="gemini",
            llm_model="gemini-3.7-flash",
            gemini_api_key="test-key",
        ),
    )

    assert isinstance(provider, GeminiLLMProvider)


def test_get_llm_requires_gemini_api_key() -> None:
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        get_llm(
            "coder",
            settings=SimpleNamespace(
                llm_provider="gemini",
                llm_model="gemini-3.7-flash",
                gemini_api_key=None,
            ),
        )


def test_gemini_provider_parses_structured_code_changes(monkeypatch) -> None:
    captured = {}

    def fake_post(url, params, json, timeout):
        captured["url"] = url
        captured["params"] = params
        captured["json"] = json
        return _response(
            200,
            _gemini_payload(
                """
                {
                  "summary": "Validate email input.",
                  "changes": [
                    {
                      "path": "src/routes/login.py",
                      "action": "modify",
                      "explanation": "Add missing email validation.",
                      "proposed_content": "def login(payload):\\n    return {}, 400\\n"
                    }
                  ]
                }
                """
            ),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = GeminiLLMProvider(api_key="test-key", model="gemini-3.7-flash")

    change_set = provider.propose_code_changes(
        issue="Login endpoint returns 500 when email is missing",
        analysis=_analysis(),
        plan=_plan(),
        target_files=[
            SourceFile(
                path="src/routes/login.py",
                content="def login(payload):\n    email = payload[\"email\"]\n",
            )
        ],
    )

    assert "gemini-3.7-flash:generateContent" in captured["url"]
    assert captured["params"] == {"key": "test-key"}
    assert captured["json"]["generationConfig"]["responseMimeType"] == "application/json"
    assert change_set.summary == "Validate email input."
    assert change_set.changes[0].path == "src/routes/login.py"


def test_gemini_provider_rejects_malformed_json(monkeypatch) -> None:
    def fake_post(url, params, json, timeout):
        return _response(200, _gemini_payload("not json"))

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = GeminiLLMProvider(api_key="test-key", model="gemini-3.7-flash")

    with pytest.raises(LLMProviderError, match="malformed JSON"):
        provider.propose_code_changes(
            issue="Login endpoint returns 500 when email is missing",
            analysis=_analysis(),
            plan=_plan(),
            target_files=[],
        )
