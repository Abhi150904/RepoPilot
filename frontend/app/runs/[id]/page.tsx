"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { ArtifactWorkspace, RunIntelligence, RunTimeline } from "@/components/run-panels";
import { ButtonLink } from "@/components/button";
import { getRun, type RunStatusResponse } from "@/lib/api";
import { buildRunView } from "@/lib/run-view-model";
import { pollResource, runNeedsRefresh } from "@/lib/poll-resource";

export default function RunDetailPage({ params }: { params: { id: string } }) {
  const [run, setRun] = useState<RunStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isLoading = !run && !error;
  const view = useMemo(() => buildRunView(run), [run]);
  const canOpenReview = view.canReview && view.tests.passed === true;

  useEffect(() => {
    setRun(null);
    setError(null);
    return pollResource({
      load: (signal) => getRun(params.id, signal),
      onData: (response) => {
        setRun(response);
        setError(null);
      },
      onError: (caught) => setError(caught instanceof Error ? caught.message : "Could not load run."),
      shouldPoll: runNeedsRefresh
    });
  }, [params.id]);

  return (
    <AppShell>
      <div className="grid gap-5">
        <header className="flex flex-wrap items-start justify-between gap-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
          <div>
            <p className="font-display text-xs uppercase text-[var(--text-secondary)]">Agent workspace</p>
            {isLoading ? (
              <>
                <div className="mt-3 h-9 w-[min(620px,70vw)] animate-pulse rounded bg-white/10" />
                <div className="mt-4 h-4 w-[min(520px,64vw)] animate-pulse rounded bg-white/10" />
              </>
            ) : (
              <>
                <h1 className="mt-2 font-display text-3xl font-semibold">{view.headline}</h1>
                <p className="mt-2 max-w-3xl text-sm leading-6 text-[var(--text-secondary)]">{error ?? view.summary}</p>
              </>
            )}
          </div>
          {canOpenReview ? (
            <ButtonLink href={`/runs/${params.id}/review`} variant="primary">Review run</ButtonLink>
          ) : (
            <span className="inline-flex min-h-10 items-center rounded-lg border border-[var(--border)] px-3.5 text-sm text-[var(--text-secondary)]">
              Review unavailable
            </span>
          )}
        </header>
        {isLoading ? <RunDetailSkeleton /> : (
          <div className="grid gap-5 xl:grid-cols-[280px_minmax(0,1fr)_240px]">
            <RunTimeline view={view} />
            <ArtifactWorkspace view={view} />
            <RunIntelligence view={view} />
          </div>
        )}
        <Link className="text-sm text-cyan-300" href="/runs">Back to runs</Link>
      </div>
    </AppShell>
  );
}

function RunDetailSkeleton() {
  return (
    <div className="grid gap-5 xl:grid-cols-[280px_minmax(0,1fr)_240px]">
      {[0, 1, 2].map((panel) => (
        <section key={panel} className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
          <div className="h-4 w-32 animate-pulse rounded bg-white/10" />
          <div className="mt-5 grid gap-3">
            {Array.from({ length: panel === 1 ? 5 : 4 }).map((_, index) => (
              <div key={index} className="h-12 animate-pulse rounded-lg bg-white/10" />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
