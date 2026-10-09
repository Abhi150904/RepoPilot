from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import tempfile
from typing import Iterable

from app.core.llm_usage import LLMCallContext, LLMUsageRecorderProtocol, llm_call_context
from app.evals.models import (
    EvalCase,
    EvalCaseResult,
    EvalCheck,
    EvalSuiteResult,
    resolve_workspace_path,
)
from app.graph.workflow import build_workflow

DEFAULT_CASE_DIR = Path("backend/tests/fixtures/evals")
CASE_PATTERN = "*.case.json"


def load_eval_case(path: Path) -> EvalCase:
    return EvalCase.model_validate(json.loads(path.read_text(encoding="utf-8")))


def run_eval_case(
    path: Path,
    *,
    eval_run_id: str | None = None,
    eval_case_id: int | None = None,
    usage_recorder: LLMUsageRecorderProtocol | None = None,
) -> EvalCaseResult:
    case = load_eval_case(path)
    workflow_input: dict[str, object] = {"issue": case.issue}
    workspace_path = _prepare_workspace(case=case, case_file=path)
    try:
        if workspace_path is not None:
            workflow_input["workspace_path"] = workspace_path
        if case.target_paths:
            workflow_input["target_paths"] = case.target_paths
        if case.apply_changes:
            workflow_input["apply_changes"] = True
        if case.run_tests:
            workflow_input["run_tests"] = True
            workflow_input["test_runner"] = case.test_runner
        if case.test_command is not None:
            workflow_input["test_command"] = case.test_command
        if case.approved:
            workflow_input["approved"] = True

        with llm_call_context(
            LLMCallContext(
                eval_run_id=eval_run_id,
                eval_case_id=eval_case_id,
                recorder=usage_recorder,
            )
        ):
            result = build_workflow().invoke(workflow_input)
        return evaluate_result(case=case, result=result)
    finally:
        if case.copy_workspace and workspace_path is not None:
            shutil.rmtree(workspace_path, ignore_errors=True)


def run_eval_suite(paths: Iterable[Path]) -> EvalSuiteResult:
    case_paths = list(paths)
    case_results = [run_eval_case(path) for path in case_paths]
    passed = sum(1 for result in case_results if result.status == "passed")
    failed = len(case_results) - passed
    points_earned = sum(result.points_earned for result in case_results)
    points_possible = sum(result.points_possible for result in case_results)
    return EvalSuiteResult(
        total=len(case_results),
        passed=passed,
        failed=failed,
        points_earned=points_earned,
        points_possible=points_possible,
        score=_score(points_earned, points_possible),
        category_scores=_category_scores(case_results),
        cases=case_results,
    )


def discover_eval_cases(paths: Iterable[Path]) -> list[Path]:
    discovered: list[Path] = []
    for path in paths:
        if path.is_dir():
            discovered.extend(sorted(path.rglob(CASE_PATTERN)))
        elif path.is_file():
            discovered.append(path)
        else:
            raise FileNotFoundError(f"Eval case path does not exist: {path}")

    unique: list[Path] = []
    seen: set[Path] = set()
    for path in discovered:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique


def evaluate_result(case: EvalCase, result: dict[str, object]) -> EvalCaseResult:
    checks = [
        _check_final_status(case, result),
        _check_tests_passed(case, result),
        _check_touched_files(case, result),
        _check_forbidden_files(case, result),
    ]
    status = "passed" if all(check.passed for check in checks) else "failed"
    points_possible = sum(check.points for check in checks)
    points_earned = sum(check.points for check in checks if check.passed)
    return EvalCaseResult(
        id=case.id,
        status=status,
        checks=checks,
        points_earned=points_earned,
        points_possible=points_possible,
        score=_score(points_earned, points_possible),
        repair_attempts=_repair_attempts(result),
        repair_succeeded=_repair_succeeded(result),
    )


def _check_final_status(case: EvalCase, result: dict[str, object]) -> EvalCheck:
    expected = case.expectations.final_status
    if expected is None:
        return EvalCheck(
            name="final_status",
            category="outcome",
            passed=True,
            message="No final status expectation configured.",
            points=0,
        )
    actual = _run_summary(result).get("status")
    return EvalCheck(
        name="final_status",
        category="outcome",
        passed=actual == expected,
        message=f"Expected final status {expected!r}; got {actual!r}.",
    )


def _check_tests_passed(case: EvalCase, result: dict[str, object]) -> EvalCheck:
    expected = case.expectations.tests_passed
    if expected is None:
        return EvalCheck(
            name="tests_passed",
            category="tests",
            passed=True,
            message="No tests-passed expectation configured.",
            points=0,
        )
    actual = _run_summary(result).get("tests_passed")
    return EvalCheck(
        name="tests_passed",
        category="tests",
        passed=actual is expected,
        message=f"Expected tests_passed {expected!r}; got {actual!r}.",
    )


