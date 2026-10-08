"use client";

import { useEffect, useState } from "react";
import { Github, KeyRound, ShieldCheck, UserRound } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { API_BASE_URL, getAuthMe, getHealth, getReady, githubLoginUrl, type AuthMeResponse, type ReadinessResponse } from "@/lib/api";

type ApiStatus = "checking" | "connected" | "disconnected";

const hostedSettings = [
  ["GitHub account", "Signed-in user, organization and GitHub App installation.", UserRound],
  ["Repository access", "Installed repositories, permissions and default target branch.", Github],
  ["Approval policy", "Who can approve runs, publish branches and open pull requests.", ShieldCheck],
  ["Usage", "Run history, token usage, model cost and rate limits.", KeyRound]
];

export default function SettingsPage() {
  const [apiStatus, setApiStatus] = useState<ApiStatus>("checking");
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);
  const [auth, setAuth] = useState<AuthMeResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [ready, me] = await Promise.all([getReady(), getAuthMe(), getHealth()]);
        if (!cancelled) {
          setApiStatus("connected");
          setReadiness(ready);
          setAuth(me);
        }
      } catch {
        if (!cancelled) {
          setApiStatus("disconnected");
        }
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <AppShell>
      <section className="grid gap-5">
        <header className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
          <p className="font-display text-xs uppercase text-[var(--text-secondary)]">Settings</p>
          <h1 className="mt-2 text-3xl font-semibold">Connection and access</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-[var(--text-secondary)]">
            RepoPilot keeps provider keys, GitHub tokens and repository credentials on the backend. The browser only sees session status and safe connection metadata.
          </p>
        </header>

        <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="font-display text-xs uppercase text-[var(--text-secondary)]">API connection</p>
              <p className="mt-2 break-all text-sm text-[var(--text-primary)]">{API_BASE_URL}</p>
            </div>
            <span className={badgeClass(apiStatus)}>{statusForApi(apiStatus)}</span>
          </div>
          <p className="mt-4 max-w-3xl text-sm leading-6 text-[var(--text-secondary)]">
            Hosted mode: {readiness?.hosted_mode ? "enabled" : "disabled"}. Environment: {readiness?.environment ?? "unknown"}.
          </p>
        </section>

        <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="font-display text-xs uppercase text-[var(--text-secondary)]">GitHub identity</p>
              <h2 className="mt-2 text-xl font-semibold">
                {auth?.authenticated && auth.user ? auth.user.login : readiness?.hosted_mode ? "Not signed in" : "Local backend mode"}
              </h2>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--text-secondary)]">
                {readiness?.hosted_mode
                  ? "Hosted runs use GitHub login for identity and GitHub App installations for repository access."
                  : "Local runs use backend environment configuration. Personal tokens stay on your machine and are never sent to the browser."}
              </p>
            </div>
            {readiness?.hosted_mode && !auth?.authenticated ? (
              <a className="inline-flex min-h-10 items-center rounded-lg border border-[var(--border)] px-4 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--surface-elevated)]" href={githubLoginUrl()}>
                Sign in with GitHub
              </a>
            ) : null}
          </div>
        </section>

        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {hostedSettings.map(([title, copy, Icon]) => (
            <article key={title as string} className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
              <Icon className="text-cyan-300" size={20} />
              <h2 className="mt-4 text-base font-semibold">{title as string}</h2>
              <p className="mt-2 text-sm leading-6 text-[var(--text-secondary)]">{copy as string}</p>
              <span className="mt-4 inline-flex rounded-full border border-[var(--border)] px-2 py-0.5 text-xs text-[var(--text-secondary)]">
                Requires hosted auth
              </span>
            </article>
          ))}
        </section>
      </section>
    </AppShell>
  );
}

function statusForApi(status: ApiStatus): string {
  if (status === "connected") {
    return "Local API connected";
  }
  if (status === "disconnected") {
    return "Local API offline";
  }
  return "Checking local API";
}

function badgeClass(status: ApiStatus): string {
  const tone = status === "connected"
    ? "border-lime-300/30 bg-lime-300/10 text-lime-200"
    : status === "disconnected"
      ? "border-red-300/30 bg-red-300/10 text-red-200"
      : "border-cyan-300/25 bg-cyan-300/10 text-cyan-200";
  return `rounded-full border px-2.5 py-1 text-xs ${tone}`;
}
