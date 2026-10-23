"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Bot, FlaskConical, Loader2, Play, RefreshCw } from "lucide-react";
import { createRun, createSimulation, getAuthMe, getRunUsage, listSimulations, RepoPilotApiError,
  type BillingSimulation, type RunUsage } from "@/lib/api";
import { buildRunRequest } from "@/lib/run-request";

type Mode = "ai" | "simulation";
type Props = {
  usage: RunUsage | null;
  mode: Mode;
  repository: string;
  issueNumber: string;
  busy: boolean;
  loading: boolean;
  error: string | null;
  result: BillingSimulation | null;
  simulations: BillingSimulation[];
  onMode: (mode: Mode) => void;
  onRepository: (value: string) => void;
  onIssueNumber: (value: string) => void;
  onStart: () => void;
  onRefresh: () => void;
  onSelect: (run: BillingSimulation) => void;
};

export function RunLauncher() {
  const router = useRouter();
  const [usage, setUsage] = useState<RunUsage | null>(null);
  const [mode, setMode] = useState<Mode>("ai");
  const [repository, setRepository] = useState("");
  const [issueNumber, setIssueNumber] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BillingSimulation | null>(null);
  const [simulations, setSimulations] = useState<BillingSimulation[]>([]);
  const modeSelected = useRef(false);
  const actionLock = useRef(false);
  const simulationKey = useRef<string | null>(null);
  const aiKey = useRef<{ payload: string; key: string } | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const auth = await getAuthMe();
      const next = await getRunUsage();
      const history = auth.authenticated ? await listSimulations() : [];
      setUsage(next);
      setSimulations(history);
      if (!modeSelected.current) {
        setMode(next.enforced && next.introductory?.remaining === 0 ? "simulation" : "ai");
        modeSelected.current = true;
      }
      setError(null);
    } catch (caught) {
      // Fail closed when account/allowance state cannot be verified.
      setUsage(null);
      setError(caught instanceof Error ? caught.message : "Could not load run access.");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  async function start() {
    if (actionLock.current || !usage || loading) return;
    const request = mode === "ai" ? buildRunRequest({ mode: "github", repository, issueNumber,
      issueText: "", applyChanges: true, runTests: true, maxRepairAttempts: "2" }) : null;
    if (request && "error" in request) { setError(request.error); return; }
    actionLock.current = true;
    setBusy(true);
    setError(null);
    try {
      if (mode === "simulation") {
        const key = simulationKey.current ?? crypto.randomUUID();
        simulationKey.current = key;
        const completed = await createSimulation(key);
        setResult(completed);
        simulationKey.current = null;
        await refresh();
      } else if (request && !("error" in request)) {
        const payload = JSON.stringify(request);
        if (aiKey.current?.payload !== payload) aiKey.current = { payload, key: crypto.randomUUID() };
        const run = await createRun(request, aiKey.current.key);
        aiKey.current = null;
        router.push(`/runs/${run.run_id}`);
      }
    } catch (caught) {
      if (caught instanceof RepoPilotApiError && caught.status > 0 && caught.status < 500) {
        simulationKey.current = null;
        aiKey.current = null;
      }
      await refresh();
      setError(caught instanceof Error ? caught.message : "Could not start run.");
    } finally { actionLock.current = false; setBusy(false); }
  }

  return <RunLauncherContent usage={usage} mode={mode} repository={repository} issueNumber={issueNumber}
    busy={busy} loading={loading} error={error} result={result} simulations={simulations}
    onMode={(next) => { modeSelected.current = true; setMode(next); setResult(null); }}
    onRepository={setRepository} onIssueNumber={setIssueNumber} onStart={() => void start()}
    onRefresh={() => void refresh()} onSelect={setResult} />;
}

