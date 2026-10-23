"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { BillingContent } from "@/components/billing-content";
import { getAuthMe, getBilling, RepoPilotApiError, startSandboxCheckout, type BillingStatus } from "@/lib/api";

export default function BillingPage() {
  const [data, setData] = useState<BillingStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [signedOut, setSignedOut] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const actionLock = useRef(false);
  const checkoutKey = useRef<string | null>(null);

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
    const cleanUrl = new URL(window.location.href);
    if (cleanUrl.searchParams.has("customer_session_token")) {
      cleanUrl.searchParams.delete("customer_session_token");
      window.history.replaceState(window.history.state, "", cleanUrl.pathname + cleanUrl.search + cleanUrl.hash);
    }
    if (returned === "returned") setNotice("Returned from checkout. Your balance updates after payment confirmation.");
    if (returned === "cancelled") setNotice("Checkout closed. Credits are added only after payment confirmation.");
    void refresh();
    if (returned !== "returned") return;
    let count = 0;
    const timer = window.setInterval(() => {
      void refresh();
      if (++count >= 12) window.clearInterval(timer);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  async function checkout() {
    if (actionLock.current) return;
    actionLock.current = true;
    setBusy(true);
    setError(null);
    const key = checkoutKey.current ?? crypto.randomUUID();
    checkoutKey.current = key;
    try {
      const result = await startSandboxCheckout(key);
      window.location.assign(result.url);
    } catch (err) {
      // Retry ambiguous network failures with the same key to avoid double spending.
      if (err instanceof RepoPilotApiError && err.status > 0 && err.status < 500) checkoutKey.current = null;
      if (err instanceof RepoPilotApiError && err.code === "checkout_failed") checkoutKey.current = null;
      setError(err instanceof Error ? err.message : "Billing request failed.");
    } finally { actionLock.current = false; setBusy(false); }
  }

  return <AppShell><BillingContent data={data} loading={loading} signedOut={signedOut} busy={busy} error={error} notice={notice}
    onRefresh={() => void refresh()} onCheckout={() => void checkout()} /></AppShell>;
}
