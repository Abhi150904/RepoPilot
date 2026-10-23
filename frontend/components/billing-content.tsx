"use client";

import Link from "next/link";
import { CreditCard, Loader2, RefreshCw } from "lucide-react";
import { githubLoginUrl, type BillingStatus } from "@/lib/api";

type Props = {
  data: BillingStatus | null;
  loading: boolean;
  signedOut: boolean;
  busy: boolean;
  error: string | null;
  notice: string | null;
  onRefresh: () => void;
  onCheckout: () => void;
};

const button = "inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-[var(--border)] px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50 hover:bg-[var(--surface-elevated)]";

export function BillingContent(props: Props) {
  const { data, loading, signedOut, busy, error, notice } = props;
  return (
    <div className="mx-auto max-w-5xl space-y-8 break-words">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl font-semibold">Billing</h1>
        </div>
        <button className={button} onClick={props.onRefresh} disabled={loading || !!busy} title="Refresh billing" aria-label="Refresh billing"><RefreshCw size={17} aria-hidden="true" /></button>
      </header>
      {error ? <p role="alert" className="border-l-2 border-red-400 pl-3 text-sm text-red-300">{error}</p> : null}
      {notice ? <p role="status" className="border-l-2 border-[var(--accent)] pl-3 text-sm text-[var(--text-secondary)]">{notice}</p> : null}
      {loading && !data ? <p role="status" className="flex items-center gap-2 text-sm"><Loader2 size={16} className="animate-spin" /> Loading billing...</p> : null}
      {signedOut ? <a href={githubLoginUrl()} className={button}>Sign in with GitHub</a> : null}
      {data && !data.enabled ? <p className="text-sm text-[var(--text-secondary)]">Checkout is currently unavailable.</p> : null}
      {data?.enabled ? <>
        <section className="grid gap-8 border-y border-[var(--border)] py-6 md:grid-cols-2">
          <div className="space-y-3">
            <h2 className="text-sm font-medium text-[var(--text-secondary)]">Credit balance</h2>
            <p className="font-display text-3xl font-semibold">{data.demo_balance} <span className="text-base font-normal">{data.demo_balance === 1 ? "credit" : "credits"}</span></p>
            <Link className="inline-flex min-h-11 items-center text-sm text-[var(--accent)]" href="/app">Command Center</Link>
          </div>
          <div className="space-y-3">
            <h2 className="text-base font-semibold">{data.pack_attempts} simulation credits</h2>
            <p className="text-xl">{new Intl.NumberFormat("en-US", { style: "currency", currency: data.currency }).format(data.test_price_cents / 100)} <span className="text-sm uppercase text-[var(--text-secondary)]">{data.currency}</span></p>
            <button className={button} onClick={props.onCheckout} disabled={!!busy} aria-describedby="checkout-disclosure">
              {busy ? <Loader2 size={16} className="animate-spin" /> : <CreditCard size={16} />} Buy credits
            </button>
            <p id="checkout-disclosure" className="text-xs text-[var(--text-secondary)]">Test payments only. No real charges. Credits apply to simulations, not real AI runs.</p>
          </div>
        </section>
        <section className="space-y-4">
          <h2 className="text-lg font-semibold">Payment history</h2>
          {data.purchases.length ? <ul className="divide-y divide-[var(--border)]">{data.purchases.map((row) => <li key={row.id} className="flex flex-wrap justify-between gap-2 py-3 text-sm">
            <time dateTime={row.created_at} className="text-[var(--text-secondary)]">{new Date(row.created_at).toLocaleString("en-US", { timeZone: "UTC" })} UTC</time><span className="capitalize">{row.state}</span>
          </li>)}</ul> : <p className="text-sm text-[var(--text-secondary)]">No purchases yet.</p>}
        </section>
        <section className="space-y-4">
          <h2 className="text-lg font-semibold">Credit activity</h2>
          {data.activity.length ? <ul className="divide-y divide-[var(--border)]">{data.activity.map((row) => <li key={row.id} className="flex flex-wrap justify-between gap-2 py-3 text-sm">
            <span className="capitalize">{row.kind}</span><span>{row.delta > 0 ? "+" : ""}{row.delta} {Math.abs(row.delta) === 1 ? "credit" : "credits"}</span>
          </li>)}</ul> : <p className="text-sm text-[var(--text-secondary)]">No credit activity yet.</p>}
        </section>
      </> : null}
    </div>
  );
}
