"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { BillingContent } from "@/components/billing-content";
import { getAuthMe, getBilling, RepoPilotApiError, simulateBillingRun, startSandboxCheckout, type BillingSimulation, type BillingStatus } from "@/lib/api";

export default function BillingPage() {
  const [data, setData] = useState<BillingStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [signedOut, setSignedOut] = useState(false);
  const [busy, setBusy] = useState<"checkout" | "simulation" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [simulation, setSimulation] = useState<BillingSimulation | null>(null);
  const actionLock = useRef(false);
  const keys = useRef<{ checkout?: string; simulation?: string }>({});

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const auth = await getAuthMe();
      setSignedOut(!auth.authenticated);
      if (auth.authenticated) setData(await getBilling());
      else setData(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load billing.");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => {
    const returned = new URLSearchParams(window.location.search).get("checkout");
    if (returned === "returned") setNotice("Returned from checkout. Your balance updates after payment confirmation.");
    if (returned === "cancelled") setNotice("You left checkout. No demo attempts have been added unless payment was confirmed.");
    void refresh();
    if (returned !== "returned") return;
    let count = 0;
    const timer = window.setInterval(() => {
      void refresh();
      if (++count >= 12) window.clearInterval(timer);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  async function act(kind: "checkout" | "simulation") {
    if (actionLock.current) return;
    actionLock.current = true;
    setBusy(kind);
    setError(null);
    const key = keys.current[kind] ?? crypto.randomUUID();
    keys.current[kind] = key;
    try {
      if (kind === "checkout") {
        const result = await startSandboxCheckout(key);
        window.location.assign(result.url);
      } else {
        setSimulation(await simulateBillingRun(key));
        delete keys.current[kind];
        await refresh();
      }
    } catch (err) {
      // Retry ambiguous network failures with the same key to avoid double spending.
      if (err instanceof RepoPilotApiError && err.status > 0 && err.status < 500) delete keys.current[kind];
      if (err instanceof RepoPilotApiError && err.code === "checkout_failed") delete keys.current[kind];
      setError(err instanceof Error ? err.message : "Billing request failed.");
    } finally { actionLock.current = false; setBusy(null); }
  }

  return <AppShell><BillingContent data={data} loading={loading} signedOut={signedOut} busy={busy} error={error} notice={notice}
    simulation={simulation} onRefresh={() => void refresh()} onCheckout={() => void act("checkout")} onSimulate={() => void act("simulation")} /></AppShell>;
}
