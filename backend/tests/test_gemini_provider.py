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


def test_settings_accepts_repo_pilot_env_aliases(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("REPOPILOT_GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("REPO_PILOT_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("REPO_PILOT_LLM_MODEL", "gemini-3.7-pro")
    monkeypatch.setenv("REPO_PILOT_GEMINI_API_KEY", "test-key")

    settings = Settings(_env_file=None)

    assert settings.llm_provider == "gemini"
    assert settings.llm_model == "gemini-3.7-pro"
    assert settings.gemini_api_key == "test-key"


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


def test_get_llm_requires_gemini_model() -> None:
    with pytest.raises(ValueError, match="REPO_PILOT_LLM_MODEL"):
        get_llm(
            "coder",
            settings=SimpleNamespace(
                llm_provider="gemini",
                llm_model=" ",
                gemini_api_key="test-key",
            ),
        )


def test_gemini_provider_analyzes_issue_with_structured_output(monkeypatch) -> None:
    captured = {}

    def fake_post(url, params, json, timeout):
        captured["json"] = json
        return _response(
            200,
            _gemini_payload(
                """
                {
                  "summary": "Login fails when email is missing.",
                  "suspected_area": "authentication flow",
                  "likely_cause": "Missing validation allows a bad request through.",
                  "risk_level": "medium"
                }
                """
            ),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = GeminiLLMProvider(api_key="test-key", model="gemini-3.7-flash")

    analysis = provider.analyze_issue("Login endpoint returns 500 when email is missing")

    prompt = captured["json"]["contents"][0]["parts"][0]["text"]
    assert '"role": "analyzer"' in prompt
    assert analysis.risk_level == "medium"
    assert analysis.suspected_area == "authentication flow"


def test_gemini_provider_creates_plan_with_repository_context(monkeypatch) -> None:
    captured = {}

    def fake_post(url, params, json, timeout):
        captured["json"] = json
        return _response(
            200,
            _gemini_payload(
                """
                {
                  "summary": "Add email validation to the login route.",
                  "steps": ["Inspect login request parsing.", "Return 400 when email is missing."],
                  "files_to_inspect": ["backend/routes/login.py", "backend/tests/test_login.py"],
                  "tests_required": ["missing email returns 400"]
                }
                """
            ),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = GeminiLLMProvider(api_key="test-key", model="gemini-3.7-flash")

    plan = provider.create_plan(
        issue="Login endpoint returns 500 when email is missing",
        analysis=_analysis(),
    )

    prompt = captured["json"]["contents"][0]["parts"][0]["text"]
    assert '"role": "planner"' in prompt
    assert plan.files_to_inspect == ["backend/routes/login.py", "backend/tests/test_login.py"]
    assert plan.tests_required == ["missing email returns 400"]


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
    assert '"role": "coder"' in captured["json"]["contents"][0]["parts"][0]["text"]
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


def test_gemini_provider_includes_status_body_in_http_errors(monkeypatch) -> None:
    def fake_post(url, params, json, timeout):
        return _response(400, {"error": {"message": "bad model name"}})

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = GeminiLLMProvider(api_key="test-key", model="bad-model")

    with pytest.raises(LLMProviderError, match="bad-model.*400.*bad model name"):
        provider.analyze_issue("Login endpoint returns 500 when email is missing")
