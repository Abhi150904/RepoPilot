"use client";

import { useEffect, useMemo, useState } from "react";
import { BarChart3, Braces, GitCompareArrows, PlayCircle } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import {
  compareEvaluationRuns,
  createEvaluationRun,
  listEvaluationRuns,
  listEvaluationSuites,
  type EvaluationComparison,
  type EvaluationRun,
  type EvaluationSuite
} from "@/lib/api";

const retrievalMetrics = ["recall_at_3", "recall_at_5", "precision_at_5", "mrr", "total_tokens", "estimated_cost_usd"];
const workflowMetrics = ["task_success_rate", "test_pass_rate", "repair_success_rate", "repair_attempts_total", "total_tokens", "estimated_cost_usd", "average_case_duration_ms"];

export default function EvaluationsPage() {
  const [suites, setSuites] = useState<EvaluationSuite[]>([]);
  const [runs, setRuns] = useState<EvaluationRun[]>([]);
  const [selectedSuite, setSelectedSuite] = useState("retrieval-core-v1");
  const [strategy, setStrategy] = useState("hybrid");
  const [topK, setTopK] = useState(5);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [comparison, setComparison] = useState<EvaluationComparison | null>(null);

  async function load() {
    try {
      const [suiteData, runData] = await Promise.all([listEvaluationSuites(), listEvaluationRuns()]);
      setSuites(suiteData);
      setRuns(runData);
      setError(null);
      if (!suiteData.some((suite) => suite.name === selectedSuite) && suiteData[0]) {
        setSelectedSuite(suiteData[0].name);
      }
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Could not load evaluation data.");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const activeSuite = suites.find((suite) => suite.name === selectedSuite);
  const latestRun = runs[0] ?? null;
  const compatibleRuns = useMemo(
    () => runs.filter((run) => run.suite_name === latestRun?.suite_name && run.status === "completed"),
    [runs, latestRun]
  );

  async function startEvaluation() {
    setBusy(true);
    setError(null);
    setComparison(null);
    try {
      const configuration =
        activeSuite?.eval_type === "retrieval"
          ? { strategy, top_k: topK, limit: Math.max(topK, 5) }
          : {};
      const run = await createEvaluationRun({ suite: selectedSuite, configuration });
      setRuns((current) => [run, ...current.filter((item) => item.id !== run.id)]);
    } catch (startError) {
      setError(startError instanceof Error ? startError.message : "Could not start evaluation.");
    } finally {
      setBusy(false);
    }
  }

  async function compareLatestTwo() {
    if (compatibleRuns.length < 2) {
      return;
    }
    try {
      setComparison(await compareEvaluationRuns([compatibleRuns[1].id, compatibleRuns[0].id]));
      setError(null);
    } catch (compareError) {
      setError(compareError instanceof Error ? compareError.message : "Could not compare evaluation runs.");
    }
  }

  return (
    <AppShell>
      <section className="grid gap-5">
        <header className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
          <p className="font-display text-xs uppercase text-cyan-300">Evaluations</p>
          <div className="mt-2 flex flex-wrap items-start justify-between gap-4">
            <div>
              <h1 className="text-3xl font-semibold">Real evaluation runs</h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-[var(--text-secondary)]">
                Durable retrieval and workflow evaluations from backend runs. Empty means no persisted evaluation has completed yet.
              </p>
            </div>
            <button className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-[var(--border)] px-4 text-sm font-medium hover:bg-[var(--surface-elevated)] disabled:opacity-50" onClick={startEvaluation} disabled={busy || !selectedSuite}>
              <PlayCircle size={16} />
              {busy ? "Running..." : "Run evaluation"}
            </button>
          </div>
        </header>

        {error ? <div className="rounded-xl border border-red-400/30 bg-red-400/10 p-4 text-sm text-red-100">{error}</div> : null}

        <section className="grid gap-4 lg:grid-cols-[360px_1fr]">
          <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
            <Braces className="text-cyan-300" size={20} />
            <h2 className="mt-4 text-lg font-semibold">Suite configuration</h2>
            <label className="mt-4 block text-xs uppercase text-[var(--text-secondary)]">Suite</label>
            <select className="mt-2 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm" value={selectedSuite} onChange={(event) => setSelectedSuite(event.target.value)}>
              {suites.map((suite) => (
                <option key={suite.id} value={suite.name}>
                  {suite.name} ({suite.eval_type})
                </option>
              ))}
            </select>
            {activeSuite?.eval_type === "retrieval" ? (
              <div className="mt-4 grid gap-3">
                <label className="block text-xs uppercase text-[var(--text-secondary)]">Retrieval strategy</label>
                <select className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm" value={strategy} onChange={(event) => setStrategy(event.target.value)}>
                  {["keyword", "bm25", "vector", "hybrid", "hybrid_reranked"].map((option) => (
                    <option key={option} value={option}>{option}</option>
                  ))}
                </select>
                <label className="block text-xs uppercase text-[var(--text-secondary)]">Top K</label>
                <input className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm" type="number" min={1} max={20} value={topK} onChange={(event) => setTopK(Number(event.target.value))} />
              </div>
            ) : null}
          </div>

          <MetricSummary run={latestRun} />
        </section>

        <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)]">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] px-5 py-4">
            <div>
              <p className="font-display text-xs uppercase text-[var(--text-secondary)]">Recent runs</p>
              <h2 className="mt-1 text-xl font-semibold">Evaluation history</h2>
            </div>
            <button className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-[var(--border)] px-4 text-sm font-medium hover:bg-[var(--surface-elevated)] disabled:opacity-50" onClick={compareLatestTwo} disabled={compatibleRuns.length < 2}>
              <GitCompareArrows size={16} />
              Compare latest two
            </button>
          </div>
          {runs.length ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[820px] text-left text-sm">
                <thead className="text-xs uppercase text-[var(--text-secondary)]">
                  <tr>
                    <th className="px-5 py-3">Suite</th>
                    <th className="px-5 py-3">Status</th>
                    <th className="px-5 py-3">Config</th>
                    <th className="px-5 py-3">Metrics</th>
                    <th className="px-5 py-3">Cases</th>
                    <th className="px-5 py-3">Created</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run) => (
                    <tr key={run.id} className="border-t border-[var(--border)]">
                      <td className="px-5 py-4 font-medium">{run.suite_name}</td>
                      <td className="px-5 py-4">{run.status}</td>
                      <td className="px-5 py-4 text-[var(--text-secondary)]">{configSummary(run)}</td>
                      <td className="px-5 py-4 text-[var(--text-secondary)]">{metricSummary(run)}</td>
                      <td className="px-5 py-4">{run.case_results.length || "—"}</td>
                      <td className="px-5 py-4 text-[var(--text-secondary)]">{new Date(run.created_at).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="p-5 text-sm text-[var(--text-secondary)]">No persisted evaluation runs yet.</div>
          )}
        </section>

        {latestRun ? <CaseTable run={latestRun} /> : null}
        {comparison ? <ComparisonTable comparison={comparison} /> : null}
      </section>
    </AppShell>
  );
}

