"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Play, RefreshCw } from "lucide-react";
import { createRun, getAuthMe, getRunUsage, RepoPilotApiError, type RunUsage } from "@/lib/api";
import { buildRunRequest } from "@/lib/run-request";

type Props = {
  usage: RunUsage | null;
  repository: string;
  issueNumber: string;
  busy: boolean;
  loading: boolean;
  error: string | null;
  retryPending?: boolean;
  onRepository: (value: string) => void;
  onIssueNumber: (value: string) => void;
  onStart: () => void;
  onRefresh: () => void;
};

function hasRunAccess(usage: RunUsage) {
  return !usage.enforced || (usage.introductory?.remaining ?? 0) > 0 || usage.run_credits > 0;
}

export function RunLauncher() {
  const router = useRouter();
  const [usage, setUsage] = useState<RunUsage | null>(null);
  const [repository, setRepository] = useState("");
  const [issueNumber, setIssueNumber] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const actionLock = useRef(false);
  const aiKey = useRef<{ payload: string; key: string } | null>(null);
  const request = buildRunRequest({ mode: "github", repository, issueNumber,
    issueText: "", applyChanges: true, runTests: true, maxRepairAttempts: "2" });
  const retryPending = !("error" in request) && aiKey.current?.payload === JSON.stringify(request);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      await getAuthMe();
      const next = await getRunUsage();
      setUsage(next);
      setError(null);
    } catch (caught) {
      // Fail closed when account/allowance state cannot be verified.
      setUsage(null);
      setError(caught instanceof Error ? caught.message : "Could not load run access.");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  async function start() {
    if (actionLock.current || loading || (!retryPending && (!usage || !hasRunAccess(usage)))) return;
    if ("error" in request) { setError(request.error); return; }
    actionLock.current = true;
    setBusy(true);
    setError(null);
    try {
      const payload = JSON.stringify(request);
      if (aiKey.current?.payload !== payload) aiKey.current = { payload, key: crypto.randomUUID() };
      const run = await createRun(request, aiKey.current.key);
      aiKey.current = null;
      await refresh();
      router.push(`/runs/${run.run_id}`);
    } catch (caught) {
      if (caught instanceof RepoPilotApiError && caught.status > 0 && caught.status < 500) {
        aiKey.current = null;
      }
      await refresh();
      setError(caught instanceof Error ? caught.message : "Could not start run.");
    } finally { actionLock.current = false; setBusy(false); }
  }

  return <RunLauncherContent usage={usage} repository={repository} issueNumber={issueNumber}
    busy={busy} loading={loading} error={error} retryPending={retryPending}
    onRepository={setRepository} onIssueNumber={setIssueNumber} onStart={() => void start()}
    onRefresh={() => void refresh()} />;
}

export function RunLauncherContent(props: Props) {
  const { usage, busy, loading, error, retryPending = false } = props;
  const exhausted = !!usage && !hasRunAccess(usage);
  const canStart = !loading && !busy && (retryPending || (!!usage && !exhausted));
  const input = "min-h-11 min-w-0 rounded-md border border-[var(--border)] bg-[var(--background)] px-3";

  return <section className="min-w-0 space-y-5 border-y border-[var(--border)] py-5" aria-label="Start a run">
    <div className="flex items-center justify-between gap-3">
      <h2 className="font-display text-lg font-semibold">Start a run</h2>
      <button type="button" aria-label="Refresh run access" title="Refresh run access" onClick={props.onRefresh}
        disabled={busy || loading} className="grid h-11 w-11 shrink-0 place-items-center rounded-md border border-[var(--border)] disabled:opacity-50"><RefreshCw size={16} /></button>
    </div>
    <div className="space-y-2 text-sm text-[var(--text-secondary)]" aria-live="polite">
      {loading && !usage ? <p>Checking run access...</p> : null}
      {usage?.enforced ? <>
        <p><strong className="text-[var(--text-primary)]">{usage.introductory?.remaining ?? 0} of {usage.introductory?.total ?? 2}</strong> free AI runs remaining
          {usage.introductory?.reserved ? ` (${usage.introductory.reserved} reserved)` : ""}</p>
        <p className="text-xs">Two lifetime free runs per GitHub account, then one purchased credit per AI run.</p>
      </> : null}
      {usage && !usage.enforced ? <p>Local execution</p> : null}
      {usage ? <p><strong className="text-[var(--text-primary)]">{usage.run_credits}</strong> purchased run {usage.run_credits === 1 ? "credit" : "credits"}</p> : null}
    </div>
    {retryPending ? <p className="text-sm text-[var(--text-secondary)]">The previous request may have started. Retry to recover its result.</p>
      : exhausted ? <p className="text-sm text-[var(--text-secondary)]">No runs available. Free runs are used or reserved, and no purchased credits remain.</p> : null}
    <div className="grid min-w-0 gap-3">
      <label className="grid min-w-0 gap-2 text-sm"><span>Repository</span><input className={input} value={props.repository} disabled={busy} onChange={(event) => props.onRepository(event.target.value)} placeholder="owner/repo" /></label>
      <label className="grid min-w-0 gap-2 text-sm"><span>Issue number</span><input className={input} value={props.issueNumber} disabled={busy} onChange={(event) => props.onIssueNumber(event.target.value)} type="number" min="1" /></label>
    </div>
    <button type="button" onClick={props.onStart} disabled={!canStart} className="flex min-h-11 w-full items-center justify-center gap-2 rounded-md border border-[var(--accent)] bg-[var(--surface-elevated)] px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50">
      {busy ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
      {busy ? "Starting..." : retryPending ? "Retry pending request" : "Start AI run"}
    </button>
    {error ? <p role="alert" className="text-sm text-red-300">{error}</p> : null}
    <Link className="inline-flex min-h-11 items-center text-sm text-[var(--accent)]" href="/billing">{exhausted ? "Buy run credits in Billing" : "Billing and credits"}</Link>
  </section>;
}
