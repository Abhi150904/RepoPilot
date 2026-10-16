import Link from "next/link";
import { ExternalLink, Github, LogOut, RefreshCw } from "lucide-react";
import { Button, ButtonLink } from "@/components/button";
import { githubLoginUrl } from "@/lib/api";
import type { SettingsData } from "@/lib/settings-data";

export function SettingsContent({ data, loading, signingOut, logoutError, onSignOut, onRefresh }: {
  data: SettingsData | null;
  loading: boolean;
  signingOut: boolean;
  logoutError: string | null;
  onSignOut: () => void;
  onRefresh: () => void;
}) {
  const user = data?.auth?.authenticated ? data.auth.user : null;
  const repositories = data?.repositories?.repositories ?? [];
  return (
    <div className="mx-auto w-full max-w-4xl">
      <header className="flex items-center justify-between gap-4 border-b border-[var(--border)] pb-5">
        <div>
          <p className="font-display text-xs uppercase text-[var(--text-secondary)]">Settings</p>
          <h1 className="mt-2 text-2xl font-semibold">Account and access</h1>
        </div>
        <Button onClick={onRefresh} disabled={loading || signingOut} aria-label="Refresh settings" title="Refresh settings">
          <RefreshCw size={18} className={loading ? "animate-spin" : ""} aria-hidden="true" />
        </Button>
      </header>

      <section className="border-b border-[var(--border)] py-6" aria-labelledby="account-heading" aria-busy={loading}>
        <h2 id="account-heading" className="text-lg font-semibold">GitHub account</h2>
        {loading ? <p className="mt-3 text-sm text-[var(--text-secondary)]" role="status">Loading account...</p> : data?.accountError ? (
          <p className="mt-3 text-sm text-red-200" role="alert">{data.accountError}</p>
        ) : user ? (
          <div className="mt-4 flex flex-wrap items-center justify-between gap-4">
            <div className="flex min-w-0 items-center gap-3">
              <Github size={24} className="shrink-0 text-[var(--text-secondary)]" aria-hidden="true" />
              <div className="min-w-0">
                <p className="break-all font-medium">{user.login}</p>
                {user.name ? <p className="break-words text-sm text-[var(--text-secondary)]">{user.name}</p> : null}
                <p className="mt-1 text-xs text-lime-200">Signed in</p>
              </div>
            </div>
            <Button onClick={onSignOut} disabled={signingOut}>
              <LogOut size={16} aria-hidden="true" />{signingOut ? "Signing out..." : "Sign out"}
            </Button>
          </div>
        ) : (
          <div className="mt-3">
            <p className="text-sm text-[var(--text-secondary)]">Not signed in</p>
            <ButtonLink className="mt-4" variant="primary" href={githubLoginUrl()}><Github size={16} aria-hidden="true" />Sign in with GitHub</ButtonLink>
          </div>
        )}
        {logoutError ? <p className="mt-3 text-sm text-red-200" role="alert">{logoutError}</p> : null}
      </section>

      <section className="py-6" aria-labelledby="access-heading" aria-busy={loading}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="access-heading" className="text-lg font-semibold">Repository access</h2>
          {!loading && user ? (
            <ButtonLink href="https://github.com/settings/installations" target="_blank" rel="noopener noreferrer">Manage access<ExternalLink size={15} aria-hidden="true" /></ButtonLink>
          ) : null}
        </div>
        {loading ? <p className="mt-3 text-sm text-[var(--text-secondary)]" role="status">Loading repositories...</p> : data?.accessError ? (
          <p className="mt-3 text-sm text-red-200" role="alert">{data.accessError}</p>
        ) : data?.accessRequiresLogin ? (
          <p className="mt-3 text-sm text-[var(--text-secondary)]">Sign in with GitHub to view repository access.</p>
        ) : repositories.length ? (
          <>
            <p className="mt-3 text-sm text-[var(--text-secondary)]">{repositories.length} {repositories.length === 1 ? "repository" : "repositories"} connected</p>
            <Link className="mt-3 inline-flex text-sm text-cyan-300 hover:text-cyan-200" href="/repositories">View repositories</Link>
          </>
        ) : (
          <p className="mt-3 text-sm text-[var(--text-secondary)]">No repositories connected.</p>
        )}
      </section>
    </div>
  );
}
