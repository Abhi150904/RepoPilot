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

export type EvaluationSuite = {
  id: number;
  name: string;
  description?: string | null;
  eval_type: "retrieval" | "workflow";
  version: string;
  created_at: string;
};

export type EvaluationMetric = {
  metric_name: string;
  metric_value?: number | null;
  metadata?: Record<string, unknown>;
};

export type EvaluationCaseResult = {
  id: number;
  eval_run_id: string;
  eval_case_id: number;
  case_key: string;
  status: "passed" | "failed" | "error";
  output: Record<string, unknown>;
  measurements: Record<string, unknown>;
  error_type?: string | null;
  safe_error_message?: string | null;
  duration_ms?: number | null;
  created_at: string;
};

export type EvaluationRun = {
  id: string;
  suite_id: number;
  suite_name: string;
  eval_type: "retrieval" | "workflow";
  status: "queued" | "running" | "completed" | "failed" | "interrupted";
  configuration: Record<string, unknown>;
  metrics: EvaluationMetric[];
  case_results: EvaluationCaseResult[];
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  created_by?: string | null;
  error_type?: string | null;
  safe_error_message?: string | null;
};

export type EvaluationComparison = {
  baseline_run_id: string;
  current_run_id: string;
  compatible: boolean;
  warning?: string | null;
  metrics: Array<{
    metric_name: string;
    baseline?: number | null;
    current?: number | null;
    delta?: number | null;
    direction: "higher_is_better" | "lower_is_better" | "neutral";
  }>;
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

export async function createRun(request: RunRequest): Promise<RunStatusResponse> {
  return apiFetch<RunStatusResponse>("/runs", {
    method: "POST",
    body: JSON.stringify(request)
  });
}

export async function listRuns(): Promise<RunStatusResponse[]> {
  return apiFetch<RunStatusResponse[]>("/runs");
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

export async function getRun(runId: string): Promise<RunStatusResponse> {
  return apiFetch<RunStatusResponse>(`/runs/${runId}`);
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

export async function listEvaluationSuites(): Promise<EvaluationSuite[]> {
  return apiFetch<EvaluationSuite[]>("/evaluations/suites");
}

export async function listEvaluationRuns(): Promise<EvaluationRun[]> {
  return apiFetch<EvaluationRun[]>("/evaluations/runs");
}

export async function getEvaluationRun(evalRunId: string): Promise<EvaluationRun> {
  return apiFetch<EvaluationRun>(`/evaluations/runs/${evalRunId}`);
}

export async function createEvaluationRun(request: {
  suite: string;
  configuration?: Record<string, unknown>;
}): Promise<EvaluationRun> {
  return apiFetch<EvaluationRun>("/evaluations/runs", {
    method: "POST",
    body: JSON.stringify({ configuration: {}, ...request })
  });
}

export async function compareEvaluationRuns(runIds: string[]): Promise<EvaluationComparison> {
  return apiFetch<EvaluationComparison>(`/evaluations/compare?run_ids=${encodeURIComponent(runIds.join(","))}`);
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
