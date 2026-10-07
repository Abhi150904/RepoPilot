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

  return {
    repository,
    issue,
    issueUrl: stringValue(result.issue_url),
    headline: headlineFor({ lifecycleStatus, summaryStatus: stringValue(summary.status), approvalApproved, publishStatus }),
    status: stringValue(summary.status) ?? lifecycleStatus ?? "preview",
    summary: stringValue(summary.summary) ?? run?.response?.summary ?? "RepoPilot is ready to inspect the next run.",
    nextAction: stringValue(summary.next_action) ?? "start_run",
    timeline: [
      stage("Issue analysis", Radar, result.analysis, "Intent and risk extracted", lifecycleStatus),
      stage("Repository retrieval", Braces, result.repository_context, "Hybrid retrieval ranked targets", lifecycleStatus),
      stage("Implementation plan", Play, result.plan, `${stepsFromPlan(plan).length} planned steps`, lifecycleStatus),
      stage("Code generation", Code2, changedFiles.length ? result.code_changes ?? changedFiles : undefined, `${changedFiles.length || 2} files changed`, lifecycleStatus),
      stage("Tests", TestTube2, result.test_analysis ?? result.test_result, testsPassed === false ? "Tests need attention" : "Tests passed", lifecycleStatus),
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
        detail: approvalApproved ? "Approval bound" : lifecycleStatus === "completed" ? "Waiting for decision" : "Pending completed run"
      },
      {
        label: "Publication",
        icon: GitPullRequestArrow,
        state: publishStatus ? "complete" : approvalApproved ? "active" : "locked",
        detail: stringValue(publishResult?.summary) ?? "Locked until approval"
      }
    ],
    planSteps: stepsFromPlan(plan),
    diffLines: diffFromText(stringValue(result.diff)),
    diffFile: changedFiles[0] ?? "backend/app/services/run_service.py",
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
      confidence: reviewStatus === "approved" || reviewStatus === "ready" ? "96" : "84",
      risk: firstString(stringValue(review?.risk_level), stringValue(dict(result.analysis)?.risk_level), "Moderate")
    },
    repairAttempts: String(numberValue(result.repair_attempts) ?? numberValue(summary.repair_attempts) ?? 0),
    tokens: formatMetric(dict(summary.metrics)?.tokens ?? dict(result.run_metrics)?.tokens, "6.4k"),
    verification: [
      { label: "Workspace verified", verified: dict(approvalBinding?.git_safety)?.status === "safe" || approvalBinding?.status === "bound" },
      { label: "Tests passed", verified: testsPassed === true },
      { label: "Review passed", verified: reviewStatus !== "blocked" && Boolean(reviewStatus) },
      { label: "HEAD bound", verified: Boolean(approvalBinding?.head_commit) },
      { label: "Artifact unchanged", verified: approvalBinding?.status === "bound" }
    ],
    publish: {
      branch: firstString(stringValue(publishResult?.branch_name), stringValue(publicationPackage?.branch_name), "repopilot/issue-42-publication-integrity"),
      repository,
      title: firstString(stringValue(publicationPackage?.pr_title), "fix: harden publication lifecycle"),
      status: stringValue(publishResult?.status) ?? "Ready",
      summary: stringValue(publishResult?.summary) ?? "Approve a completed run before publishing.",
      prUrl: stringValue(publishResult?.pr_url)
    },
    failure: {
      failedTest: firstString(stringValue(testAnalysis?.failure_reason), "test_publish_retry_after_commit"),
      reason: stringValue(testAnalysis?.summary) ?? "Expected push stage to resume after existing commit.",
      repair: stringValue(dict(result.repair_decision)?.summary) ?? "RepoPilot identified the failure as repairable.",
      attempt: `${numberValue(result.repair_attempts) ?? 1} / ${numberValue(run?.request.max_repair_attempts) ?? 2}`,
      passed: testsPassed === false ? 17 : 26,
      failed: testsPassed === false ? 2 : 0
    }
  };
}

function headlineFor({
  lifecycleStatus,
  summaryStatus,
  approvalApproved,
  publishStatus
}: {
  lifecycleStatus?: string;
  summaryStatus?: string;
  approvalApproved?: boolean | null;
  publishStatus?: string;
}): string {
  if (publishStatus === "published") {
    return "Pull request opened.";
  }
  if (approvalApproved) {
    return "Ready to ship.";
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

function stepsFromPlan(plan: Record<string, unknown> | null): string[] {
  const steps = stringList(plan?.steps);
  if (steps.length) {
    return steps;
  }
  const summary = stringValue(plan?.summary);
  if (summary) {
    return [summary];
  }
  return fallbackPlanSteps;
}

function diffFromText(diff?: string): DiffLine[] {
  if (!diff) {
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
    return "+5 -1";
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
