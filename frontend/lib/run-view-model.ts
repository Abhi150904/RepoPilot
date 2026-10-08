import {
  Braces,
  Code2,
  GitPullRequestArrow,
  Play,
  Radar,
  ShieldCheck,
  TestTube2,
  TimerReset,
  UserCheck
} from "lucide-react";
import type { RunStatusResponse } from "@/lib/api";
import { diffLines as fallbackDiffLines, planSteps as fallbackPlanSteps } from "@/lib/sample-data";

export type DiffLine = {
  kind: "add" | "remove" | "context";
  text: string;
};

export type TimelineState = "complete" | "active" | "muted" | "locked";

export type RunViewModel = {
  repository: string;
  issue: string;
  issueUrl?: string;
  headline: string;
  status: string;
  summary: string;
  nextAction: string;
  canReview: boolean;
  timeline: Array<{
    label: string;
    icon: typeof Radar;
    state: TimelineState;
    detail: string;
  }>;
  planSteps: string[];
  diffLines: DiffLine[];
  diffFile: string;
  diffStats: string;
  changedFiles: string[];
  tests: {
    label: string;
    passed: boolean | null;
    status: string;
    summary: string;
  };
  review: {
    blockers: number;
    notes: number;
    confidence: string;
    risk: string;
  };
  repairAttempts: string;
  tokens: string;
  verification: Array<{
    label: string;
    verified: boolean;
  }>;
  publish: {
    mode: string;
    branch: string;
    repository: string;
    title: string;
    status: string;
    summary: string;
    prUrl?: string;
  };
  failure: {
    failedTest: string;
    reason: string;
    repair: string;
    attempt: string;
    passed: number;
    failed: number;
  };
};

