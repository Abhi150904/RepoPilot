import type { RunRequest } from "@/lib/api";

export type QuickRunMode = "github" | "issue";

export type QuickRunForm = {
  mode: QuickRunMode;
  repository: string;
  issueNumber: string;
  issueText: string;
  applyChanges: boolean;
  runTests: boolean;
  maxRepairAttempts: string;
};

export function buildRunRequest(form: QuickRunForm): RunRequest | { error: string } {
  const repairAttempts = Number(form.maxRepairAttempts);
  if (!Number.isInteger(repairAttempts) || repairAttempts < 0) {
    return { error: "Max repair attempts must be zero or greater." };
  }
  if (form.mode === "issue") {
    if (!form.issueText.trim()) {
      return { error: "Issue text is required." };
    }
    return { issue: form.issueText.trim(), max_repair_attempts: repairAttempts };
  }
  if (!/^[^/\s]+\/[^/\s]+$/.test(form.repository.trim())) {
    return { error: "Repository must use owner/name format." };
  }
  const parsedIssue = Number(form.issueNumber);
  if (!Number.isInteger(parsedIssue) || parsedIssue < 1) {
    return { error: "Issue number must be at least 1." };
  }
  return {
    repository: form.repository.trim(),
    issue_number: parsedIssue,
    apply_changes: form.applyChanges,
    run_tests: form.runTests,
    max_repair_attempts: repairAttempts
  };
}
