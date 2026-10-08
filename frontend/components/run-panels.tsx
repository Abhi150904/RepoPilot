import { BadgeCheck, GitPullRequestArrow, LockKeyhole } from "lucide-react";
import type { RunStatusResponse, PublishMode } from "@/lib/api";
import type { RunViewModel } from "@/lib/run-view-model";
import { Button } from "@/components/button";
import { publishModes } from "@/lib/sample-data";

export function RunTimeline({ view }: { view: RunViewModel }) {
  return (
    <aside className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
      <div className="mb-4 flex items-center justify-between">
        <p className="font-display text-xs uppercase text-[var(--text-secondary)]">Execution timeline</p>
        <span className="font-display text-xs text-cyan-300">{view.timeline.filter((item) => item.state === "complete").length}/{view.timeline.length}</span>
      </div>
      <div className="grid gap-1">
        {view.timeline.map((item, index) => {
          const Icon = item.icon;
          return (
            <div key={`${item.label}-${index}`} className="grid grid-cols-[32px_1fr] gap-3 border-b border-[var(--border)] py-3 last:border-b-0">
              <span className="grid h-8 w-8 place-items-center rounded-lg bg-[var(--surface-elevated)] text-cyan-300">
                <Icon size={16} />
              </span>
              <span>
                <strong className="block text-sm text-[var(--text-primary)]">{item.label}</strong>
                <small className="text-xs text-[var(--text-secondary)]">{item.detail}</small>
              </span>
            </div>
          );
        })}
      </div>
    </aside>
  );
}

export function ArtifactWorkspace({ view }: { view: RunViewModel }) {
  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)]">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] px-4 py-3">
        <div>
          <p className="font-display text-xs uppercase text-[var(--text-secondary)]">Artifact workspace</p>
          <h2 className="mt-1 font-display text-lg font-semibold">{view.diffFile}</h2>
        </div>
        <div className="flex gap-1 rounded-lg border border-[var(--border)] bg-[var(--background)] p-1">
          {["Plan", "Changes", "Tests", "Review"].map((tab, index) => (
            <button key={tab} className={index === 1 ? "rounded-md bg-[var(--surface-elevated)] px-3 py-1.5 text-xs text-[var(--text-primary)]" : "px-3 py-1.5 text-xs text-[var(--text-secondary)]"}>
              {tab}
            </button>
          ))}
        </div>
      </div>
      <div className="grid gap-4 p-4 xl:grid-cols-[0.75fr_1.25fr]">
        <div>
          <p className="font-display text-xs uppercase text-[var(--text-secondary)]">Plan</p>
          <div className="mt-3 grid gap-2">
            {view.planSteps.map((step, index) => (
              <div key={step} className="grid grid-cols-[36px_1fr] gap-3 rounded-lg bg-[var(--surface-elevated)] p-3 text-sm">
                <span className="font-display text-cyan-300">{String(index + 1).padStart(2, "0")}</span>
                <p className="text-[var(--text-secondary)]">{step}</p>
              </div>
            ))}
          </div>
        </div>
        <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[#07090c]">
          <div className="flex justify-between border-b border-[var(--border)] px-4 py-2 font-display text-xs text-[var(--text-secondary)]">
            <span>{view.diffFile}</span>
            <span>{view.diffStats}</span>
          </div>
          <pre className="overflow-x-auto py-3 text-xs">
            {view.diffLines.map((line, index) => (
              <code
                key={`${line.text}-${index}`}
                className={
                  line.kind === "add"
                    ? "block bg-lime-400/10 px-4 py-1 text-lime-200"
                    : line.kind === "remove"
                      ? "block bg-red-400/10 px-4 py-1 text-red-200"
                      : "block px-4 py-1 text-[var(--text-secondary)]"
                }
              >
                {line.kind === "add" ? "+ " : line.kind === "remove" ? "- " : "  "}
                {line.text}
              </code>
            ))}
          </pre>
        </div>
      </div>
    </section>
  );
}

export function RunIntelligence({ view }: { view: RunViewModel }) {
  const rows = [
    ["Review confidence", view.review.confidence],
    ["Changed files", String(view.changedFiles.length)],
    ["Risk", view.review.risk],
    ["Repair attempts", view.repairAttempts],
    ["Tokens", view.tokens]
  ];
  return (
    <aside className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
      <p className="font-display text-xs uppercase text-[var(--text-secondary)]">Run intelligence</p>
      <div className="mt-3 grid gap-3">
        {rows.map(([label, value]) => (
          <div key={label} className="border-b border-[var(--border)] pb-3 last:border-b-0">
            <span className="text-xs text-[var(--text-secondary)]">{label}</span>
            <strong className="mt-1 block font-display text-xl">{value}</strong>
          </div>
        ))}
      </div>
    </aside>
  );
}

