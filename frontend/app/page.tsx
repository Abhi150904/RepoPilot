import { ArrowDown, ArrowRight, Github } from "lucide-react";
import { RepoPilotLogo } from "@/components/repopilot-logo";

const workflow = ["Issue", "Analyze", "Retrieve", "Plan", "Code", "Test", "Review", "Approval", "PR"];
const evaluationSignals = [
  ["Task success", "Whether the run reaches a useful reviewed outcome for the issue."],
  ["Test pass rate", "How often generated changes pass the configured project tests."],
  ["Repair success", "Whether RepoPilot can fix failures after test or review feedback."],
  ["Retrieval quality", "How well the selected files match the issue being solved."]
];

export default function LandingPage() {
  return (
    <main className="min-h-screen bg-[var(--background)] text-[var(--text-primary)]">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
        <RepoPilotLogo />
        <a
          href="#workflow"
          className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3.5 text-sm font-medium text-[var(--text-primary)] transition hover:border-cyan-300 hover:text-cyan-200"
        >
          See workflow
          <ArrowDown size={16} />
        </a>
      </header>
      <section className="mx-auto grid max-w-6xl gap-10 px-6 py-24 lg:grid-cols-[1fr_460px] lg:items-center">
        <div>
          <p className="font-display text-xs uppercase text-cyan-300">Autonomous engineering. Human-controlled shipping.</p>
          <h1 className="mt-5 max-w-3xl font-display text-5xl font-semibold tracking-tight md:text-7xl">Ship fixes, not tickets.</h1>
          <p className="mt-6 max-w-2xl text-lg leading-8 text-[var(--text-secondary)]">
            RepoPilot turns GitHub issues into tested, reviewed pull requests — with you at the final gate.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <a
              href="/app"
              className="inline-flex min-h-12 items-center justify-center gap-2 rounded-lg border border-cyan-100 bg-cyan-300/15 px-5 text-base font-semibold text-white shadow-[0_0_36px_rgba(56,189,248,0.38)] transition hover:bg-cyan-300/25"
            >
              Start RepoPilot
              <ArrowRight size={17} />
            </a>
            <a
              className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3.5 text-sm font-medium text-[var(--text-primary)] transition hover:border-slate-500"
              href="https://github.com/Abhi150904/RepoPilot"
              target="_blank"
              rel="noreferrer"
            >
              <Github size={17} />
              View GitHub
            </a>
          </div>
        </div>
        <ProductFlow />
      </section>
      <section id="workflow" className="mx-auto grid max-w-6xl gap-4 px-6 py-16 md:grid-cols-3">
        {[
          ["Workflow", "Issue intake, repository retrieval, planning, implementation and test feedback in one controlled path."],
          ["Human control", "Approval is explicit. Publication waits for a reviewed, bound artifact."],
          ["Evaluation", "Workflow and retrieval metrics keep the agent measurable instead of merely impressive."]
        ].map(([title, copy]) => (
          <article key={title} className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
            <h2 className="font-display text-lg font-semibold">{title}</h2>
            <p className="mt-3 text-sm leading-6 text-[var(--text-secondary)]">{copy}</p>
          </article>
        ))}
      </section>
      <section id="human-control" className="mx-auto max-w-6xl px-6 py-16">
        <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-8">
          <p className="font-display text-xs uppercase text-cyan-300">Final gate</p>
          <h2 className="mt-3 font-display text-3xl font-semibold">Approve exactly what was reviewed.</h2>
          <p className="mt-4 max-w-2xl text-[var(--text-secondary)]">
            RepoPilot is built around engineering controls: review evidence, test status, artifact binding and publication choices.
          </p>
        </div>
      </section>
      <section id="evaluations" className="mx-auto max-w-6xl px-6 py-16">
        <div className="mb-5 max-w-2xl">
          <p className="font-display text-xs uppercase text-cyan-300">Evaluation signals</p>
          <h2 className="mt-2 font-display text-2xl font-semibold">What RepoPilot measures</h2>
          <p className="mt-3 text-sm leading-6 text-[var(--text-secondary)]">
            These are not buttons. They are the quality signals used to judge whether the agent is improving.
          </p>
        </div>
        <div className="grid gap-4 md:grid-cols-4">
          {evaluationSignals.map(([title, copy]) => (
            <div key={title} className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
              <span className="font-display text-sm text-[var(--text-primary)]">{title}</span>
              <p className="mt-3 text-sm leading-6 text-[var(--text-secondary)]">{copy}</p>
            </div>
          ))}
        </div>
      </section>
      <footer className="mx-auto max-w-6xl border-t border-[var(--border)] px-6 py-8 text-sm text-[var(--text-secondary)]">
        <p className="grid gap-3 md:grid-cols-3 md:items-center">
          <span className="md:text-left">Built by Abhinav Sinha</span>
          <a className="text-cyan-300 hover:text-cyan-200 md:text-center" href="mailto:sinhaabhinav015@gmail.com">sinhaabhinav015@gmail.com</a>
          <span className="md:text-right">© 2026 Abhinav Sinha</span>
        </p>
      </footer>
    </main>
  );
}

function ProductFlow() {
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-panel">
      <div className="mb-3 flex items-center justify-between border-b border-[var(--border)] pb-3">
        <span className="font-display text-xs uppercase text-[var(--text-secondary)]">Run pipeline</span>
        <span className="rounded-full bg-cyan-400/10 px-2 py-1 text-xs text-cyan-200">controlled</span>
      </div>
      <div className="grid gap-2">
        {workflow.map((item, index) => (
          <div key={item} className="flex items-center gap-3 rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] px-3 py-2">
            <span className="font-display text-xs text-cyan-300">{String(index + 1).padStart(2, "0")}</span>
            <span className="text-sm">{item}</span>
            {index < workflow.length - 1 ? <ArrowRight className="ml-auto text-[var(--text-secondary)]" size={15} /> : null}
          </div>
        ))}
      </div>
    </div>
  );
}
