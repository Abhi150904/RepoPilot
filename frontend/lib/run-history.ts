import type { RunStatusResponse } from "@/lib/api";

const STORAGE_KEY = "repopilot.recentRuns";

export type StoredRunSummary = {
  runId: string;
  repository: string;
  issue: string;
  status: string;
  updatedAt: string;
};

export function readRunHistory(): StoredRunSummary[] {
  if (typeof window === "undefined") {
    return [];
  }
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return value ? JSON.parse(value) : [];
  } catch {
    return [];
  }
}

export function rememberRun(run: RunStatusResponse): StoredRunSummary[] {
  const next = summaryFromRun(run);
  const existing = readRunHistory().filter((item) => item.runId !== run.run_id);
  const history = [next, ...existing].slice(0, 12);
  if (typeof window !== "undefined") {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(history));
  }
  return history;
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

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}
