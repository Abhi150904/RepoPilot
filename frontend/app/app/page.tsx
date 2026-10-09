"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, Check, Play } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/button";
import { createRun, listRuns, type RunRequest } from "@/lib/api";
import { buildRunRequest } from "@/lib/run-request";
import { summaryFromRun, summariesFromRuns, type StoredRunSummary } from "@/lib/run-history";

export default function CommandCenterPage() {
  const [history, setHistory] = useState<StoredRunSummary[]>([]);
  const [isStarting, setIsStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [repository, setRepository] = useState("");
  const [issueNumber, setIssueNumber] = useState("");

  useEffect(() => {
    let active = true;
    async function loadRuns() {
      try {
        const backendRuns = await listRuns();
        if (active) {
          setHistory(summariesFromRuns(backendRuns));
          setHistoryError(null);
        }
      } catch (caught) {
        if (active) {
          setHistory([]);
          setHistoryError(caught instanceof Error ? caught.message : "Could not load runs from the API.");
        }
      }
    }
    loadRuns();
    return () => {
      active = false;
    };
  }, []);

  async function startRun() {
    const request = buildRunRequest({
      mode: "github",
      repository,
      issueNumber,
      issueText: "",
      applyChanges: true,
      runTests: true,
      maxRepairAttempts: "2"
    });
    if ("error" in request) {
      setError(request.error);
      return;
    }
    await runRequest(request);
  }

  async function runRequest(request: RunRequest) {
    setIsStarting(true);
    setError(null);
    try {
      const run = await createRun(request);
      setHistory((current) => [summaryFromRun(run), ...current.filter((item) => item.runId !== run.run_id)]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not start run.");
    } finally {
      setIsStarting(false);
    }
  }

  const needsAttention = history.filter((run) => ["completed", "failed"].includes(run.status));

  return (
    <AppShell>
      <div className="grid gap-6">
        <section className="grid gap-4 xl:grid-cols-[1fr_380px]">
          <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6">
            <p className="font-display text-xs uppercase text-cyan-300">Command Center</p>
            <h1 className="mt-3 font-display text-3xl font-semibold tracking-tight">RepoPilot is ready.</h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-[var(--text-secondary)]">
              Start a scoped run, review completed work and keep autonomous engineering under human control.
            </p>
          </div>
          <QuickRunCard
            repository={repository}
            issueNumber={issueNumber}
            isStarting={isStarting}
            error={error}
            onRepository={setRepository}
            onIssueNumber={setIssueNumber}
            onStart={startRun}
          />
        </section>
        <section className="grid gap-4 xl:grid-cols-[1fr_1fr]">
          <AttentionPanel runs={needsAttention} />
          <ActivePanel runs={history.filter((run) => ["queued", "running"].includes(run.status))} />
        </section>
        <RecentRuns runs={history} error={historyError} />
      </div>
    </AppShell>
  );
}

function QuickRunCard({
  repository,
  issueNumber,
  isStarting,
  error,
  onRepository,
  onIssueNumber,
  onStart
}: {
  repository: string;
  issueNumber: string;
  isStarting: boolean;
  error: string | null;
  onRepository: (value: string) => void;
  onIssueNumber: (value: string) => void;
  onStart: () => void;
}) {
  return (
    <section className="rounded-xl border border-cyan-300/35 bg-cyan-400/[0.04] p-5 shadow-[0_0_34px_rgba(56,189,248,0.08)]">
      <div className="flex items-center gap-2">
        <Play size={18} className="text-cyan-300" />
        <h2 className="font-display text-lg font-semibold">Quick Run</h2>
      </div>
      <p className="mt-2 text-sm text-[var(--text-secondary)]">Start a focused GitHub issue run and track it through review.</p>
      <div className="mt-4 grid gap-3">
        <label className="grid gap-2 text-sm">
          <span className="text-[var(--text-secondary)]">Repository</span>
          <input className="min-h-10 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 outline-none focus:border-cyan-300" value={repository} onChange={(event) => onRepository(event.target.value)} placeholder="owner/repo" />
        </label>
        <label className="grid gap-2 text-sm">
          <span className="text-[var(--text-secondary)]">Issue number</span>
          <input className="min-h-10 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 outline-none focus:border-cyan-300" value={issueNumber} onChange={(event) => onIssueNumber(event.target.value)} type="number" min="1" />
        </label>
      </div>
      <Button className="mt-4 w-full !bg-cyan-300/15 !text-white hover:!bg-cyan-300/25" variant="primary" disabled={isStarting} onClick={onStart}>
        {isStarting ? "Starting..." : "Start RepoPilot"}
      </Button>
      {error ? <p className="mt-3 text-sm text-red-300">{error}</p> : null}
    </section>
  );
}

function AttentionPanel({ runs }: { runs: StoredRunSummary[] }) {
  return (
    <section className="rounded-xl border border-cyan-400/25 bg-[var(--surface)] p-5">
      <p className="font-display text-xs uppercase text-cyan-300">Needs your attention</p>
      <h2 className="mt-2 font-display text-3xl font-semibold">{runs.length ? `${runs.length} runs need your attention` : "You're all caught up."}</h2>
      <div className="mt-5 grid gap-3">
        {(runs.length ? runs : [{ runId: "empty", repository: "No reviewed runs waiting", issue: "Completed runs that need your approval will appear here.", status: "empty", tests: "—", duration: "n/a", updatedAt: "" }]).map((run) => (
          <div key={run.runId} className="rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <strong className="block">{run.repository}</strong>
                <span className="text-sm text-[var(--text-secondary)]">{run.issue}</span>
              </div>
              {run.runId !== "empty" ? (
                <Link className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:border-cyan-300" href={`/runs/${run.runId}/review`}>
                  Review
                  <ArrowRight size={15} />
                </Link>
              ) : null}
            </div>
            {run.runId !== "empty" ? <p className="mt-3 text-sm text-[var(--text-secondary)]"><Check className="mr-1 inline text-lime-300" size={15} />Ready for approval</p> : null}
          </div>
        ))}
      </div>
    </section>
  );
}

function ActivePanel({ runs }: { runs: StoredRunSummary[] }) {
  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
      <p className="font-display text-xs uppercase text-[var(--text-secondary)]">Active engineering</p>
      <div className="mt-4 grid gap-3">
        {(runs.length ? runs : [{ runId: "empty", repository: "No runs in progress", issue: "Start a run to watch RepoPilot work.", status: "idle", tests: "—", duration: "n/a", updatedAt: "" }]).map((run) => (
          <div key={run.runId} className="flex items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] p-3">
            <span>
              <strong className="block text-sm">{run.repository}</strong>
              <small className="text-[var(--text-secondary)]">{run.issue}</small>
            </span>
            <span className="rounded-full bg-cyan-400/10 px-2 py-1 text-xs text-cyan-200">{run.status}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function RecentRuns({ runs, error }: { runs: StoredRunSummary[]; error: string | null }) {
  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)]">
      <div className="border-b border-[var(--border)] px-5 py-4">
        <h2 className="font-display text-lg font-semibold">Recent runs</h2>
      </div>
      <div className="divide-y divide-[var(--border)]">
        {error ? (
          <div className="px-5 py-8">
            <p className="text-sm text-red-300">Could not load recent runs.</p>
            <p className="mt-2 text-sm text-[var(--text-secondary)]">{error}</p>
          </div>
        ) : null}
        {!error && (runs.length ? runs : []).map((run) => (
          <Link key={run.runId} href={`/runs/${run.runId}`} className="grid gap-3 px-5 py-4 text-sm hover:bg-[var(--surface-elevated)] md:grid-cols-[1fr_120px_160px]">
            <span>{run.repository} <small className="text-[var(--text-secondary)]">{run.issue}</small></span>
            <span className="text-[var(--text-secondary)]">{run.status}</span>
            <span className="text-[var(--text-secondary)]">{run.updatedAt ? new Date(run.updatedAt).toLocaleString() : ""}</span>
          </Link>
        ))}
        {!error && !runs.length ? (
          <div className="px-5 py-8">
            <p className="text-sm text-[var(--text-secondary)]">No runs yet. Create your first run to build your execution history.</p>
            <Link className="mt-3 inline-flex text-sm font-medium text-cyan-300 hover:text-cyan-200" href="/app">Start a run</Link>
          </div>
        ) : null}
      </div>
    </section>
  );
}
