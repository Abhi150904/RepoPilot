import type { ButtonHTMLAttributes, AnchorHTMLAttributes, ReactNode } from "react";
import Link from "next/link";
import { cn } from "@/lib/cn";

const variants = {
  primary: "border-cyan-400/40 bg-cyan-400 text-slate-950 hover:bg-cyan-300",
  secondary: "border-[var(--border)] bg-[var(--surface-elevated)] text-[var(--text-primary)] hover:border-slate-500",
  ghost: "border-transparent bg-transparent text-[var(--text-secondary)] hover:bg-[var(--surface-elevated)] hover:text-[var(--text-primary)]",
  danger: "border-red-400/40 bg-red-500/12 text-red-200 hover:bg-red-500/18"
};

const base = "inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border px-3.5 text-sm font-medium transition duration-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300 disabled:cursor-not-allowed disabled:opacity-50";

export function Button({
  variant = "secondary",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: keyof typeof variants }) {
  return <button className={cn(base, variants[variant], className)} {...props} />;
}

export function ButtonLink({
  variant = "secondary",
  className,
  children,
  ...props
}: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string; variant?: keyof typeof variants; children: ReactNode }) {
  return (
    <Link className={cn(base, variants[variant], className)} {...props}>
      {children}
    </Link>
  );
}
