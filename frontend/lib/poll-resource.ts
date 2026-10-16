import { RepoPilotApiError, type RunStatusResponse } from "@/lib/api";

export function pollResource<T>({
  load,
  onData,
  onError,
  shouldPoll = () => true,
  intervalMs = 3000
}: {
  load: (signal: AbortSignal) => Promise<T>;
  onData: (value: T) => void;
  onError: (error: unknown) => void;
  shouldPoll?: (value: T) => boolean;
  intervalMs?: number;
}): () => void {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;

  async function refresh() {
    let repeat = true;
    try {
      const value = await load(controller.signal);
      if (controller.signal.aborted) return;
      onData(value);
      repeat = shouldPoll(value);
    } catch (error) {
      if (controller.signal.aborted) return;
      onError(error);
      repeat = !(error instanceof RepoPilotApiError && [401, 403, 404].includes(error.status));
    }
    if (!controller.signal.aborted && repeat) {
      timer = setTimeout(refresh, intervalMs);
    }
  }

  void refresh();
  return () => {
    controller.abort();
    clearTimeout(timer);
  };
}

export function runNeedsRefresh(run: RunStatusResponse): boolean {
  return run.lifecycle_status === "queued" ||
    run.lifecycle_status === "running" ||
    run.publication_status === "publishing";
}
