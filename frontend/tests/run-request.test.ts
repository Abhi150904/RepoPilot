import { describe, expect, it } from "vitest";
import { buildRunRequest } from "@/lib/run-request";

describe("buildRunRequest", () => {
  it("builds a GitHub issue run request", () => {
    expect(
      buildRunRequest({
        mode: "github",
        repository: " Abhi150904/RepoPilot ",
        issueNumber: "42",
        issueText: "",
        applyChanges: true,
        runTests: true,
        maxRepairAttempts: "2"
      })
    ).toEqual({
      repository: "Abhi150904/RepoPilot",
      issue_number: 42,
      apply_changes: true,
      run_tests: true,
      max_repair_attempts: 2
    });
  });

  it("rejects invalid GitHub repository format", () => {
    expect(
      buildRunRequest({
        mode: "github",
        repository: "RepoPilot",
        issueNumber: "42",
        issueText: "",
        applyChanges: true,
        runTests: true,
        maxRepairAttempts: "2"
      })
    ).toEqual({ error: "Repository must use owner/name format." });
  });

  it("builds issue-text runs without apply or test flags", () => {
    expect(
      buildRunRequest({
        mode: "issue",
        repository: "",
        issueNumber: "",
        issueText: " Login endpoint fails ",
        applyChanges: true,
        runTests: true,
        maxRepairAttempts: "1"
      })
    ).toEqual({
      issue: "Login endpoint fails",
      max_repair_attempts: 1
    });
  });

  it("rejects blank issue text", () => {
    expect(
      buildRunRequest({
        mode: "issue",
        repository: "",
        issueNumber: "",
        issueText: " ",
        applyChanges: false,
        runTests: false,
        maxRepairAttempts: "0"
      })
    ).toEqual({ error: "Issue text is required." });
  });
});