export function RunLauncherContent(props: Props) {
  const { usage, mode, busy, loading, error, result, simulations } = props;
  const exhausted = !!usage?.enforced && (usage.introductory?.remaining ?? 0) < 1;
  const canStart = !!usage && !loading && !busy && (mode === "ai" ? !exhausted
    : usage.billing_enabled && usage.simulation_credits > 0);
  const input = "min-h-11 min-w-0 rounded-md border border-[var(--border)] bg-[var(--background)] px-3";

  return <section className="min-w-0 space-y-5 border-y border-[var(--border)] py-5" aria-label="Start a run">
    <div className="flex items-center justify-between gap-3">
      <h2 className="font-display text-lg font-semibold">Start a run</h2>
      <button type="button" aria-label="Refresh run access" title="Refresh run access" onClick={props.onRefresh}
        disabled={busy || loading} className="grid h-11 w-11 shrink-0 place-items-center rounded-md border border-[var(--border)] disabled:opacity-50"><RefreshCw size={16} /></button>
    </div>
    <div className="space-y-2 text-sm text-[var(--text-secondary)]" aria-live="polite">
      {loading && !usage ? <p>Checking run access...</p> : null}
      {usage?.enforced && usage.introductory ? <p><strong className="text-[var(--text-primary)]">{usage.introductory.remaining} of {usage.introductory.total}</strong> free AI runs available
        {usage.introductory.reserved ? ` (${usage.introductory.reserved} reserved)` : ""}</p> : null}
      {usage?.enforced ? <p className="text-xs">One-time allowance per GitHub account.</p> : null}
      {usage && !usage.enforced ? <p>Local execution</p> : null}
      {usage ? <p><strong className="text-[var(--text-primary)]">{usage.simulation_credits}</strong> simulation credits</p> : null}
    </div>
    <fieldset disabled={busy}>
      <legend className="sr-only">Execution mode</legend>
      <div className="grid grid-cols-2 rounded-md border border-[var(--border)]">
        {([{ value: "ai", label: "AI run", icon: Bot }, { value: "simulation", label: "Simulation", icon: FlaskConical }] as const).map(({ value, label, icon: Icon }) =>
          <label key={value} className={`flex min-h-11 cursor-pointer items-center justify-center gap-2 px-2 text-sm focus-within:outline focus-within:outline-2 focus-within:outline-[var(--accent)] ${mode === value ? "bg-[var(--surface-elevated)] text-[var(--text-primary)]" : "text-[var(--text-secondary)]"}`}>
            <input className="sr-only" type="radio" name="execution-mode" value={value} checked={mode === value} onChange={() => props.onMode(value)} />
            <Icon size={16} aria-hidden="true" />{label}
          </label>)}
      </div>
    </fieldset>
    {mode === "ai" ? <>
      {exhausted ? <p className="text-sm text-[var(--text-secondary)]">Your introductory AI runs are used or reserved. Sandbox credits fund simulations only.</p> : null}
      <div className="grid min-w-0 gap-3">
        <label className="grid min-w-0 gap-2 text-sm"><span>Repository</span><input className={input} value={props.repository} disabled={busy || exhausted} onChange={(event) => props.onRepository(event.target.value)} placeholder="owner/repo" /></label>
        <label className="grid min-w-0 gap-2 text-sm"><span>Issue number</span><input className={input} value={props.issueNumber} disabled={busy || exhausted} onChange={(event) => props.onIssueNumber(event.target.value)} type="number" min="1" /></label>
      </div>
    </> : <div className="space-y-2 text-sm">
      <h3 className="font-medium">Email validation example</h3>
      <p className="text-[var(--text-secondary)]">1 credit per simulation. No AI call, repository change, or test execution.</p>
      {usage && !usage.billing_enabled ? <p className="text-[var(--text-secondary)]">Simulation checkout is currently unavailable.</p> : null}
    </div>}
    <button type="button" onClick={props.onStart} disabled={!canStart} className="flex min-h-11 w-full items-center justify-center gap-2 rounded-md border border-[var(--accent)] bg-[var(--surface-elevated)] px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50">
      {busy ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
      {busy ? "Starting..." : mode === "ai" ? "Start AI run" : "Start simulation"}
    </button>
    {error ? <p role="alert" className="text-sm text-red-300">{error}</p> : null}
    <Link className="inline-flex min-h-11 items-center text-sm text-[var(--accent)]" href="/billing">{mode === "simulation" && (usage?.simulation_credits ?? 0) < 1 ? "Buy simulation credits" : "Billing and credits"}</Link>
    {result ? <section className="min-w-0 space-y-3 border-t border-[var(--border)] pt-4" aria-label="Simulation result">
      <h3 className="font-semibold">Simulated result</h3>
      <p className="text-sm">{result.summary}</p>
      <p className="text-xs text-[var(--text-secondary)]">Example output only. No tests were executed.</p>
      <pre className="max-w-full overflow-x-auto bg-[var(--background)] p-3 text-xs"><code>{result.patch}</code></pre>
    </section> : null}
    {simulations.length ? <section className="space-y-2 border-t border-[var(--border)] pt-4" aria-label="Simulation history">
      <h3 className="text-sm font-semibold">Recent simulations</h3>
      <ul className="max-h-48 divide-y divide-[var(--border)] overflow-y-auto">{simulations.map((run) => <li key={run.simulation_id}>
        <button type="button" className="min-h-11 w-full py-2 text-left text-sm text-[var(--text-secondary)]" onClick={() => props.onSelect(run)}>
          <time dateTime={run.created_at}>{new Date(run.created_at).toLocaleString("en-US", { timeZone: "UTC" })} UTC</time>
        </button>
      </li>)}</ul>
    </section> : null}
  </section>;
}
