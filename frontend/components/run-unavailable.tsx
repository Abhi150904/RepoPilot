import { ButtonLink } from "@/components/button";

export function RunUnavailable({ message }: { message: string }) {
  return (
    <section role="alert" className="border border-[var(--border)] bg-[var(--surface)] p-6">
      <h1 className="font-display text-2xl font-semibold">Run unavailable</h1>
      <p className="mt-3 text-sm text-[var(--text-secondary)]">{message}</p>
      <div className="mt-5">
        <ButtonLink href="/runs" variant="primary">Back to runs</ButtonLink>
      </div>
    </section>
  );
}
