import type { RunStatusResponse } from "@/lib/api";

export type StoredRunSummary = {
  runId: string;
  repository: string;
  issue: string;
  status: string;
  statusLabel: string;
  stage: string;
  tests: string;
  duration: string;
  updatedAt: string;
  needsAttention: boolean;
  attentionLabel: string;
  attentionAction: "review" | "inspect";
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
  const responseSummary = run.response?.run_summary ?? {};
  const runSummary = objectValue(result.run_summary) ?? responseSummary;
  const review = objectValue(result.review_result);
  const approval = objectValue(result.approval_decision);
  const approvalStatus = stringValue(approval?.status);
  const hasFinalApprovalDecision = approval?.approved === true || approvalStatus === "not_ready" || isHumanRejection(approval);
  const hasLlmError = Boolean(objectValue(result.llm_error)) || isProviderLimitError(run);
  const testsPassed = run.response?.run_summary?.tests_passed;
  const repository = stringValue(result.repository) ?? String(run.request.repository ?? "Issue text");
  const issueNumber = run.request.issue_number ?? result.issue_number;
  const needsApproval =
    run.lifecycle_status === "completed" &&
    Boolean(review) &&
    testsPassed === true &&
    !hasFinalApprovalDecision &&
    !hasLlmError;
  return {
    runId: run.run_id,
    repository,
    issue: typeof issueNumber === "number" ? `#${issueNumber}` : "Manual issue",
    status: run.lifecycle_status,
    statusLabel: statusLabel(run),
    stage: stageForRun(run),
    tests: testsLabel(run),
    duration: durationLabel(run),
    updatedAt: stringValue(run.updated_at) ?? new Date().toISOString(),
    needsAttention: needsApproval,
    attentionLabel: needsApproval ? "Ready for approval" : "",
    attentionAction: "review"
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

export function stageForRun(run: RunStatusResponse | StoredRunSummary): string {
  if ("stage" in run && run.stage) {
    return run.stage;
  }
  if (!("lifecycle_status" in run)) {
    return stageForStatus(run.status);
  }
  const result = run.response?.result ?? {};
  if (isProviderLimitError(run)) {
    return "Provider limit";
  }
  if (run.lifecycle_status === "queued") {
    return "Queued";
  }
  if (run.lifecycle_status === "running") {
    return "Engineering";
  }
  if (run.lifecycle_status === "failed") {
    return "Failed";
  }
  if (
    run.lifecycle_status === "completed" &&
    stringValue(objectValue(result.test_analysis)?.status) === "unavailable"
  ) {
    return "Verification unavailable";
  }
  if (run.lifecycle_status === "completed" && run.response?.run_summary?.tests_passed === false) {
    return "Approval blocked";
  }
  if (objectValue(result.publish_result)?.status === "published") {
    return "Published";
  }
  const approval = objectValue(result.approval_decision);
  if (isHumanRejection(approval)) {
    return "Rejected";
  }
  if (stringValue(approval?.status) === "not_ready") {
    return "Approval blocked";
  }
  if (approval?.approved === true) {
    return "Approved";
  }
  if (stringValue(approval?.status) === "awaiting_approval") {
    return "Ready for approval";
  }
  if (objectValue(result.review_result)) {
    return "Review";
  }
  return stageForStatus(run.lifecycle_status);
}

function statusLabel(run: RunStatusResponse): string {
  if (isProviderLimitError(run)) {
    return "rate limited";
  }
  const approval = objectValue(run.response?.result?.approval_decision);
  if (isHumanRejection(approval)) {
    return "rejected";
  }
  if (run.publication_status && run.publication_status !== "not_started") {
    return run.publication_status.replace("_", " ");
  }
  if (stringValue(approval?.status) === "not_ready") {
    return "approval blocked";
  }
  if (run.lifecycle_status === "completed" && stringValue(approval?.status) === "awaiting_approval") {
    return "awaiting approval";
  }
  return run.lifecycle_status;
}

function isHumanRejection(approval: Record<string, unknown> | null): boolean {
  // The backend uses not_ready for both automated blockers and human rejection.
  return approval?.status === "not_ready" && approval?.summary === "Human reviewer rejected this run.";
}

function testsLabel(run: RunStatusResponse): string {
  const testAnalysis = objectValue(run.response?.result?.test_analysis);
  if (stringValue(testAnalysis?.status) === "unavailable") {
    return "unavailable";
  }
  const testsPassed = run.response?.run_summary?.tests_passed;
  if (testsPassed === true) {
    return "passed";
  }
  if (testsPassed === false) {
    return "failed";
  }
  return "—";
}

function isProviderLimitError(run: RunStatusResponse): boolean {
  const result = run.response?.result ?? {};
  const llmError = objectValue(result.llm_error);
  const values = [
    run.error?.code,
    run.error?.message,
    stringValue(llmError?.code),
    stringValue(llmError?.message),
    stringValue(llmError?.type)
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return values.includes("429") || values.includes("rate_limit") || values.includes("too many requests");
}

function objectValue(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

export function durationLabel(run: RunStatusResponse): string {
  if (run.lifecycle_status === "queued" || run.lifecycle_status === "running") {
    return "live";
  }
  const runtimeMs = workflowRuntimeMs(run);
  if (runtimeMs !== undefined) {
    return formatDuration(Math.round(runtimeMs / 1000));
  }
  const started = Date.parse(String(run.created_at));
  const ended = Date.parse(String(run.updated_at));
  if (Number.isNaN(started) || Number.isNaN(ended) || ended < started) {
    return "n/a";
  }
  return formatDuration(Math.round((ended - started) / 1000));
}

function workflowRuntimeMs(run: RunStatusResponse): number | undefined {
  const result = run.response?.result ?? {};
  const metrics = objectValue(result.run_metrics);
  const totalRuntime = numberValue(metrics?.total_runtime_ms);
  if (totalRuntime !== undefined) {
    return totalRuntime;
  }
  const timings = Array.isArray(result.stage_timings) ? result.stage_timings : [];
  const timingTotal = timings.reduce((total, timing) => {
    const duration = numberValue(objectValue(timing)?.duration_ms);
    return total + (duration ?? 0);
  }, 0);
  return timingTotal > 0 ? timingTotal : undefined;
}

function formatDuration(seconds: number): string {
  if (seconds < 60) {
    return `${seconds}s`;
  }
  return `${Math.round(seconds / 60)}m`;
}

function numberValue(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}
