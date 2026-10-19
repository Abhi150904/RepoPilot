"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/app-shell";
import { ReviewPanel } from "@/components/run-panels";
import { ButtonLink } from "@/components/button";
import { RunUnavailable } from "@/components/run-unavailable";
import { approveRun, getRun, publishRun, rejectRun, type PublishMode, type RunStatusResponse } from "@/lib/api";
import { buildRunView } from "@/lib/run-view-model";

export default function ReviewPage() {
  const { id } = useParams<{ id: string }>();
  const [run, setRun] = useState<RunStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [activeAction, setActiveAction] = useState<string | null>(null);
  const view = useMemo(() => buildRunView(run), [run]);
  const canApprove = run?.lifecycle_status === "completed" && view.tests.passed === true && view.review.blockers === 0;

  useEffect(() => {
    let cancelled = false;
    setRun(null);
    setError(null);
    async function load() {
      try {
        const response = await getRun(id);
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
  }, [id]);

  async function mutate(action: "approve" | "reject" | PublishMode) {
    setBusy(true);
    setActiveAction(action);
    setError(null);
    try {
      if (action === "approve") {
        setRun(await approveRun(id));
      } else if (action === "reject") {
        setRun(await rejectRun(id));
      } else {
        setRun(await publishRun(id, action));
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Run action failed.");
    } finally {
      setBusy(false);
      setActiveAction(null);
    }
  }

  if (!run) {
    return (
      <AppShell>
        {error ? <RunUnavailable message={error} /> : <p role="status">Loading run...</p>}
      </AppShell>
    );
  }

  return (
    <AppShell>
      <div className="grid gap-4">
        {error ? <p className="rounded-lg border border-red-400/30 bg-red-400/10 p-3 text-sm text-red-200">{error}</p> : null}
        {run && !canApprove ? (
          <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6">
            <p className="font-display text-xs uppercase text-[var(--text-secondary)]">Human review</p>
            <h1 className="mt-3 font-display text-3xl font-semibold">Approval is blocked.</h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-[var(--text-secondary)]">
              {view.tests.passed === false
                ? view.tests.summary
                : "RepoPilot did not produce a passing review package for this run."}
            </p>
            <div className="mt-5">
              <ButtonLink href={`/runs/${id}`} variant="primary">Inspect run</ButtonLink>
            </div>
          </section>
        ) : (
          <ReviewPanel
            run={run}
            view={view}
            isBusy={busy}
            activeAction={activeAction}
            onApprove={() => mutate("approve")}
            onReject={() => mutate("reject")}
            onPublish={(mode) => mutate(mode)}
          />
        )}
      </div>
    </AppShell>
  );
}
