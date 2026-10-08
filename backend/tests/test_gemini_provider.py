from __future__ import annotations

import httpx
import pytest
from types import SimpleNamespace

from app.core.config import Settings
from app.core.llm import GeminiLLMProvider, GroqLLMProvider, LLMProviderError, get_llm
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


def _gemini_payload_with_usage(text: str) -> dict[str, object]:
    payload = _gemini_payload(text)
    payload["usageMetadata"] = {
        "promptTokenCount": 11,
        "candidatesTokenCount": 7,
        "totalTokenCount": 18,
    }
    return payload


def _groq_payload(text: str) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": text,
                }
            }
        ],
        "usage": {
            "prompt_tokens": 13,
            "completion_tokens": 8,
            "total_tokens": 21,
        },
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
            _env_file=None,
        ),
    )

    assert isinstance(provider, GeminiLLMProvider)


def test_get_llm_uses_role_specific_model_when_configured() -> None:
    provider = get_llm(
        "reviewer",
        settings=Settings(
            llm_provider="gemini",
            llm_model="gemini-3.7-flash",
            reviewer_model="gemini-3.7-pro",
            gemini_api_key="test-key",
            _env_file=None,
        ),
    )

    assert isinstance(provider, GeminiLLMProvider)
    assert provider._model == "gemini-3.7-pro"


def test_get_llm_builds_groq_provider_from_settings() -> None:
    provider = get_llm(
        "coder",
        settings=Settings(
            llm_provider="groq",
            llm_model="openai/gpt-oss-120b",
            groq_api_key="test-key",
            _env_file=None,
        ),
    )

    assert isinstance(provider, GroqLLMProvider)
    assert provider._model == "openai/gpt-oss-120b"


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