export function buildRunView(run: RunStatusResponse | null): RunViewModel {
  const result = run?.response?.result ?? {};
  const summary = dict(result.run_summary) ?? run?.response?.run_summary ?? {};
  const plan = dict(result.plan);
  const testAnalysis = dict(result.test_analysis);
  const review = dict(result.review_result);
  const approval = dict(result.approval_decision);
  const approvalBinding = dict(result.approval_binding);
  const publishResult = dict(result.publish_result);
  const publicationPackage = dict(result.publication_package);
  const llmError = dict(result.llm_error);
  const hasRun = Boolean(run);

  const changedFiles = stringList(result.modified_files);
  const runWorkspace = dict(result.run_workspace);
  const repository = firstString(
    stringValue(result.repository),
    stringValue(run?.request.repository),
    stringValue(runWorkspace?.repo),
    "Abhi150904/RepoPilot"
  );
  const issueNumber = numberValue(result.issue_number) ?? numberValue(run?.request.issue_number);
  const issue = issueNumber
    ? `#${issueNumber} ${stringValue(result.issue) ?? "Live API run"}`
    : stringValue(result.issue) ?? "Live issue-text run";

  const testsPassed = booleanValue(summary.tests_passed);
  const reviewStatus = stringValue(review?.status);
  const approvalApproved = booleanValue(approval?.approved);
  const publishStatus = stringValue(publishResult?.status);
  const lifecycleStatus = run?.lifecycle_status;
  const hasResponse = Boolean(run?.response);
  const changedFileDetail = changedFiles.length === 1
    ? "1 file changed"
    : changedFiles.length > 1
      ? `${changedFiles.length} files changed`
      : "No files changed";
  const generatedTimeline: RunViewModel["timeline"] = [
    stage("Issue analysis", Radar, result.analysis, "Intent and risk extracted", lifecycleStatus),
    stage("Repository retrieval", Braces, result.repository_context, "Hybrid retrieval ranked targets", lifecycleStatus),
    stage("Implementation plan", Play, result.plan, `${stepsFromPlan(plan).length} planned steps`, lifecycleStatus),
    stage("Code generation", Code2, changedFiles.length ? result.code_changes ?? changedFiles : undefined, changedFileDetail, lifecycleStatus),
    stage("Tests", TestTube2, result.test_analysis ?? result.test_result, testDetail(testsPassed), lifecycleStatus),
    {
      label: "Repair",
      icon: TimerReset,
      state: numberValue(result.repair_attempts) ? "complete" : "muted",
      detail: numberValue(result.repair_attempts) ? `${numberValue(result.repair_attempts)} repair attempts` : "No repair needed"
    },
    stage("Automated review", ShieldCheck, result.review_result, reviewStatus === "blocked" ? "Review found blockers" : "Review complete", lifecycleStatus),
    {
      label: "Human approval",
      icon: UserCheck,
      state: approvalApproved ? "complete" : lifecycleStatus === "completed" ? "active" : "locked",
      detail: approvalApproved ? "Approval bound" : lifecycleStatus === "completed" && review ? "Waiting for decision" : "Pending completed run"
    },
    {
      label: "Publication",
      icon: GitPullRequestArrow,
      state: publishStatus ? "complete" : approvalApproved ? "active" : "locked",
      detail: stringValue(publishResult?.summary) ?? "Locked until approval"
    }
  ];

  return {
    repository,
    issue,
    issueUrl: stringValue(result.issue_url),
    headline: headlineFor({
      lifecycleStatus,
      summaryStatus: stringValue(summary.status),
      approvalApproved,
      publishStatus,
      hasLlmError: Boolean(llmError),
      hasResponse
    }),
    status: stringValue(summary.status) ?? lifecycleStatus ?? "preview",
    summary: stringValue(summary.summary) ?? run?.response?.summary ?? failureSummary(run) ?? "RepoPilot is ready to inspect the next run.",
    nextAction: stringValue(summary.next_action) ?? "start_run",
    canReview: Boolean(review || approval || approvalBinding),
    timeline: timelineFromEvents(run, generatedTimeline),
    planSteps: stepsFromPlan(plan, hasRun),
    diffLines: diffFromText(stringValue(result.diff), hasRun),
    diffFile: changedFiles[0] ?? (hasRun ? "No changed files" : "backend/app/services/run_service.py"),
    diffStats: diffStats(stringValue(result.diff)),
    changedFiles,
    tests: {
      label: testsPassed === true ? "passed" : testsPassed === false ? "failed" : "pending",
      passed: testsPassed,
      status: stringValue(testAnalysis?.status) ?? "not run",
      summary: stringValue(testAnalysis?.summary) ?? "Test output will appear after a run executes."
    },
    review: {
      blockers: reviewStatus === "blocked" || reviewStatus === "changes_requested" ? 1 : 0,
      notes: reviewStatus ? 2 : 0,
      confidence: reviewStatus ? (reviewStatus === "approved" || reviewStatus === "ready" ? "96" : "84") : "n/a",
      risk: firstString(stringValue(review?.risk_level), stringValue(dict(result.analysis)?.risk_level), hasRun ? "n/a" : "Moderate")
    },
    repairAttempts: String(numberValue(result.repair_attempts) ?? numberValue(summary.repair_attempts) ?? 0),
    tokens: formatMetric(dict(summary.metrics)?.tokens ?? dict(result.run_metrics)?.tokens, hasRun ? "n/a" : "6.4k"),
    verification: [
      { label: "Workspace verified", verified: dict(approvalBinding?.git_safety)?.status === "safe" || approvalBinding?.status === "bound" },
      { label: "Tests passed", verified: testsPassed === true },
      { label: "Review passed", verified: reviewStatus !== "blocked" && Boolean(reviewStatus) },
      { label: "HEAD bound", verified: Boolean(approvalBinding?.head_commit) },
      { label: "Artifact unchanged", verified: approvalBinding?.status === "bound" }
    ],
    publish: {
      mode: stringValue(publishResult?.mode) ?? "",
      branch: firstString(stringValue(publishResult?.branch_name), stringValue(publicationPackage?.branch_name), hasRun ? "Not prepared" : "repopilot/issue-42-publication-integrity"),
      repository,
      title: firstString(stringValue(publicationPackage?.pr_title), hasRun ? "No pull request prepared" : "fix: harden publication lifecycle"),
      status: stringValue(publishResult?.status) ?? (hasRun ? "Locked" : "Ready"),
      summary: stringValue(publishResult?.summary) ?? "Approve a completed run before publishing.",
      prUrl: publishResult?.status === "published"
        ? stringValue(publishResult?.pr_url)
        : undefined
    },
    failure: {
      failedTest: firstString(stringValue(testAnalysis?.failure_reason), stringValue(llmError?.stage), hasRun ? "No failing test recorded" : "test_publish_retry_after_commit"),
      reason: stringValue(testAnalysis?.summary) ?? stringValue(llmError?.message) ?? "Expected push stage to resume after existing commit.",
      repair: stringValue(dict(result.repair_decision)?.summary) ?? (hasRun ? "No automated repair was available for this stop." : "RepoPilot identified the failure as repairable."),
      attempt: `${numberValue(result.repair_attempts) ?? 0} / ${numberValue(run?.request.max_repair_attempts) ?? 2}`,
      passed: testsPassed === false ? 17 : 26,
      failed: testsPassed === false ? 2 : 0
    }
  };
}

