"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, Check } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { pollResource } from "@/lib/poll-resource";
import { RunLauncher } from "@/components/run-launcher";
import { listRuns } from "@/lib/api";
import { summariesFromRuns, type StoredRunSummary } from "@/lib/run-history";

export default function CommandCenterPage() {
  const [history, setHistory] = useState<StoredRunSummary[]>([]);
  const [isLoadingHistory, setIsLoadingHistory] = useState(true);
  const [historyError, setHistoryError] = useState<string | null>(null);

  useEffect(() => {
    setIsLoadingHistory(true);
    return pollResource({
      load: (signal) => listRuns(signal),
      onData: (backendRuns) => {
        setHistory(summariesFromRuns(backendRuns));
        setHistoryError(null);
        setIsLoadingHistory(false);
      },
      onError: (caught) => {
        setHistoryError(caught instanceof Error ? caught.message : "Could not load runs from the API.");
        setIsLoadingHistory(false);
      }
    });
  }, []);

  const needsAttention = history.filter((run) => run.needsAttention);

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
          <RunLauncher />
        </section>
        <section className="grid gap-4 xl:grid-cols-[1fr_1fr]">
          <AttentionPanel runs={needsAttention} isLoading={isLoadingHistory} />
          <ActivePanel runs={history.filter((run) => ["queued", "running"].includes(run.status))} isLoading={isLoadingHistory} />
        </section>
        <RecentRuns runs={history} error={historyError} isLoading={isLoadingHistory} />
      </div>
    </AppShell>
  );
}

function AttentionPanel({ runs, isLoading }: { runs: StoredRunSummary[]; isLoading: boolean }) {
  return (
    <section className="rounded-xl border border-cyan-400/25 bg-[var(--surface)] p-5">
      <p className="font-display text-xs uppercase text-cyan-300">Needs your attention</p>
      <h2 className="mt-2 font-display text-3xl font-semibold">{isLoading ? "Checking run queue..." : runs.length ? `${runs.length} runs need your attention` : "You're all caught up."}</h2>
      <div className="mt-5 grid gap-3">
        {isLoading ? <PanelSkeleton /> : null}
        {!isLoading && (runs.length ? runs : [{ runId: "empty", repository: "No reviewed runs waiting", issue: "Runs waiting for approval or human inspection will appear here.", status: "empty", statusLabel: "empty", stage: "Idle", tests: "—", duration: "n/a", updatedAt: "", needsAttention: false, attentionLabel: "", attentionAction: "inspect" as const }]).map((run) => (
          <div key={run.runId} className="rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <strong className="block">{run.repository}</strong>
                <span className="text-sm text-[var(--text-secondary)]">{run.issue}</span>
              </div>
              {run.runId !== "empty" ? (
                <Link className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:border-cyan-300" href={run.attentionAction === "review" ? `/runs/${run.runId}/review` : `/runs/${run.runId}`}>
                  {run.attentionAction === "review" ? "Review" : "Inspect"}
                  <ArrowRight size={15} />
                </Link>
              ) : null}
            </div>
            {run.runId !== "empty" ? <p className="mt-3 text-sm text-[var(--text-secondary)]"><Check className="mr-1 inline text-lime-300" size={15} />{run.attentionLabel}</p> : null}
          </div>
        ))}
      </div>
    </section>
  );
}

function ActivePanel({ runs, isLoading }: { runs: StoredRunSummary[]; isLoading: boolean }) {
  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
      <p className="font-display text-xs uppercase text-[var(--text-secondary)]">Active engineering</p>
      <div className="mt-4 grid gap-3">
        {isLoading ? <PanelSkeleton /> : null}
        {!isLoading && (runs.length ? runs : [{ runId: "empty", repository: "No runs in progress", issue: "Start a run to watch RepoPilot work.", status: "idle", statusLabel: "idle", stage: "Idle", tests: "—", duration: "n/a", updatedAt: "", needsAttention: false, attentionLabel: "", attentionAction: "inspect" as const }]).map((run) => (
          <div key={run.runId} className="flex items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] p-3">
            <span>
              <strong className="block text-sm">{run.repository}</strong>
              <small className="text-[var(--text-secondary)]">{run.issue}</small>
            </span>
            <span className="rounded-full bg-cyan-400/10 px-2 py-1 text-xs text-cyan-200">{run.statusLabel}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function RecentRuns({ runs, error, isLoading }: { runs: StoredRunSummary[]; error: string | null; isLoading: boolean }) {
  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)]">
      <div className="border-b border-[var(--border)] px-5 py-4">
        <h2 className="font-display text-lg font-semibold">Recent runs</h2>
      </div>
      <div className="divide-y divide-[var(--border)]">
        {isLoading ? (
          <div className="grid gap-3 px-5 py-5">
            <SkeletonLine className="h-4 w-2/3" />
            <SkeletonLine className="h-4 w-1/2" />
            <SkeletonLine className="h-4 w-3/5" />
          </div>
        ) : null}
        {!isLoading && error ? (
          <div className="px-5 py-8">
            <p className="text-sm text-red-300">Could not load recent runs.</p>
            <p className="mt-2 text-sm text-[var(--text-secondary)]">{error}</p>
          </div>
        ) : null}
        {!isLoading && !error && (runs.length ? runs : []).map((run) => (
          <Link key={run.runId} href={`/runs/${run.runId}`} className="grid gap-3 px-5 py-4 text-sm hover:bg-[var(--surface-elevated)] md:grid-cols-[1fr_120px_160px]">
            <span>{run.repository} <small className="text-[var(--text-secondary)]">{run.issue}</small></span>
            <span className="text-[var(--text-secondary)]">{run.statusLabel}</span>
            <span className="text-[var(--text-secondary)]">{run.updatedAt ? new Date(run.updatedAt).toLocaleString() : ""}</span>
          </Link>
        ))}
        {!isLoading && !error && !runs.length ? (
          <div className="px-5 py-8">
            <p className="text-sm text-[var(--text-secondary)]">No runs yet. Create your first run to build your execution history.</p>
            <Link className="mt-3 inline-flex text-sm font-medium text-cyan-300 hover:text-cyan-200" href="/app">Start a run</Link>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function PanelSkeleton() {
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] p-4">
      <SkeletonLine className="h-5 w-2/3" />
      <SkeletonLine className="mt-3 h-4 w-1/2" />
    </div>
  );
}

function SkeletonLine({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-white/10 ${className}`} />;
}