def _check_touched_files(case: EvalCase, result: dict[str, object]) -> EvalCheck:
    expected = set(case.expectations.touched_files)
    if not expected:
        return EvalCheck(
            name="touched_files",
            category="files",
            passed=True,
            message="No touched-file expectation configured.",
            points=0,
        )
    actual = set(_modified_files(result))
    missing = sorted(expected - actual)
    return EvalCheck(
        name="touched_files",
        category="files",
        passed=not missing,
        message=f"Missing expected touched files: {missing}.",
    )


def _check_forbidden_files(case: EvalCase, result: dict[str, object]) -> EvalCheck:
    forbidden = set(case.expectations.forbidden_files)
    if not forbidden:
        return EvalCheck(
            name="forbidden_files",
            category="files",
            passed=True,
            message="No forbidden-file expectation configured.",
            points=0,
        )
    actual = set(_modified_files(result))
    touched_forbidden = sorted(forbidden & actual)
    return EvalCheck(
        name="forbidden_files",
        category="files",
        passed=not touched_forbidden,
        message=f"Touched forbidden files: {touched_forbidden}.",
    )


def _run_summary(result: dict[str, object]) -> dict[str, object]:
    summary = result.get("run_summary")
    return summary if isinstance(summary, dict) else {}


def _repair_attempts(result: dict[str, object]) -> int:
    value = _run_summary(result).get("repair_attempts", result.get("repair_attempts"))
    return value if isinstance(value, int) and value >= 0 else 0


def _repair_succeeded(result: dict[str, object]) -> bool | None:
    attempts = _repair_attempts(result)
    if attempts == 0:
        return None
    summary = _run_summary(result)
    return bool(summary.get("tests_passed")) and summary.get("status") in {"ready_for_review", "awaiting_approval", "approved"}


def _modified_files(result: dict[str, object]) -> list[str]:
    files = result.get("modified_files")
    return files if isinstance(files, list) else []


def _prepare_workspace(case: EvalCase, case_file: Path) -> str | None:
    workspace_path = resolve_workspace_path(case, case_file)
    if workspace_path is None or not case.copy_workspace:
        return workspace_path

    source = Path(workspace_path)
    target = Path(tempfile.mkdtemp(prefix=f"repopilot-eval-{case.id}-"))
    shutil.copytree(source, target, dirs_exist_ok=True)
    return str(target)


def _score(points_earned: int, points_possible: int) -> float:
    if points_possible == 0:
        return 1.0
    return round(points_earned / points_possible, 4)


def _category_scores(results: list[EvalCaseResult]) -> dict[str, float]:
    totals: dict[str, tuple[int, int]] = {}
    for result in results:
        for check in result.checks:
            earned, possible = totals.get(check.category, (0, 0))
            totals[check.category] = (
                earned + (check.points if check.passed else 0),
                possible + check.points,
            )
    return {
        category: _score(earned, possible)
        for category, (earned, possible) in totals.items()
        if possible > 0
    }


def _print_report(result: EvalSuiteResult) -> None:
    percent = int(result.score * 100)
    print(
        f"Eval cases: {result.passed}/{result.total} passed "
        f"({result.points_earned}/{result.points_possible} points, {percent}%)"
    )
    if result.category_scores:
        categories = ", ".join(
            f"{category}={int(score * 100)}%"
            for category, score in sorted(result.category_scores.items())
        )
        print(f"Categories: {categories}")
    for case in result.cases:
        case_percent = int(case.score * 100)
        print(
            f"- {case.id}: {case.status} "
            f"({case.points_earned}/{case.points_possible}, {case_percent}%)"
        )
        for check in case.checks:
            marker = "ok" if check.passed else "fail"
            print(f"  [{marker}] {check.category}.{check.name}: {check.message}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RepoPilot eval cases.")
    parser.add_argument(
        "cases",
        nargs="*",
        help="Eval case JSON files or directories. Defaults to backend/tests/fixtures/evals.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the eval suite result as JSON.",
    )
    args = parser.parse_args()

    input_paths = [Path(case) for case in args.cases] or [DEFAULT_CASE_DIR]
    case_paths = discover_eval_cases(input_paths)
    if not case_paths:
        raise SystemExit("No eval case files found.")

    result = run_eval_suite(case_paths)
    if args.json:
        print(result.model_dump_json(indent=2))
    else:
        _print_report(result)
    if result.failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