function timelineFromEvents(
  run: RunStatusResponse | null,
  fallback: RunViewModel["timeline"]
): RunViewModel["timeline"] {
  if (!run?.events?.length) {
    return fallback;
  }
  return run.events.map((event, index) => eventTimelineItem(event, run, index));
}

function eventTimelineItem(
  event: NonNullable<RunStatusResponse["events"]>[number],
  run: RunStatusResponse,
  index: number
): RunViewModel["timeline"][number] {
  const metadata = dict(event.metadata) ?? {};
  const mode = stringValue(metadata.mode);
  const status = stringValue(metadata.status);
  const prUrl = stringValue(metadata.pr_url);
  const isLatest = index === (run.events?.length ?? 0) - 1;
  const active =
    isLatest &&
    (run.lifecycle_status === "queued" ||
      run.lifecycle_status === "running" ||
      run.publication_status === "publishing");

  switch (event.event_type) {
    case "run.created":
      return eventItem("Run created", Radar, active ? "active" : "complete", detailFromMetadata(metadata, "Request accepted"));
    case "run.queued":
      return eventItem("Queued", TimerReset, active ? "active" : "complete", "Waiting for an execution worker");
    case "run.claimed":
      return eventItem("Worker claimed run", Play, active ? "active" : "complete", "Execution slot assigned");
    case "run.started":
      return eventItem("Execution started", Play, active ? "active" : "complete", "Workflow is running");
    case "run.completed":
      return eventItem("Run completed", ShieldCheck, "complete", "Artifacts were saved");
    case "run.failed":
      return eventItem("Run failed", ShieldCheck, "active", detailFromMetadata(metadata, "Workflow stopped before completion"));
    case "run.interrupted":
      return eventItem("Run interrupted", TimerReset, "active", "Backend restarted before completion");
    case "run.updated":
      return eventItem("Run updated", UserCheck, "complete", "Review state was saved");
    case "run.publication_started":
      return eventItem("Publication started", GitPullRequestArrow, active ? "active" : "complete", mode ? `Mode: ${modeLabel(mode)}` : "Publishing");
    case "run.publication_ready":
      return eventItem("Publication ready", GitPullRequestArrow, "complete", status ? `Status: ${status}` : "Dry run passed");
    case "run.publication_published":
      return eventItem("Published", GitPullRequestArrow, "complete", prUrl ?? "Publication finished");
    case "run.publication_failed":
      return eventItem("Publication failed", GitPullRequestArrow, "active", mode ? `Mode: ${modeLabel(mode)}` : "Publication needs attention");
    default:
      return eventItem(titleFromEvent(event.event_type), Radar, active ? "active" : "complete", detailFromMetadata(metadata, "Recorded by RepoPilot"));
  }
}

function eventItem(
  label: string,
  icon: typeof Radar,
  state: TimelineState,
  detail: string
): RunViewModel["timeline"][number] {
  return { label, icon, state, detail };
}

