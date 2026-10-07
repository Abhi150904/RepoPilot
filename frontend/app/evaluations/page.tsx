import { BarChart3, Braces, PlayCircle } from "lucide-react";
import { AppShell } from "@/components/app-shell";

const evalAreas = [
  ["Workflow evals", "Task success, test pass rate, repair behavior and approval readiness."],
  ["Retrieval evals", "Recall, MRR, precision and hit rate for repository context selection."],
  ["Cost and runtime", "Model calls, token usage, retries, latency and failed-run causes."]
];

export default function EvaluationsPage() {
  return (
    <AppShell>
      <section className="grid gap-5">
        <header className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
          <p className="font-display text-xs uppercase text-cyan-300">Evaluations</p>
          <h1 className="mt-2 text-3xl font-semibold">No evaluation runs connected yet.</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-[var(--text-secondary)]">
            The backend has eval tooling, but this frontend does not currently receive eval results from an API. This page should stay empty until real eval run data is available.
          </p>
        </header>

        <div className="grid gap-4 lg:grid-cols-3">
          {evalAreas.map(([title, copy]) => (
            <article key={title} className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
              <Braces className="text-cyan-300" size={20} />
              <h2 className="mt-4 text-lg font-semibold">{title}</h2>
              <p className="mt-2 text-sm leading-6 text-[var(--text-secondary)]">{copy}</p>
            </article>
          ))}
        </div>

        <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
          <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
            <div>
              <BarChart3 className="text-cyan-300" size={22} />
              <h2 className="mt-4 text-xl font-semibold">What should appear here later</h2>
              <p className="mt-2 text-sm leading-6 text-[var(--text-secondary)]">
                Once the API exposes eval runs, this page can show the latest run, dataset, pass/fail checks, retrieval strategy comparison and cost/runtime totals.
              </p>
            </div>
            <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] p-4">
              <div className="flex items-center gap-2">
                <PlayCircle className="text-cyan-300" size={18} />
                <h3 className="text-sm font-semibold">Current state</h3>
              </div>
              <p className="mt-3 text-sm leading-6 text-[var(--text-secondary)]">
                No fake scores are shown. Run evals through the backend CLI for now, then connect a real eval-results endpoint before making this dashboard data-driven.
              </p>
            </div>
          </div>
        </section>
      </section>
    </AppShell>
  );
}
