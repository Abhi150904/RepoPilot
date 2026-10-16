from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json

import httpx
import pytest

from app.core.config import Settings
from app.core.llm import LLMProviderError, MockLLMProvider, get_llm
from app.core.llm_budget import BudgetExceededError, LLMBudget
from app.core.llm_usage import LLMCallContext, llm_call_context
from app.core.llm_usage import LLMUsageRecorder
from app.core.openai_provider import OpenAILLMProvider, _strict_schema
from app.schemas.code_change import CodeChangeSet, SourceFile
from app.schemas.issue import IssueAnalysis
from app.schemas.plan import ImplementationPlan


def analysis():
    return {"summary": "Validate input", "suspected_area": "login", "likely_cause": "No validation", "risk_level": "medium"}


def response(data, *, usage=True, status="completed"):
    result = {
        "status": status,
        "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(data)}]}],
    }
    if usage:
        result["usage"] = {"input_tokens": 100, "output_tokens": 200, "total_tokens": 300,
                           "output_tokens_details": {"reasoning_tokens": 50}}
    return result


def http_response(status, body, headers=None):
    return httpx.Response(status, json=body, headers=headers,
                          request=httpx.Request("POST", "https://api.openai.com/v1/responses"))


@pytest.fixture
def provider(tmp_path):
    return OpenAILLMProvider(
        api_key="test-key", model="gpt-5.4-mini",
        budget_path=str(tmp_path / "budget.sqlite"), sleep=lambda _: None,
    )


def test_factory_supports_openai_and_mock(tmp_path):
    config = Settings(_env_file=None, llm_provider="openai", openai_api_key="test",
                      llm_budget_path=str(tmp_path / "budget.sqlite"))
    assert isinstance(get_llm("coder", config), OpenAILLMProvider)
    assert isinstance(get_llm("coder", Settings(_env_file=None, llm_provider="mock")), MockLLMProvider)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        get_llm("coder", Settings(_env_file=None, llm_provider="openai", openai_api_key=None))
    with pytest.raises(ValueError, match="Unsupported"):
        get_llm("coder", Settings(_env_file=None, llm_provider="removed-provider"))


def test_strict_schema_requires_optional_keys_and_disallows_extra_fields():
    schema = _strict_schema(CodeChangeSet)
    assert schema["required"] == list(schema["properties"])
    assert schema["additionalProperties"] is False
    change = schema["$defs"]["FileChange"]
    assert "proposed_content" in change["required"]
    assert change["additionalProperties"] is False
    assert "default" not in change["properties"]["proposed_content"]


def test_responses_api_mapping_and_usage(provider, monkeypatch):
    calls = []
    class Recorder:
        def record(self, context, event):
            calls.append((context, event))
    def post(url, headers, json, timeout):
        assert url == "https://api.openai.com/v1/responses"
        assert headers["Authorization"] == "Bearer test-key"
        assert json["store"] is False
        assert json["text"]["format"]["strict"] is True
        assert json["max_output_tokens"] == 8192
        return http_response(200, response(analysis()))
    monkeypatch.setattr(httpx, "post", post)
    with llm_call_context(LLMCallContext(run_id="run-1", recorder=Recorder())):
        assert provider.analyze_issue("Validate login").risk_level == "medium"
    event = provider.usage_events[0]
    assert event.total_tokens == 300
    assert event.reasoning_tokens == 50
    assert event.estimated_cost_usd == pytest.approx(0.000975)
    assert event.success is True
    assert calls[0][0].run_id == "run-1"
    assert len(provider.usage_events) == 1


@pytest.mark.parametrize("status", [429, 503])
def test_transient_failure_waits_then_recovers(provider, monkeypatch, status):
    calls, delays = [], []
    def post(*args, **kwargs):
        calls.append(kwargs["json"])
        if len(calls) == 1:
            return http_response(status, {"error": {"code": "rate_limit_exceeded"}},
                                 {"Retry-After": "35"})
        return http_response(200, response(analysis()))
    monkeypatch.setattr(httpx, "post", post)
    provider._sleep = delays.append
    assert provider.analyze_issue("Validate input").summary == "Validate input"
    assert delays == [36]
    assert len(provider.usage_events) == 2


def test_quota_failure_does_not_retry(provider, monkeypatch):
    calls = []
    def post(*args, **kwargs):
        calls.append(1)
        return http_response(429, {"error": {"code": "insufficient_quota"}})
    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(LLMProviderError, match="insufficient_quota"):
        provider.analyze_issue("Fix issue")
    assert len(calls) == 1


