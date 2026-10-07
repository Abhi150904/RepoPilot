"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { ArtifactWorkspace, RunIntelligence, RunTimeline } from "@/components/run-panels";
import { ButtonLink } from "@/components/button";
import { getRun, type RunStatusResponse } from "@/lib/api";
import { buildRunView } from "@/lib/run-view-model";

export default function RunDetailPage({ params }: { params: { id: string } }) {
  const [run, setRun] = useState<RunStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const view = useMemo(() => buildRunView(run), [run]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await getRun(params.id);
        if (!cancelled) {
          setRun(response);
        }
      } catch (caught) {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "Could not load run.");
        }
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [params.id]);

  return (
    <AppShell>
      <div className="grid gap-5">
        <header className="flex flex-wrap items-start justify-between gap-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
          <div>
            <p className="font-display text-xs uppercase text-[var(--text-secondary)]">Agent workspace</p>
            <h1 className="mt-2 font-display text-3xl font-semibold">{view.headline}</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-[var(--text-secondary)]">{error ?? view.summary}</p>
          </div>
          <ButtonLink href={`/runs/${params.id}/review`} variant="primary">Review run</ButtonLink>
        </header>
        <div className="grid gap-5 xl:grid-cols-[280px_minmax(0,1fr)_240px]">
          <RunTimeline view={view} />
          <ArtifactWorkspace view={view} />
          <RunIntelligence view={view} />
        </div>
        {!run && !error ? <p className="text-sm text-[var(--text-secondary)]">Loading run...</p> : null}
        <Link className="text-sm text-cyan-300" href="/runs">Back to runs</Link>
      </div>
    </AppShell>
  );
}