export function ReviewPanel({
  run,
  view,
  isBusy,
  activeAction,
  onApprove,
  onReject,
  onPublish
}: {
  run: RunStatusResponse | null;
  view: RunViewModel;
  isBusy: boolean;
  activeAction: string | null;
  onApprove: () => void;
  onReject: () => void;
  onPublish: (mode: PublishMode) => void;
}) {
  const canAct = run?.lifecycle_status === "completed";
  const approvalDecision = run?.response?.result?.approval_decision;
  const approved = Boolean(
    approvalDecision &&
      typeof approvalDecision === "object" &&
      (approvalDecision as { approved?: unknown }).approved === true
  );
  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
      <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
        <p className="font-display text-xs uppercase text-[var(--text-secondary)]">Human review</p>
        <h1 className="mt-3 max-w-3xl font-display text-4xl font-semibold tracking-tight">Approve exactly what was reviewed.</h1>
        <div className="mt-6 grid gap-3 md:grid-cols-5">
          {view.verification.map((item) => (
            <div key={item.label} className="rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] p-3">
              <BadgeCheck className={item.verified ? "text-lime-300" : "text-[var(--text-secondary)]"} size={18} />
              <span className="mt-3 block text-sm">{item.label === "HEAD bound" ? "HEAD/base bound" : item.label}</span>
            </div>
          ))}
        </div>
        <div className="mt-6 grid gap-4 md:grid-cols-4">
          <Metric label="Changed files" value={String(view.changedFiles.length)} />
          <Metric label="Reviewer findings" value={String(view.review.blockers)} />
          <Metric label="Risk" value={view.review.risk} />
          <Metric label="Tests" value={view.tests.label} />
        </div>
      </section>
      <aside className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
        <LockKeyhole className="text-cyan-300" size={24} />
        <h2 className="mt-4 font-display text-2xl font-semibold">{canAct ? "Ready for decision" : "Awaiting completed run"}</h2>
        <p className="mt-3 text-sm leading-6 text-[var(--text-secondary)]">{canAct ? view.tests.summary : "Start a run and wait for it to complete before approval."}</p>
        <div className="mt-6 grid gap-2">
          <Button variant="danger" disabled={!canAct || isBusy} onClick={onReject}>Reject</Button>
          <Button variant="primary" disabled={!canAct || isBusy} onClick={onApprove}>Approve changes</Button>
        </div>
        {approved ? (
          <div className="mt-6 border-t border-[var(--border)] pt-5">
            <p className="font-display text-xs uppercase text-[var(--text-secondary)]">Publication options</p>
            <PublicationStatus view={view} activeAction={activeAction} />
            <div className="mt-3 grid gap-2">
              {publishModes.map((option) => (
                <Button
                  key={option.title}
                  variant="secondary"
                  disabled={isBusy}
                  onClick={() => onPublish(modeForTitle(option.title))}
                >
                  <GitPullRequestArrow size={16} />
                  {activeAction === modeForTitle(option.title) ? "Working..." : option.title}
                </Button>
              ))}
            </div>
          </div>
        ) : null}
      </aside>
    </div>
  );
}

function PublicationStatus({
  view,
  activeAction
}: {
  view: RunViewModel;
  activeAction: string | null;
}) {
  const isPublishing = activeAction && ["dry_run", "local", "push", "pr"].includes(activeAction);
  if (isPublishing) {
    return (
      <p className="mt-3 rounded-lg border border-cyan-300/30 bg-cyan-300/10 p-3 text-sm text-cyan-100">
        Publishing action is running. Keep this page open.
      </p>
    );
  }
  if (!view.publish.status || view.publish.status === "Locked") {
    return null;
  }
  const nextStep =
    view.publish.mode === "dry_run" && view.publish.status === "ready"
      ? "Dry run passed. Click Pull Request to commit, push, and open the PR."
      : null;
  return (
    <div className="mt-3 rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] p-3 text-sm">
      <div className="flex items-center justify-between gap-3">
        <span className="text-[var(--text-secondary)]">Status</span>
        <strong>{view.publish.status}</strong>
      </div>
      <p className="mt-2 text-[var(--text-secondary)]">{view.publish.summary}</p>
      {nextStep ? <p className="mt-2 text-cyan-200">{nextStep}</p> : null}
      {view.publish.branch && view.publish.branch !== "Not prepared" ? (
        <p className="mt-2 break-all text-xs text-[var(--text-secondary)]">Branch: {view.publish.branch}</p>
      ) : null}
      {view.publish.prUrl ? (
        <a className="mt-3 inline-flex text-sm font-medium text-cyan-300 hover:text-cyan-200" href={view.publish.prUrl} target="_blank" rel="noreferrer">
          Open pull request
        </a>
      ) : null}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] p-3">
      <span className="text-xs text-[var(--text-secondary)]">{label}</span>
      <strong className="mt-1 block font-display text-xl">{value}</strong>
    </div>
  );
}

function modeForTitle(title: string): PublishMode {
  if (title === "Dry Run") {
    return "dry_run";
  }
  if (title === "Local Commit") {
    return "local";
  }
  if (title === "Push Branch") {
    return "push";
  }
  return "pr";
}