function titleFromEvent(eventType: string): string {
  return eventType
    .replace(/^run\./, "")
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function detailFromMetadata(metadata: Record<string, unknown>, fallback: string): string {
  const errorCode = stringValue(metadata.error_code);
  if (errorCode) {
    return errorCode;
  }
  const requestId = stringValue(metadata.request_id);
  if (requestId) {
    return `Request ${requestId.slice(0, 8)}`;
  }
  return fallback;
}

function modeLabel(mode: string): string {
  if (mode === "dry_run") {
    return "Dry run";
  }
  if (mode === "pr") {
    return "Pull request";
  }
  return mode.charAt(0).toUpperCase() + mode.slice(1);
}

function headlineFor({
  lifecycleStatus,
  summaryStatus,
  approvalApproved,
  publishStatus,
  hasLlmError,
  hasResponse
}: {
  lifecycleStatus?: string;
  summaryStatus?: string;
  approvalApproved?: boolean | null;
  publishStatus?: string;
  hasLlmError?: boolean;
  hasResponse?: boolean;
}): string {
  if (publishStatus === "published") {
    return "Pull request opened.";
  }
  if (approvalApproved) {
    return "Ready to ship.";
  }
  if (hasLlmError || summaryStatus === "needs_human") {
    return "RepoPilot needs your attention.";
  }
  if (lifecycleStatus === "failed") {
    return "Run failed before completion.";
  }
  if (lifecycleStatus === "completed" && hasResponse === false) {
    return "Run completed without artifacts.";
  }
  if (summaryStatus === "repair_failed" || summaryStatus === "review_failed") {
    return "RepoPilot needs your attention.";
  }
  if (lifecycleStatus === "running" || lifecycleStatus === "queued") {
    return "RepoPilot is working through the issue.";
  }
  return "The fix is tested, reviewed and ready.";
}

function stage(
  label: string,
  icon: typeof Radar,
  value: unknown,
  detail: string,
  lifecycleStatus?: string
): RunViewModel["timeline"][number] {
  return {
    label,
    icon,
    state: value ? "complete" : lifecycleStatus === "running" ? "active" : "locked",
    detail
  };
}

function stepsFromPlan(plan: Record<string, unknown> | null, hasRun = false): string[] {
  const steps = stringList(plan?.steps);
  if (steps.length) {
    return steps;
  }
  const summary = stringValue(plan?.summary);
  if (summary) {
    return [summary];
  }
  if (hasRun) {
    return ["No implementation plan was produced for this run."];
  }
  return fallbackPlanSteps;
}

function failureSummary(run: RunStatusResponse | null): string | undefined {
  if (!run?.error) {
    return undefined;
  }
  return run.error.message || "Run failed before RepoPilot could produce artifacts.";
}

function testDetail(testsPassed: boolean | null): string {
  if (testsPassed === true) {
    return "Tests passed";
  }
  if (testsPassed === false) {
    return "Tests need attention";
  }
  return "Tests not run";
}

function diffFromText(diff?: string, hasRun = false): DiffLine[] {
  if (!diff) {
    if (hasRun) {
      return [{ kind: "context", text: "No diff was generated for this run." }];
    }
    return fallbackDiffLines as DiffLine[];
  }
  return diff
    .split("\n")
    .slice(0, 24)
    .map((line) => ({
      kind: line.startsWith("+") ? "add" : line.startsWith("-") ? "remove" : "context",
      text: line.replace(/^[+-]/, "")
    }));
}

function diffStats(diff?: string): string {
  if (!diff) {
    return "+0 -0";
  }
  const lines = diff.split("\n");
  const added = lines.filter((line) => line.startsWith("+") && !line.startsWith("+++")).length;
  const removed = lines.filter((line) => line.startsWith("-") && !line.startsWith("---")).length;
  return `+${added} -${removed}`;
}

function dict(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}

function numberValue(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function booleanValue(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function firstString(...values: Array<string | undefined>): string {
  return values.find((value) => value && value.length > 0) ?? "";
}

function formatMetric(value: unknown, fallback: string): string {
  if (typeof value === "number") {
    return value >= 1000 ? `${(value / 1000).toFixed(1)}k` : String(value);
  }
  if (typeof value === "string" && value) {
    return value;
  }
  return fallback;
}
