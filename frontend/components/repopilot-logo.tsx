import { cn } from "@/lib/cn";

export function RepoPilotLogo({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <svg
        aria-hidden="true"
        className="h-8 w-8 shrink-0"
        viewBox="0 0 32 32"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <rect x="3" y="3" width="26" height="26" rx="8" fill="#111419" />
        <path d="M10 23V9h7.2c3 0 5 1.8 5 4.5 0 2-1.1 3.4-2.9 4l4.1 5.5h-4.1l-3.6-5.1h-2.1V23H10Z" fill="#F5F7FA" />
        <path d="M13.6 15.2h3.2c1.1 0 1.8-.6 1.8-1.6 0-1.1-.7-1.6-1.8-1.6h-3.2v3.2Z" fill="#0B0D10" />
        <path d="M20 8.5c2.8.4 4.6 2.2 4.9 5.1M22.6 20.8c1.6-.9 2.5-2.3 2.7-4.3" stroke="#38BDF8" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
      <span className="font-display text-sm font-semibold tracking-tight text-[var(--text-primary)]">RepoPilot</span>
    </div>
  );
}
