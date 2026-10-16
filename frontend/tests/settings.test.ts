import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getAuthMe, getGitHubRepositories, RepoPilotApiError } from "@/lib/api";
import { loadSettings, type SettingsData } from "@/lib/settings-data";
import { SettingsContent } from "@/components/settings-content";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/api")>(),
  getAuthMe: vi.fn(),
  getGitHubRepositories: vi.fn()
}));

const auth = { authenticated: true, user: { github_user_id: 1, login: "example", name: "Example User" } };
const repositories = {
  repositories: [{ full_name: "example/demo", installation_id: 1, default_branch: "main", private: true }],
  install_url: "https://github.com/apps/example/installations/new"
};

describe("settings data", () => {
  beforeEach(() => vi.resetAllMocks());

  it("loads the account and authorized repositories", async () => {
    vi.mocked(getAuthMe).mockResolvedValue(auth);
    vi.mocked(getGitHubRepositories).mockResolvedValue(repositories);
    expect(await loadSettings()).toEqual({ auth, repositories, accountError: null, accessError: null, accessRequiresLogin: false });
  });

  it("preserves account data when repository access fails", async () => {
    vi.mocked(getAuthMe).mockResolvedValue(auth);
    vi.mocked(getGitHubRepositories).mockRejectedValue(new Error("GitHub unavailable"));
    const data = await loadSettings();
    expect(data.auth).toEqual(auth);
    expect(data.accountError).toBeNull();
    expect(data.accessError).toBe("Could not load repository access. Try again.");
  });

  it("does not treat an expired session as an API outage", async () => {
    vi.mocked(getAuthMe).mockResolvedValue({ authenticated: false });
    vi.mocked(getGitHubRepositories).mockRejectedValue(new RepoPilotApiError({ status: 401, code: "auth_required", message: "Sign in" }));
    const data = await loadSettings();
    expect(data.accessRequiresLogin).toBe(true);
    expect(data.accessError).toBeNull();
  });

  it("preserves repository data when account loading fails", async () => {
    vi.mocked(getAuthMe).mockRejectedValue(new Error("Account error"));
    vi.mocked(getGitHubRepositories).mockResolvedValue(repositories);
    const data = await loadSettings();
    expect(data.repositories).toEqual(repositories);
    expect(data.accessError).toBeNull();
    expect(data.accountError).toBeTruthy();
  });
});

describe("settings content", () => {
  beforeEach(() => vi.stubGlobal("React", React));
  afterEach(() => vi.unstubAllGlobals());

  const data: SettingsData = { auth, repositories, accountError: null, accessError: null, accessRequiresLogin: false };

  function render(overrides: Partial<React.ComponentProps<typeof SettingsContent>> = {}) {
    return renderToStaticMarkup(React.createElement(SettingsContent, {
      data, loading: false, signingOut: false, logoutError: null,
      onSignOut: vi.fn(), onRefresh: vi.fn(), ...overrides
    }));
  }

  it("shows real account details, repository access and sign out", () => {
    const html = render();
    expect(html).not.toContain("example/demo");
    expect(html).toContain("Example User");
    expect(html).toContain("Signed in");
    expect(html).toContain("Sign out");
    expect(html).toContain("1 repository connected");
    expect(html).toContain('href="/repositories"');
    expect(html).toContain('href="https://github.com/settings/installations"');
    expect(html).not.toContain(repositories.install_url);
    expect(html).toContain('rel="noopener noreferrer"');
    for (const placeholder of ["Requires hosted auth", "Hosted mode", "localhost:8000", "Approval policy", "token usage", "Local API"]) {
      expect(html).not.toContain(placeholder);
    }
  });

  it("shows loading instead of false signed-out or empty states", () => {
    const html = render({ data: null, loading: true });
    expect(html).toContain("Loading account...");
    expect(html).toContain("Loading repositories...");
    expect(html).not.toContain("Not signed in");
    expect(html).not.toContain("No repositories connected.");
  });

  it("offers sign in for an unauthenticated session", () => {
    const html = render({ data: { ...data, auth: { authenticated: false }, repositories: null, accessRequiresLogin: true } });
    expect(html).toContain("Sign in with GitHub");
    expect(html).not.toContain("Sign out");
    expect(html).not.toContain("Manage access");
  });

  it("shows repository errors without hiding the account", () => {
    const html = render({ data: { ...data, repositories: null, accessError: "Could not load repository access. Try again." } });
    expect(html).toContain("Example User");
    expect(html).toContain("Could not load repository access");
    expect(html).toContain('aria-label="Refresh settings"');
    expect(html).not.toContain("offline");
  });

  it("retains a manage-access action when no repositories are connected", () => {
    const html = render({ data: { ...data, repositories: { ...repositories, repositories: [] } } });
    expect(html).toContain("No repositories connected.");
    expect(html).toContain("Manage access");
  });

  it("disables sign out while in progress and reports logout failure", () => {
    expect(render({ signingOut: true })).toContain("Signing out...");
    expect(render({ logoutError: "Could not sign out. Try again." })).toContain("Could not sign out. Try again.");
  });
});
