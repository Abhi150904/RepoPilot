"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { GitBranch } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { ButtonLink } from "@/components/button";
import { readRunHistory, type StoredRunSummary } from "@/lib/run-history";

type RepositorySummary = {
  name: string;
  latestRun: StoredRunSummary;
  runCount: number;
};

export default function RepositoriesPage() {
  const [runs, setRuns] = useState<StoredRunSummary[]>([]);

  useEffect(() => {
    setRuns(readRunHistory());
  }, []);

  const repositories = useMemo(() => summarizeRepositories(runs), [runs]);

  return (
    <AppShell>
      <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)]">
        <div className="border-b border-[var(--border)] px-5 py-4">
          <p className="font-display text-xs uppercase text-[var(--text-secondary)]">Repositories</p>
          <h1 className="mt-1 font-display text-2xl font-semibold">Connected workspaces</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--text-secondary)]">
            Repositories appear here after you start runs from GitHub issues.
          </p>
        </div>
        {repositories.length ? (
          <div className="grid gap-3 p-5 md:grid-cols-2 xl:grid-cols-3">
            {repositories.map((repository) => (
              <article key={repository.name} className="rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-display text-xs uppercase text-[var(--text-secondary)]">Repository</p>
                    <h2 className="mt-2 font-display text-lg font-semibold">{repository.name}</h2>
                  </div>
                  <GitBranch className="text-cyan-300" size={19} />
                </div>
                <dl className="mt-5 grid gap-3 text-sm">
                  <div className="flex justify-between gap-4 border-b border-[var(--border)] pb-3">
                    <dt className="text-[var(--text-secondary)]">Runs</dt>
                    <dd>{repository.runCount}</dd>
                  </div>
                  <div className="flex justify-between gap-4 border-b border-[var(--border)] pb-3">
                    <dt className="text-[var(--text-secondary)]">Latest status</dt>
                    <dd>{repository.latestRun.status}</dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt className="text-[var(--text-secondary)]">Latest issue</dt>
                    <dd>{repository.latestRun.issue}</dd>
                  </div>
                </dl>
                <Link className="mt-5 inline-flex text-sm font-medium text-cyan-300 hover:text-cyan-200" href={`/runs/${repository.latestRun.runId}`}>
                  Open latest run
                </Link>
              </article>
            ))}
          </div>
        ) : (
          <div className="p-5">
            <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] p-5">
              <h2 className="font-display text-lg font-semibold">No repositories yet.</h2>
              <p className="mt-2 max-w-xl text-sm leading-6 text-[var(--text-secondary)]">
                Start a GitHub issue run and RepoPilot will list the repository here with its latest run status.
              </p>
              <ButtonLink className="mt-4" href="/app" variant="primary">Start a run</ButtonLink>
            </div>
          </div>
        )}
      </section>
    </AppShell>
  );
}

function summarizeRepositories(runs: StoredRunSummary[]): RepositorySummary[] {
  const summaries = new Map<string, RepositorySummary>();
  for (const run of runs) {
    if (!run.repository || run.repository === "Issue text") {
      continue;
    }
    const existing = summaries.get(run.repository);
    if (existing) {
      existing.runCount += 1;
      continue;
    }
    summaries.set(run.repository, {
      name: run.repository,
      latestRun: run,
      runCount: 1
    });
  }
  return [...summaries.values()];
}
