from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import tempfile
from typing import Iterable

from app.evals.models import (
    EvalCase,
    EvalCaseResult,
    EvalCheck,
    EvalSuiteResult,
    resolve_workspace_path,
)
from app.graph.workflow import build_workflow


def load_eval_case(path: Path) -> EvalCase:
    return EvalCase.model_validate(json.loads(path.read_text(encoding="utf-8")))


def run_eval_case(path: Path) -> EvalCaseResult:
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

        result = build_workflow().invoke(workflow_input)
        return evaluate_result(case=case, result=result)
    finally:
        if case.copy_workspace and workspace_path is not None:
            shutil.rmtree(workspace_path, ignore_errors=True)


def run_eval_suite(paths: Iterable[Path]) -> EvalSuiteResult:
    case_results = [run_eval_case(path) for path in paths]
    passed = sum(1 for result in case_results if result.status == "passed")
    failed = len(case_results) - passed
    return EvalSuiteResult(
        total=len(case_results),
        passed=passed,
        failed=failed,
        cases=case_results,
    )


def evaluate_result(case: EvalCase, result: dict[str, object]) -> EvalCaseResult:
    checks = [
        _check_final_status(case, result),
        _check_tests_passed(case, result),
        _check_touched_files(case, result),
        _check_forbidden_files(case, result),
    ]
    status = "passed" if all(check.passed for check in checks) else "failed"
    return EvalCaseResult(id=case.id, status=status, checks=checks)


def _check_final_status(case: EvalCase, result: dict[str, object]) -> EvalCheck:
    expected = case.expectations.final_status
    if expected is None:
        return EvalCheck(
            name="final_status",
            passed=True,
            message="No final status expectation configured.",
        )
    actual = _run_summary(result).get("status")
    return EvalCheck(
        name="final_status",
        passed=actual == expected,
        message=f"Expected final status {expected!r}; got {actual!r}.",
    )


def _check_tests_passed(case: EvalCase, result: dict[str, object]) -> EvalCheck:
    expected = case.expectations.tests_passed
    if expected is None:
        return EvalCheck(
            name="tests_passed",
            passed=True,
            message="No tests-passed expectation configured.",
        )
    actual = _run_summary(result).get("tests_passed")
    return EvalCheck(
        name="tests_passed",
        passed=actual is expected,
        message=f"Expected tests_passed {expected!r}; got {actual!r}.",
    )


def _check_touched_files(case: EvalCase, result: dict[str, object]) -> EvalCheck:
    expected = set(case.expectations.touched_files)
    if not expected:
        return EvalCheck(
            name="touched_files",
            passed=True,
            message="No touched-file expectation configured.",
        )
    actual = set(_modified_files(result))
    missing = sorted(expected - actual)
    return EvalCheck(
        name="touched_files",
        passed=not missing,
        message=f"Missing expected touched files: {missing}.",
    )


def _check_forbidden_files(case: EvalCase, result: dict[str, object]) -> EvalCheck:
    forbidden = set(case.expectations.forbidden_files)
    if not forbidden:
        return EvalCheck(
            name="forbidden_files",
            passed=True,
            message="No forbidden-file expectation configured.",
        )
    actual = set(_modified_files(result))
    touched_forbidden = sorted(forbidden & actual)
    return EvalCheck(
        name="forbidden_files",
        passed=not touched_forbidden,
        message=f"Touched forbidden files: {touched_forbidden}.",
    )


def _run_summary(result: dict[str, object]) -> dict[str, object]:
    summary = result.get("run_summary")
    return summary if isinstance(summary, dict) else {}


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


def _print_report(result: EvalSuiteResult) -> None:
    print(f"Eval cases: {result.passed}/{result.total} passed")
    for case in result.cases:
        print(f"- {case.id}: {case.status}")
        for check in case.checks:
            marker = "ok" if check.passed else "fail"
            print(f"  [{marker}] {check.name}: {check.message}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RepoPilot eval cases.")
    parser.add_argument("cases", nargs="+", help="Path(s) to eval case JSON files.")
    args = parser.parse_args()

    result = run_eval_suite(Path(case) for case in args.cases)
    _print_report(result)
    if result.failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