function MetricSummary({ run }: { run: EvaluationRun | null }) {
  const names = run?.eval_type === "workflow" ? workflowMetrics : retrievalMetrics;
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
      <BarChart3 className="text-cyan-300" size={20} />
      <h2 className="mt-4 text-lg font-semibold">Latest aggregate metrics</h2>
      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {names.map((name) => (
          <div key={name} className="rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] p-3">
            <p className="text-xs uppercase text-[var(--text-secondary)]">{name.replaceAll("_", " ")}</p>
            <strong className="mt-2 block font-display text-xl">{formatMetric(metricValue(run, name))}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

function CaseTable({ run }: { run: EvaluationRun }) {
  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)]">
      <div className="border-b border-[var(--border)] px-5 py-4">
        <p className="font-display text-xs uppercase text-[var(--text-secondary)]">Case results</p>
        <h2 className="mt-1 text-xl font-semibold">{run.suite_name}</h2>
      </div>
      {run.case_results.length ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-left text-sm">
            <thead className="text-xs uppercase text-[var(--text-secondary)]">
              <tr>
                <th className="px-5 py-3">Case</th>
                <th className="px-5 py-3">Status</th>
                <th className="px-5 py-3">Measurements</th>
                <th className="px-5 py-3">Output</th>
                <th className="px-5 py-3">Duration</th>
              </tr>
            </thead>
            <tbody>
              {run.case_results.map((result) => (
                <tr key={result.id} className="border-t border-[var(--border)] align-top">
                  <td className="px-5 py-4 font-medium">{result.case_key}</td>
                  <td className="px-5 py-4">{result.status}</td>
                  <td className="px-5 py-4 text-[var(--text-secondary)]"><JsonPreview value={result.measurements} /></td>
                  <td className="px-5 py-4 text-[var(--text-secondary)]"><JsonPreview value={result.output} /></td>
                  <td className="px-5 py-4">{result.duration_ms == null ? "n/a" : `${result.duration_ms.toFixed(1)}ms`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="p-5 text-sm text-[var(--text-secondary)]">Case results are not available for this run.</div>
      )}
    </section>
  );
}

function ComparisonTable({ comparison }: { comparison: EvaluationComparison }) {
  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
      <h2 className="text-xl font-semibold">Comparison</h2>
      {comparison.warning ? <p className="mt-2 text-sm text-amber-200">{comparison.warning}</p> : null}
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[620px] text-left text-sm">
          <thead className="text-xs uppercase text-[var(--text-secondary)]">
            <tr>
              <th className="py-3">Metric</th>
              <th className="py-3">Baseline</th>
              <th className="py-3">Current</th>
              <th className="py-3">Delta</th>
            </tr>
          </thead>
          <tbody>
            {comparison.metrics.map((metric) => (
              <tr key={metric.metric_name} className="border-t border-[var(--border)]">
                <td className="py-3">{metric.metric_name}</td>
                <td className="py-3">{formatMetric(metric.baseline)}</td>
                <td className="py-3">{formatMetric(metric.current)}</td>
                <td className="py-3">{metric.delta == null ? "n/a" : metric.delta > 0 ? `+${metric.delta}` : String(metric.delta)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function JsonPreview({ value }: { value: Record<string, unknown> }) {
  return (
    <details>
      <summary className="cursor-pointer text-cyan-300">View</summary>
      <pre className="mt-2 max-h-64 overflow-auto rounded-lg bg-[var(--background)] p-3 text-xs">{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}

function metricValue(run: EvaluationRun | null, name: string): number | null | undefined {
  return run?.metrics.find((metric) => metric.metric_name === name)?.metric_value;
}

function formatMetric(value: number | null | undefined): string {
  if (value == null) {
    return "n/a";
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
}

function configSummary(run: EvaluationRun): string {
  const entries = Object.entries(run.configuration).filter(([, value]) => value !== null && value !== undefined);
  if (!entries.length) {
    return "—";
  }
  return entries.map(([key, value]) => `${key}: ${String(value)}`).join(", ");
}

function metricSummary(run: EvaluationRun): string {
  if (!run.metrics.length) {
    return "—";
  }
  return run.metrics.slice(0, 3).map((metric) => `${metric.metric_name}: ${formatMetric(metric.metric_value)}`).join(", ");
}
