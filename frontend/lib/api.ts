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

export type RunError = {
  code: string;
  message: string;
  type?: string | null;
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
  lifecycle_status: "queued" | "running" | "completed" | "failed";
  request: Record<string, unknown>;
  response?: RunResponse | null;
  error?: RunError | null;
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

export async function createRun(request: RunRequest): Promise<RunStatusResponse> {
  return apiFetch<RunStatusResponse>("/runs", {
    method: "POST",
    body: JSON.stringify(request)
  });
}

export async function getHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>("/health");
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

async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  const headers = {
    ...(init.body ? { "Content-Type": "application/json" } : {}),
    ...init.headers
  };
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers
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
