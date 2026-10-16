import { getAuthMe, getGitHubRepositories, RepoPilotApiError, type AuthMeResponse, type GitHubRepositoriesResponse } from "@/lib/api";

export type SettingsData = {
  auth: AuthMeResponse | null;
  repositories: GitHubRepositoriesResponse | null;
  accountError: string | null;
  accessError: string | null;
  accessRequiresLogin: boolean;
};

export async function loadSettings(): Promise<SettingsData> {
  const [account, access] = await Promise.allSettled([getAuthMe(), getGitHubRepositories()]);
  const accessRequiresLogin = access.status === "rejected" && access.reason instanceof RepoPilotApiError && access.reason.status === 401;
  return {
    auth: account.status === "fulfilled" ? account.value : null,
    repositories: access.status === "fulfilled" ? access.value : null,
    accountError: account.status === "rejected" ? "Could not load your GitHub account. Try again." : null,
    accessError: access.status === "rejected" && !accessRequiresLogin ? "Could not load repository access. Try again." : null,
    accessRequiresLogin
  };
}
