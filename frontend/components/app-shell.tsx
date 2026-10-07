"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import * as Tooltip from "@radix-ui/react-tooltip";
import {
  Braces,
  Command,
  GitBranch,
  Home,
  ListChecks,
  Menu,
  Play,
  Search,
  Settings,
  X
} from "lucide-react";
import { cn } from "@/lib/cn";
import { RepoPilotLogo } from "@/components/repopilot-logo";

const navItems = [
  { href: "/app", label: "Command Center", icon: Home },
  { href: "/runs", label: "Runs", icon: ListChecks },
  { href: "/repositories", label: "Repositories", icon: GitBranch },
  { href: "/evaluations", label: "Evaluations", icon: Braces },
  { href: "/settings", label: "Settings", icon: Settings }
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);

  useEffect(() => {
    setCollapsed(window.localStorage.getItem("repopilot.sidebar") === "collapsed");
  }, []);

  useEffect(() => {
    window.localStorage.setItem("repopilot.sidebar", collapsed ? "collapsed" : "expanded");
  }, [collapsed]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen(true);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <div className="min-h-screen bg-[var(--background)] text-[var(--text-primary)]">
      <Tooltip.Provider delayDuration={160}>
        <aside
          className={cn(
            "fixed inset-y-0 left-0 z-30 flex flex-col border-r border-[var(--border)] bg-[var(--surface)] transition-[width] duration-200",
            collapsed ? "w-[72px]" : "w-[232px]"
          )}
        >
          <div className="flex h-16 items-center justify-between px-4">
            <Link href="/app" title="RepoPilot">
              <RepoPilotLogo className={collapsed ? "[&_span]:hidden" : ""} />
            </Link>
            <button
              aria-label="Toggle sidebar"
              className="grid h-9 w-9 place-items-center rounded-lg text-[var(--text-secondary)] hover:bg-[var(--surface-elevated)] hover:text-[var(--text-primary)]"
              onClick={() => setCollapsed((value) => !value)}
            >
              <Menu size={18} />
            </button>
          </div>
          <nav className="grid gap-1 px-3 py-3">
            {navItems.map((item) => (
              <SidebarItem key={item.href} collapsed={collapsed} {...item} />
            ))}
          </nav>
          <div className="mt-auto p-3">
            <button
              className={cn(
                "flex min-h-10 w-full items-center gap-3 rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] px-3 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
                collapsed && "justify-center px-0"
              )}
              title="Command palette"
              onClick={() => setPaletteOpen(true)}
            >
              <Command size={17} />
              {!collapsed ? <span>Cmd/Ctrl K</span> : null}
            </button>
          </div>
        </aside>
      </Tooltip.Provider>
      <div className={cn("transition-[padding] duration-200", collapsed ? "pl-[72px]" : "pl-[232px]")}>
        <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-[var(--border)] bg-[var(--background)]/90 px-6 backdrop-blur">
          <div aria-hidden="true" />
          <button
            className="hidden min-h-10 items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] md:flex"
            onClick={() => setPaletteOpen(true)}
          >
            <Search size={16} />
            Search actions
            <kbd className="rounded border border-[var(--border)] px-1.5 py-0.5 font-display text-[10px]">Ctrl K</kbd>
          </button>
        </header>
        <main className="px-6 py-6">{children}</main>
      </div>
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </div>
  );
}

function SidebarItem({
  href,
  label,
  icon: Icon,
  collapsed
}: {
  href: string;
  label: string;
  icon: typeof Home;
  collapsed: boolean;
}) {
  const pathname = usePathname();
  const active = pathname === href || (href !== "/app" && pathname.startsWith(href));
  const link = (
    <Link
      href={href}
      className={cn(
        "flex min-h-10 items-center gap-3 rounded-lg px-3 text-sm transition duration-200",
        active ? "bg-[var(--surface-elevated)] text-[var(--text-primary)]" : "text-[var(--text-secondary)] hover:bg-[var(--surface-elevated)] hover:text-[var(--text-primary)]",
        collapsed && "justify-center px-0"
      )}
    >
      <Icon size={18} />
      {!collapsed ? <span>{label}</span> : null}
    </Link>
  );

  if (!collapsed) {
    return link;
  }

  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>{link}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content className="z-50 rounded-lg border border-[var(--border)] bg-[var(--surface-elevated)] px-2 py-1 text-xs text-[var(--text-primary)] shadow-panel" side="right">
          {label}
          <Tooltip.Arrow className="fill-[var(--surface-elevated)]" />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}

function CommandPalette({
  open,
  onOpenChange
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();
  const actions = useMemo(
    () => [
      { label: "New run", href: "/app", icon: Play },
      ...navItems.map((item) => ({ label: item.label, href: item.href, icon: item.icon }))
    ],
    []
  );

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/55 backdrop-blur-sm" />
        <Dialog.Content className="fixed left-1/2 top-24 z-50 w-[calc(100vw-2rem)] max-w-xl -translate-x-1/2 overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)] shadow-2xl">
          <Dialog.Title className="sr-only">Command palette</Dialog.Title>
          <Dialog.Description className="sr-only">Jump to a RepoPilot action or route.</Dialog.Description>
        <div className="flex items-center gap-3 border-b border-[var(--border)] px-4 py-3">
          <Search size={18} className="text-cyan-300" />
          <span className="flex-1 text-sm text-[var(--text-secondary)]">Jump to a RepoPilot action</span>
          <Dialog.Close aria-label="Close command palette">
            <X size={18} />
          </Dialog.Close>
        </div>
        <div className="grid gap-1 p-2">
          {actions.map((action) => {
            const Icon = action.icon;
            return (
              <button
                key={action.label}
                className="flex min-h-11 items-center gap-3 rounded-lg px-3 text-left text-sm text-[var(--text-secondary)] hover:bg-[var(--surface-elevated)] hover:text-[var(--text-primary)]"
                onClick={() => {
                  router.push(action.href);
                  onOpenChange(false);
                }}
              >
                <Icon size={17} />
                {action.label}
              </button>
            );
          })}
        </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
