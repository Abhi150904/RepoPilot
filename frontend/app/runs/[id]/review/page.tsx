"use client";

import { useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { ReviewPanel } from "@/components/run-panels";
import { approveRun, getRun, publishRun, rejectRun, type PublishMode, type RunStatusResponse } from "@/lib/api";
import { buildRunView } from "@/lib/run-view-model";

export default function ReviewPage({ params }: { params: { id: string } }) {
  const [run, setRun] = useState<RunStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [activeAction, setActiveAction] = useState<string | null>(null);
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

  async function mutate(action: "approve" | "reject" | PublishMode) {
    setBusy(true);
    setActiveAction(action);
    setError(null);
    try {
      if (action === "approve") {
        setRun(await approveRun(params.id));
      } else if (action === "reject") {
        setRun(await rejectRun(params.id));
      } else {
        setRun(await publishRun(params.id, action));
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Run action failed.");
    } finally {
      setBusy(false);
      setActiveAction(null);
    }
  }

  return (
    <AppShell>
      <div className="grid gap-4">
        {error ? <p className="rounded-lg border border-red-400/30 bg-red-400/10 p-3 text-sm text-red-200">{error}</p> : null}
        <ReviewPanel
          run={run}
          view={view}
          isBusy={busy}
          activeAction={activeAction}
          onApprove={() => mutate("approve")}
          onReject={() => mutate("reject")}
          onPublish={(mode) => mutate(mode)}
        />
      </div>
    </AppShell>
  );
}
