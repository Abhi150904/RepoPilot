"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { SettingsContent } from "@/components/settings-content";
import { logout } from "@/lib/api";
import { loadSettings, type SettingsData } from "@/lib/settings-data";

export default function SettingsPage() {
  const [data, setData] = useState<SettingsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [signingOut, setSigningOut] = useState(false);
  const [logoutError, setLogoutError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void loadSettings().then((next) => {
      if (!cancelled) {
        setData(next);
        setLoading(false);
      }
    });
    return () => { cancelled = true; };
  }, [revision]);

  async function signOut() {
    setSigningOut(true);
    setLogoutError(null);
    try {
      await logout();
      window.location.assign("/");
    } catch {
      setLogoutError("Could not sign out. Try again.");
      setSigningOut(false);
    }
  }

  return (
    <AppShell>
      <SettingsContent
        data={data}
        loading={loading}
        signingOut={signingOut}
        logoutError={logoutError}
        onSignOut={signOut}
        onRefresh={() => setRevision((value) => value + 1)}
      />
    </AppShell>
  );
}
