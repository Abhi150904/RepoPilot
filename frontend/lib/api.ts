export type PublishMode = "dry_run" | "local" | "push" | "pr";

export type RunRequest = {
  issue?: string;
  repository?: string;
  issue_number?: number;
  apply_changes?: boolean;
  run_tests?: boolean;
  test_command?: string[];
  max_repair_attempts?: number;
};

export type HealthResponse = {
  status: "ok";
  service: "repopilot";
};

export type ReadinessResponse = {
  status: "ready" | "degraded";
  service: "repopilot";
  environment: string;
  hosted_mode: boolean;
  checks: Record<string, boolean>;
  warnings: string[];
};

export type AuthUser = {
  github_user_id: number;
  login: string;
  avatar_url?: string | null;
  name?: string | null;
};

export type AuthMeResponse = {
  authenticated: boolean;
  user?: AuthUser | null;
  csrf_token?: string | null;
};

export type GitHubRepository = {
  full_name: string;
  installation_id: number;
  default_branch?: string | null;
  private?: boolean | null;
};

export type GitHubRepositoriesResponse = {
  repositories: GitHubRepository[];
  install_url?: string | null;
};

export type RunError = {
  code: string;
  message: string;
  type?: string | null;
  details?: Record<string, unknown>;
};

export type RunResponse = {
  status: string;
  next_action: string;
  summary: string;
  run_summary: Record<string, unknown>;
  result: Record<string, unknown>;
};

export type RunStatusResponse = {
  run_id: string;
  lifecycle_status: "queued" | "running" | "completed" | "failed" | "interrupted";
  publication_status?: "not_started" | "ready" | "publishing" | "published" | "failed";
  created_at?: string;
  updated_at?: string;
  request: Record<string, unknown>;
  events?: RunEvent[];
  response?: RunResponse | null;
  error?: RunError | null;
};

export type RunEvent = {
  run_id: string;
  event_type: string;
  created_at: string;
  metadata?: Record<string, unknown>;
};

export class RepoPilotApiError extends Error {
  code: string;
  status: number;

  constructor({ code, message, status }: { code: string; message: string; status: number }) {
    super(message);
    this.name = "RepoPilotApiError";
    this.code = code;
    this.status = status;
  }
}

export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_REPOPILOT_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

let csrfToken: string | null = null;

export function githubLoginUrl(): string {
  return `${API_BASE_URL}/auth/github/login`;
}

export async function getAuthMe(): Promise<AuthMeResponse> {
  const response = await apiFetch<AuthMeResponse>("/auth/me");
  csrfToken = response.csrf_token ?? null;
  return response;
}

export async function logout(): Promise<AuthMeResponse> {
  const response = await apiFetch<AuthMeResponse>("/auth/logout", {
    method: "POST"
  });
  csrfToken = response.csrf_token ?? null;
  return response;
}

export async function createRun(request: RunRequest, requestKey?: string): Promise<RunStatusResponse> {
  return apiFetch<RunStatusResponse>("/runs", {
    method: "POST",
    ...(requestKey ? { headers: { "Idempotency-Key": requestKey } } : {}),
    body: JSON.stringify(request)
  });
}

export async function listRuns(signal?: AbortSignal): Promise<RunStatusResponse[]> {
  return apiFetch<RunStatusResponse[]>("/runs", { signal, cache: "no-store" });
}

export async function getHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>("/health");
}

export async function getReady(): Promise<ReadinessResponse> {
  return apiFetch<ReadinessResponse>("/ready");
}

export async function getGitHubRepositories(): Promise<GitHubRepositoriesResponse> {
  return apiFetch<GitHubRepositoriesResponse>("/github/repositories");
}

export type BillingStatus = {
  enabled: boolean;
  environment: "sandbox";
  demo_balance: number;
  pack_attempts: number;
  test_price_cents: number;
  currency: string;
  purchases: { id: string; state: string; created_at: string }[];
  activity: { id: string; kind: string; delta: number; created_at: string }[];
};

export type BillingSimulation = {
  simulation_id: string;
  created_at: string;
  simulated: true;
  summary: string;
  patch: string;
  checks: string[];
  demo_balance: number;
};

export async function getBilling(signal?: AbortSignal): Promise<BillingStatus> {
  return apiFetch<BillingStatus>("/billing", { signal, cache: "no-store" });
}

export async function startSandboxCheckout(requestKey: string): Promise<{ id: string; url: string }> {
  return apiFetch("/billing/checkout", { method: "POST", body: JSON.stringify({ request_key: requestKey }) });
}

export type RunUsage = {
  enforced: boolean;
  introductory: { total: number; used: number; reserved: number; remaining: number } | null;
  simulation_credits: number;
  billing_enabled: boolean;
};

export async function getRunUsage(signal?: AbortSignal): Promise<RunUsage> {
  return apiFetch("/usage", { signal, cache: "no-store" });
}

export async function createSimulation(requestKey: string): Promise<BillingSimulation> {
  return apiFetch("/simulations", { method: "POST", body: JSON.stringify({ request_key: requestKey }) });
}

export async function listSimulations(): Promise<BillingSimulation[]> {
  return apiFetch("/simulations", { cache: "no-store" });
}

export async function getRun(runId: string, signal?: AbortSignal): Promise<RunStatusResponse> {
  return apiFetch<RunStatusResponse>(`/runs/${runId}`, { signal, cache: "no-store" });
}

export async function approveRun(runId: string): Promise<RunStatusResponse> {
  return apiFetch<RunStatusResponse>(`/runs/${runId}/approve`, {
    method: "POST",
    body: JSON.stringify({})
  });
}

export async function rejectRun(runId: string): Promise<RunStatusResponse> {
  return apiFetch<RunStatusResponse>(`/runs/${runId}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason: "Rejected from RepoPilot frontend." })
  });
}

export async function publishRun(
  runId: string,
  mode: PublishMode
): Promise<RunStatusResponse> {
  return apiFetch<RunStatusResponse>(`/runs/${runId}/publish`, {
    method: "POST",
    body: JSON.stringify({ mode })
  });
}

async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  const headers = {
    ...(init.body ? { "Content-Type": "application/json" } : {}),
    ...(csrfToken && init.method && init.method !== "GET" ? { "X-CSRF-Token": csrfToken } : {}),
    ...init.headers
  };
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers,
      credentials: "include"
    });
  } catch (error) {
    throw new RepoPilotApiError({
      code: "api_unreachable",
      message: `Could not reach RepoPilot API at ${API_BASE_URL}.`,
      status: 0
    });
  }

  const payload = await readJson(response);
  if (!response.ok) {
    const error = payload?.error;
    throw new RepoPilotApiError({
      code: typeof error?.code === "string" ? error.code : "api_error",
      message: typeof error?.message === "string" ? error.message : "RepoPilot API request failed.",
      status: response.status
    });
  }
  return payload as T;
}

async function readJson(response: Response): Promise<any> {
  const text = await response.text();
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}
