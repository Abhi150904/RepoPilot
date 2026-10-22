"use client";

import { CreditCard, FlaskConical, Loader2, Play, RefreshCw } from "lucide-react";
import { githubLoginUrl, type BillingSimulation, type BillingStatus } from "@/lib/api";

type Props = {
  data: BillingStatus | null;
  loading: boolean;
  signedOut: boolean;
  busy: "checkout" | "simulation" | null;
  error: string | null;
  notice: string | null;
  simulation: BillingSimulation | null;
  onRefresh: () => void;
  onCheckout: () => void;
  onSimulate: () => void;
};

const button = "inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-[var(--border)] px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50 hover:bg-[var(--surface-elevated)]";

export function BillingContent(props: Props) {
  const { data, loading, signedOut, busy, error, notice, simulation } = props;
  return (
    <div className="mx-auto max-w-5xl space-y-8 break-words">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="mb-2 flex items-center gap-2 text-sm text-[var(--text-secondary)]"><FlaskConical size={16} aria-hidden="true" /> Sandbox only</p>
          <h1 className="font-display text-2xl font-semibold">Billing Demo</h1>
          <p className="mt-2 max-w-xl text-sm text-[var(--text-secondary)]">No real money. Demo attempts are separate from real AI runs.</p>
        </div>
        <button className={button} onClick={props.onRefresh} disabled={loading || !!busy} title="Refresh billing" aria-label="Refresh billing"><RefreshCw size={17} aria-hidden="true" /></button>
      </header>
      {error ? <p role="alert" className="border-l-2 border-red-400 pl-3 text-sm text-red-300">{error}</p> : null}
      {notice ? <p role="status" className="border-l-2 border-[var(--accent)] pl-3 text-sm text-[var(--text-secondary)]">{notice}</p> : null}
      {loading && !data ? <p role="status" className="flex items-center gap-2 text-sm"><Loader2 size={16} className="animate-spin" /> Loading billing...</p> : null}
      {signedOut ? <a href={githubLoginUrl()} className={button}>Sign in with GitHub</a> : null}
      {data && !data.enabled ? <p className="text-sm text-[var(--text-secondary)]">Sandbox checkout is not available yet.</p> : null}
      {data?.enabled ? <>
        <section className="grid gap-8 border-y border-[var(--border)] py-6 md:grid-cols-2">
          <div className="space-y-3">
            <h2 className="text-sm font-medium text-[var(--text-secondary)]">Demo balance</h2>
            <p className="font-display text-3xl font-semibold">{data.demo_balance} <span className="text-base font-normal">attempts</span></p>
            <button className={button} onClick={props.onSimulate} disabled={!!busy || data.demo_balance < 1}>
              {busy === "simulation" ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />} Run simulation
            </button>
          </div>
          <div className="space-y-3">
            <h2 className="text-base font-semibold">{data.pack_attempts} demo attempts</h2>
            <p className="text-xl">{new Intl.NumberFormat("en-US", { style: "currency", currency: data.currency }).format(data.test_price_cents / 100)} <span className="text-sm text-[var(--text-secondary)]">test price</span></p>
            <button className={button} onClick={props.onCheckout} disabled={!!busy}>
              {busy === "checkout" ? <Loader2 size={16} className="animate-spin" /> : <CreditCard size={16} />} Open test checkout
            </button>
          </div>
        </section>
        {simulation ? <section className="space-y-3" aria-label="Simulation result">
          <h2 className="text-lg font-semibold">Simulated result</h2>
          <p className="text-sm text-[var(--text-secondary)]">Example output only. No AI call, repository change, or test execution.</p>
          <p className="text-sm">{simulation.summary}</p>
          <pre className="overflow-x-auto rounded-md border border-[var(--border)] bg-[var(--surface)] p-4 text-xs"><code>{simulation.patch}</code></pre>
        </section> : null}
        <section className="space-y-4">
          <h2 className="text-lg font-semibold">Test purchases</h2>
          {data.purchases.length ? <ul className="divide-y divide-[var(--border)]">{data.purchases.map((row) => <li key={row.id} className="flex flex-wrap justify-between gap-2 py-3 text-sm">
            <span className="text-[var(--text-secondary)]">{new Date(row.created_at).toLocaleString()}</span><span className="capitalize">{row.state}</span>
          </li>)}</ul> : <p className="text-sm text-[var(--text-secondary)]">No test purchases yet.</p>}
        </section>
        <section className="space-y-4">
          <h2 className="text-lg font-semibold">Demo activity</h2>
          {data.activity.length ? <ul className="divide-y divide-[var(--border)]">{data.activity.map((row) => <li key={row.id} className="flex flex-wrap justify-between gap-2 py-3 text-sm">
            <span className="capitalize">{row.kind}</span><span>{row.delta > 0 ? "+" : ""}{row.delta} attempts</span>
          </li>)}</ul> : <p className="text-sm text-[var(--text-secondary)]">No demo activity yet.</p>}
        </section>
      </> : null}
    </div>
  );
}
