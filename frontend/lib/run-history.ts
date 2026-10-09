import type { RunStatusResponse } from "@/lib/api";

export type StoredRunSummary = {
  runId: string;
  repository: string;
  issue: string;
  status: string;
  tests: string;
  duration: string;
  updatedAt: string;
};

export function rememberRun(run: RunStatusResponse): StoredRunSummary[] {
  const next = summaryFromRun(run);
  return [next];
}

export function summariesFromRuns(runs: RunStatusResponse[]): StoredRunSummary[] {
  return runs.map(summaryFromRun);
}

export function summaryFromRun(run: RunStatusResponse): StoredRunSummary {
  const result = run.response?.result ?? {};
  const repository = stringValue(result.repository) ?? String(run.request.repository ?? "Issue text");
  const issueNumber = run.request.issue_number ?? result.issue_number;
  return {
    runId: run.run_id,
    repository,
    issue: typeof issueNumber === "number" ? `#${issueNumber}` : "Manual issue",
    status: run.lifecycle_status,
    tests: testsLabel(run),
    duration: durationLabel(run),
    updatedAt: stringValue(run.updated_at) ?? new Date().toISOString()
  };
}

export function stageForStatus(status: string): string {
  if (status === "queued") {
    return "Queued";
  }
  if (status === "running") {
    return "Engineering";
  }
  if (status === "failed") {
    return "Needs repair";
  }
  return "Review";
}

function testsLabel(run: RunStatusResponse): string {
  const testsPassed = run.response?.run_summary?.tests_passed;
  if (testsPassed === true) {
    return "passed";
  }
  if (testsPassed === false) {
    return "failed";
  }
  return "—";
}

function durationLabel(run: RunStatusResponse): string {
  if (run.lifecycle_status === "queued" || run.lifecycle_status === "running") {
    return "live";
  }
  const started = Date.parse(String(run.created_at));
  const ended = Date.parse(String(run.updated_at));
  if (Number.isNaN(started) || Number.isNaN(ended) || ended < started) {
    return "n/a";
  }
  const seconds = Math.round((ended - started) / 1000);
  if (seconds < 60) {
    return `${seconds}s`;
  }
  return `${Math.round(seconds / 60)}m`;
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}
