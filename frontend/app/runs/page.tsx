"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { ButtonLink } from "@/components/button";
import { listRuns } from "@/lib/api";
import { stageForStatus, summariesFromRuns, type StoredRunSummary } from "@/lib/run-history";

const filters = ["All", "Running", "Needs review", "Completed", "Failed"];

export default function RunsPage() {
  const [runs, setRuns] = useState<StoredRunSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [filter, setFilter] = useState("All");

  useEffect(() => {
    let active = true;
    async function loadRuns() {
      setIsLoading(true);
      try {
        const backendRuns = await listRuns();
        if (active) {
          setRuns(summariesFromRuns(backendRuns));
          setLoadError(null);
        }
      } catch (caught) {
        if (active) {
          setRuns([]);
          setLoadError(caught instanceof Error ? caught.message : "Could not load runs from the API.");
        }
      } finally {
        if (active) {
          setIsLoading(false);
        }
      }
    }
    loadRuns();
    return () => {
      active = false;
    };
  }, []);

  const visibleRuns = useMemo(() => {
    if (filter === "All") {
      return runs;
    }
    if (filter === "Needs review") {
      return runs.filter((run) => run.status === "completed");
    }
    return runs.filter((run) => run.status.toLowerCase() === filter.toLowerCase());
  }, [filter, runs]);

  return (
    <AppShell>
      <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)]">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[var(--border)] px-5 py-4">
          <div>
            <p className="font-display text-xs uppercase text-[var(--text-secondary)]">Runs</p>
            <h1 className="mt-1 font-display text-2xl font-semibold">Engineering run history</h1>
          </div>
          <div className="flex flex-wrap gap-2">
            {filters.map((item) => (
              <button
                key={item}
                className={item === filter ? "rounded-lg border border-cyan-300/40 bg-cyan-300/10 px-3 py-2 text-sm text-cyan-200" : "rounded-lg border border-[var(--border)] px-3 py-2 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)]"}
                onClick={() => setFilter(item)}
              >
                {item}
              </button>
            ))}
          </div>
        </div>
        <div className="overflow-x-auto">
          <div className="grid min-w-[900px] grid-cols-[1fr_120px_140px_110px_100px_100px_170px] border-b border-[var(--border)] px-5 py-3 font-display text-xs uppercase text-[var(--text-secondary)]">
            <span>Repository</span>
            <span>Issue</span>
            <span>Current stage</span>
            <span>Status</span>
            <span>Tests</span>
            <span>Duration</span>
            <span>Updated</span>
          </div>
          {isLoading ? (
            <div className="px-5 py-10">
              <p className="text-sm text-[var(--text-secondary)]">Loading run history...</p>
            </div>
          ) : null}
          {!isLoading && loadError ? (
            <div className="px-5 py-10">
              <p className="text-sm text-red-300">Could not load run history.</p>
              <p className="mt-2 text-sm text-[var(--text-secondary)]">{loadError}</p>
            </div>
          ) : null}
          {visibleRuns.map((run) => (
            <Link key={run.runId} href={`/runs/${run.runId}`} className="grid min-w-[900px] grid-cols-[1fr_120px_140px_110px_100px_100px_170px] border-b border-[var(--border)] px-5 py-4 text-sm hover:bg-[var(--surface-elevated)]">
              <span>{run.repository}</span>
              <span className="text-[var(--text-secondary)]">{run.issue}</span>
              <span>{stageForStatus(run.status)}</span>
              <span className="text-[var(--text-secondary)]">{run.status}</span>
              <span className="text-[var(--text-secondary)]">{run.tests}</span>
              <span className="text-[var(--text-secondary)]">{run.duration}</span>
              <span className="text-[var(--text-secondary)]">{new Date(run.updatedAt).toLocaleString()}</span>
            </Link>
          ))}
          {!isLoading && !loadError && !visibleRuns.length ? (
            <div className="px-5 py-10">
              <p className="text-sm text-[var(--text-secondary)]">No runs yet. Start your first RepoPilot run to see its execution history here.</p>
              <ButtonLink className="mt-4" href="/app" variant="primary">Start a run</ButtonLink>
            </div>
          ) : null}
        </div>
      </section>
    </AppShell>
  );
}