@pytest.mark.parametrize("body", [
    response(analysis(), status="incomplete"),
    response({"summary": "Missing schema fields"}),
    {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal"}]}]},
    {"status": "completed", "output": []},
])
def test_unusable_response_never_becomes_changes(provider, monkeypatch, body):
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: http_response(200, body))
    with pytest.raises(LLMProviderError):
        provider.analyze_issue("Fix issue")
    assert provider.usage_events[0].success is False


def test_missing_usage_stays_unknown(provider, monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: http_response(200, response(analysis(), usage=False)))
    provider.analyze_issue("Fix issue")
    event = provider.usage_events[0]
    assert event.total_tokens is None
    assert event.estimated_cost_usd is None


def test_source_is_complete_or_request_is_rejected(provider, monkeypatch):
    source = "x" * 20_000 + "\n# last line"
    def post(*args, **kwargs):
        prompt = json.loads(kwargs["json"]["input"])
        assert prompt["context"]["target_files"][0]["content"] == source
        return http_response(200, response({"summary": "No edit", "changes": [], "diff": ""}))
    monkeypatch.setattr(httpx, "post", post)
    provider.propose_code_changes("Fix issue", IssueAnalysis(**analysis()),
                                 ImplementationPlan(summary="Fix", steps=[], files_to_inspect=[], tests_required=[]),
                                 [SourceFile(path="src/app.py", content=source)])
    provider._max_prompt_chars = 100
    with pytest.raises(LLMProviderError, match="not truncated"):
        provider.analyze_issue("x" * 1000)


def test_budget_persists_and_unknown_cost_keeps_reservation(tmp_path):
    path = str(tmp_path / "budget.sqlite")
    budget = LLMBudget(path, "key", 0.10, 0.10)
    reservation = budget.reserve(0.08, "run")
    budget.settle(reservation, None)
    restarted = LLMBudget(path, "key", 0.10, 0.10)
    with pytest.raises(BudgetExceededError):
        restarted.reserve(0.03, "another-run")
    restarted.settle(reservation, 0.01)
    restarted.reserve(0.03, "another-run")


def test_budget_reservations_are_atomic(tmp_path):
    budget = LLMBudget(str(tmp_path / "budget.sqlite"), "key", 0.10, 0.10)
    def reserve(_):
        try:
            budget.reserve(0.06, "run")
            return True
        except BudgetExceededError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(reserve, range(2))) == [False, True]


def test_run_budget_and_unknown_model_block_before_network(provider, monkeypatch):
    def post(*a, **kw):
        raise AssertionError("No network request should occur")
    monkeypatch.setattr(httpx, "post", post)
    provider._budget.run_limit = 0.00001
    with pytest.raises(LLMProviderError, match="spending guard"):
        provider.analyze_issue("Fix")
    provider._model = "unpriced-model"
    with pytest.raises(LLMProviderError, match="No verified pricing"):
        provider.analyze_issue("Fix")


def test_workflow_collects_openai_usage_through_existing_interface(tmp_path, monkeypatch):
    from app.graph import workflow

    def post(*args, **kwargs):
        role = json.loads(kwargs["json"]["input"])["role"]
        data = {
            "analyzer": analysis(),
            "planner": {"summary": "Fix", "steps": [], "files_to_inspect": [], "tests_required": []},
            "coder": {"summary": "No source loaded", "changes": [], "diff": ""},
        }[role]
        return http_response(200, response(data))

    monkeypatch.setattr(httpx, "post", post)
    monkeypatch.setattr(workflow, "get_llm", lambda role: OpenAILLMProvider(
        api_key="test", model="gpt-5.4-mini", role=role,
        budget_path=str(tmp_path / "budget.sqlite"),
    ))
    with llm_call_context(LLMCallContext(run_id="workflow-test")):
        result = workflow.build_workflow().invoke({"issue": "Fix input validation"})
    assert result["run_metrics"]["total_tokens"] == 900
    assert result["run_metrics"]["llm_call_count"] == 3


def test_persisted_usage_does_not_hide_missing_values():
    from sqlalchemy import create_engine
    from app.schemas.execution import LLMUsageEvent
    recorder = LLMUsageRecorder(engine=create_engine("sqlite+pysqlite:///:memory:"))
    context = LLMCallContext(run_id="usage-test")
    recorder.record(context, LLMUsageEvent(
        role="coder", provider="openai", model="gpt-5.4-mini",
        prompt_tokens=100, output_tokens=200, total_tokens=300, estimated_cost_usd=0.001,
    ))
    assert recorder.aggregate(run_id="usage-test")["total_tokens"] == 300
    recorder.record(context, LLMUsageEvent(role="coder", provider="openai", model="gpt-5.4-mini"))
    aggregate = recorder.aggregate(run_id="usage-test")
    assert aggregate["total_tokens"] is None
    assert aggregate["estimated_cost_usd"] is None
    assert aggregate["by_role"]["coder"]["total_tokens"] is None
