import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RunLauncher } from "@/components/run-launcher";
import { createRun, getAuthMe, getRunUsage, RepoPilotApiError, type RunUsage } from "@/lib/api";

// Retain hook state across explicit renders without introducing a browser test dependency.
const hooks = vi.hoisted(() => ({ slots: [] as unknown[], index: 0, push: vi.fn() }));
vi.mock("react", async (original) => ({
  ...await original<typeof import("react")>(),
  useState: (initial: unknown) => {
    const index = hooks.index++;
    if (!(index in hooks.slots)) hooks.slots[index] = initial;
    return [hooks.slots[index], (value: unknown) => { hooks.slots[index] = value; }];
  },
  useRef: (initial: unknown) => {
    const index = hooks.index++;
    if (!(index in hooks.slots)) hooks.slots[index] = { current: initial };
    return hooks.slots[index];
  },
  useCallback: (callback: unknown) => callback,
  useEffect: () => {},
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: hooks.push }) }));
vi.mock("@/lib/api", async (original) => ({
  ...await original<typeof import("@/lib/api")>(),
  createRun: vi.fn(), getAuthMe: vi.fn(), getRunUsage: vi.fn(),
}));

const usage: RunUsage = { enforced: true, introductory: { total: 2, used: 2, reserved: 0, remaining: 0 },
  run_credits: 1, billing_enabled: false };

function render() {
  hooks.index = 0;
  return RunLauncher().props;
}

async function ready() {
  render().onRefresh();
  await vi.waitFor(() => expect(render().loading).toBe(false));
  render().onRepository("owner/repo");
  render().onIssueNumber("42");
}

async function submit() {
  render().onStart();
  await vi.waitFor(() => expect(render().busy).toBe(false));
}

describe("real run submission and recovery", () => {
  beforeEach(() => {
    hooks.slots = [];
    vi.clearAllMocks();
    vi.stubGlobal("React", React);
    vi.mocked(getAuthMe).mockResolvedValue({ authenticated: true });
    vi.mocked(getRunUsage).mockReset().mockResolvedValue(usage);
    vi.mocked(createRun).mockReset().mockResolvedValue({ run_id: "run-1", lifecycle_status: "queued", request: {} });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("submits the unchanged AI contract once and refreshes usage before navigation", async () => {
    await ready();
    render().onStart();
    render().onStart();
    await vi.waitFor(() => expect(hooks.push).toHaveBeenCalledWith("/runs/run-1"));
    expect(createRun).toHaveBeenCalledTimes(1);
    expect(createRun).toHaveBeenCalledWith({ repository: "owner/repo", issue_number: 42,
      apply_changes: true, run_tests: true, max_repair_attempts: 2 }, expect.any(String));
    expect(getRunUsage).toHaveBeenCalledTimes(2);
    expect(vi.mocked(getRunUsage).mock.invocationCallOrder[1]).toBeLessThan(hooks.push.mock.invocationCallOrder[0]);
    expect(render().retryPending).toBe(false);
  });

  it.each([0, 500])("replays an ambiguous %s outcome with the same key even after the last credit is reserved", async (status) => {
    await ready();
    vi.mocked(createRun).mockRejectedValueOnce(new RepoPilotApiError({ status, code: "unavailable", message: "Try again" }));
    vi.mocked(getRunUsage).mockResolvedValue({ ...usage, run_credits: 0 });
    await submit();
    const key = vi.mocked(createRun).mock.calls[0][1];
    expect(render().retryPending).toBe(true);
    expect(render().error).toBe("Try again");
    expect(getRunUsage).toHaveBeenCalledTimes(2);
    await submit();
    expect(vi.mocked(createRun).mock.calls[1][1]).toBe(key);
    expect(hooks.push).toHaveBeenCalledWith("/runs/run-1");
  });

  it("only bypasses exhaustion for the same pending payload", async () => {
    await ready();
    vi.mocked(createRun).mockRejectedValueOnce(new Error("Network outcome unknown"));
    vi.mocked(getRunUsage).mockResolvedValue({ ...usage, run_credits: 0 });
    await submit();
    render().onIssueNumber("43");
    expect(render().retryPending).toBe(false);
    await submit();
    expect(createRun).toHaveBeenCalledTimes(1);
    render().onIssueNumber("42");
    expect(render().retryPending).toBe(true);
    await submit();
    expect(createRun).toHaveBeenCalledTimes(2);
  });

  it("uses a fresh key after a definitive client rejection", async () => {
    await ready();
    vi.mocked(createRun).mockRejectedValueOnce(new RepoPilotApiError({ status: 422, code: "invalid", message: "Invalid issue" }));
    await submit();
    expect(render().retryPending).toBe(false);
    await submit();
    expect(vi.mocked(createRun).mock.calls[1][1]).not.toBe(vi.mocked(createRun).mock.calls[0][1]);
  });

  it("uses a fresh key for a changed payload when credits remain", async () => {
    await ready();
    vi.mocked(createRun).mockRejectedValueOnce(new Error("Network outcome unknown"));
    await submit();
    render().onIssueNumber("43");
    await submit();
    expect(vi.mocked(createRun).mock.calls[1][1]).not.toBe(vi.mocked(createRun).mock.calls[0][1]);
  });

  it("can recover a pending request when usage refresh itself fails", async () => {
    await ready();
    vi.mocked(createRun).mockRejectedValueOnce(new Error("Network outcome unknown"));
    vi.mocked(getRunUsage).mockRejectedValue(new Error("Usage unavailable"));
    await submit();
    expect(render().usage).toBeNull();
    expect(render().retryPending).toBe(true);
    await submit();
    expect(hooks.push).toHaveBeenCalledWith("/runs/run-1");
  });
});