def test_settings_accepts_groq_env_aliases(monkeypatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("REPOPILOT_GROQ_API_KEY", raising=False)
    monkeypatch.setenv("REPO_PILOT_LLM_PROVIDER", "groq")
    monkeypatch.setenv("REPO_PILOT_LLM_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("REPO_PILOT_GROQ_API_KEY", "test-key")

    settings = Settings(_env_file=None)

    assert settings.llm_provider == "groq"
    assert settings.llm_model == "openai/gpt-oss-120b"
    assert settings.groq_api_key == "test-key"


def test_settings_accepts_retry_and_cap_env_aliases(monkeypatch) -> None:
    monkeypatch.setenv("REPO_PILOT_LLM_MAX_RETRIES", "4")
    monkeypatch.setenv("REPO_PILOT_LLM_MAX_OUTPUT_TOKENS", "2048")
    monkeypatch.setenv("REPO_PILOT_LLM_MAX_PROMPT_CHARS", "9000")
    monkeypatch.setenv("REPO_PILOT_REVIEWER_MODEL", "gemini-reviewer")

    settings = Settings(_env_file=None)

    assert settings.llm_max_retries == 4
    assert settings.llm_max_output_tokens == 2048
    assert settings.llm_max_prompt_chars == 9000
    assert settings.reviewer_model == "gemini-reviewer"


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


def test_get_llm_requires_groq_api_key() -> None:
    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        get_llm(
            "coder",
            settings=SimpleNamespace(
                llm_provider="groq",
                llm_model="openai/gpt-oss-120b",
                groq_api_key=None,
            ),
        )


def test_groq_provider_analyzes_issue_with_json_mode(monkeypatch) -> None:
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _response(
            200,
            _groq_payload(
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
    provider = GroqLLMProvider(api_key="test-key", model="openai/gpt-oss-120b")

    analysis = provider.analyze_issue("Login endpoint returns 500 when email is missing")

    assert captured["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["json"]["model"] == "openai/gpt-oss-120b"
    assert captured["json"]["response_format"] == {"type": "json_object"}
    assert captured["json"]["max_completion_tokens"] == 8192
    assert '"role": "analyzer"' in captured["json"]["messages"][1]["content"]
    assert analysis.risk_level == "medium"
    assert provider.usage_events[0].provider == "groq"
    assert provider.usage_events[0].total_tokens == 21


def test_groq_provider_retries_malformed_json_with_repair_prompt(monkeypatch) -> None:
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(json)
        if len(calls) == 1:
            return _response(200, _groq_payload("not json"))
        return _response(
            200,
            _groq_payload(
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
    provider = GroqLLMProvider(
        api_key="test-key",
        model="openai/gpt-oss-120b",
        max_retries=1,
        sleep=lambda delay: None,
    )

    analysis = provider.analyze_issue("Login endpoint returns 500 when email is missing")

    assert analysis.risk_level == "medium"
    assert len(calls) == 2
    assert calls[1]["messages"][-1]["role"] == "user"
    assert "not json" in calls[1]["messages"][-1]["content"]


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


def test_gemini_provider_retries_transient_http_failures(monkeypatch) -> None:
    calls = []

    def fake_post(url, params, json, timeout):
        calls.append(json)
        if len(calls) == 1:
            return _response(503, {"error": {"message": "try again"}})
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
    provider = GeminiLLMProvider(
        api_key="test-key",
        model="gemini-3.7-flash",
        max_retries=1,
        sleep=lambda delay: None,
    )

    analysis = provider.analyze_issue("Login endpoint returns 500 when email is missing")

    assert len(calls) == 2
    assert analysis.risk_level == "medium"


def test_gemini_provider_retries_malformed_json_with_repair_prompt(monkeypatch) -> None:
    calls = []

    def fake_post(url, params, json, timeout):
        calls.append(json)
        if len(calls) == 1:
            return _response(200, _gemini_payload("not json"))
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
    provider = GeminiLLMProvider(
        api_key="test-key",
        model="gemini-3.7-flash",
        max_retries=1,
        sleep=lambda delay: None,
    )

    analysis = provider.analyze_issue("Login endpoint returns 500 when email is missing")

    assert analysis.risk_level == "medium"
    assert len(calls) == 2
    repair_text = calls[1]["contents"][1]["parts"][0]["text"]
    assert "corrected JSON only" in repair_text
    assert "IssueAnalysis" in repair_text
    assert "not json" in repair_text


def test_gemini_provider_extracts_json_from_wrapped_response(monkeypatch) -> None:
    def fake_post(url, params, json, timeout):
        return _response(
            200,
            _gemini_payload(
                """
                Here is the JSON:
                {
                  "summary": "Login fails when email is missing.",
                  "suspected_area": "authentication flow",
                  "likely_cause": "Missing validation allows a bad request through.",
                  "risk_level": "medium"
                }
                Done.
                """
            ),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = GeminiLLMProvider(
        api_key="test-key",
        model="gemini-3.7-flash",
        max_retries=0,
    )

    analysis = provider.analyze_issue("Login endpoint returns 500 when email is missing")

    assert analysis.risk_level == "medium"


def test_gemini_provider_accepts_raw_newlines_inside_json_strings(monkeypatch) -> None:
    def fake_post(url, params, json, timeout):
        return _response(
            200,
            _gemini_payload(
                """{
                  "summary": "Validate email input.",
                  "changes": [
                    {
                      "path": "src/routes/login.py",
                      "action": "modify",
                      "explanation": "Add validation.",
                      "proposed_content": "def login(payload):
    email = payload.get('email')
    if not email:
        return {'error': 'email is required'}, 400
    return {'email': email}
"
                    }
                  ]
                }"""
            ),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = GeminiLLMProvider(
        api_key="test-key",
        model="gemini-3.7-flash",
        max_retries=0,
    )

    change_set = provider.propose_code_changes(
        issue="Login endpoint returns 500 when email is missing",
        analysis=_analysis(),
        plan=_plan(),
        target_files=[SourceFile(path="src/routes/login.py", content="def login(payload): pass")],
    )

    assert change_set.changes[0].path == "src/routes/login.py"
    assert "email is required" in change_set.changes[0].proposed_content


def test_gemini_provider_records_usage_metadata(monkeypatch) -> None:
    def fake_post(url, params, json, timeout):
        return _response(
            200,
            _gemini_payload_with_usage(
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
    provider = GeminiLLMProvider(
        api_key="test-key",
        model="gemini-3.7-flash",
        role="analyzer",
    )

    provider.analyze_issue("Login endpoint returns 500 when email is missing")

    assert len(provider.usage_events) == 1
    assert provider.usage_events[0].role == "analyzer"
    assert provider.usage_events[0].prompt_tokens == 11
    assert provider.usage_events[0].output_tokens == 7
    assert provider.usage_events[0].total_tokens == 18


def test_gemini_provider_applies_output_and_prompt_caps(monkeypatch) -> None:
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
    provider = GeminiLLMProvider(
        api_key="test-key",
        model="gemini-3.7-flash",
        max_output_tokens=123,
        max_prompt_chars=250,
    )

    provider.analyze_issue("x" * 2000)

    assert captured["json"]["generationConfig"]["maxOutputTokens"] == 123
    prompt = captured["json"]["contents"][0]["parts"][0]["text"]
    assert len(prompt) < 350
    assert "truncated" in prompt


def test_gemini_provider_rejects_malformed_json(monkeypatch) -> None:
    def fake_post(url, params, json, timeout):
        return _response(200, _gemini_payload("not json"))

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = GeminiLLMProvider(
        api_key="test-key",
        model="gemini-3.7-flash",
        max_retries=0,
    )

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
