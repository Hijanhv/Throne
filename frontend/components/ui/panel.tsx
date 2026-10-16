import * as React from "react";

import { cn } from "@/lib/utils";

export function Panel({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <section className={cn("flex min-h-0 min-w-0 flex-col border-line bg-surface", className)}>
      {children}
    </section>
  );
}

export function PanelLabel({ children, right }: { children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
      <h2 className="font-mono text-[11px] font-bold uppercase tracking-[0.2em] text-accent">{children}</h2>
      {right}
    </div>
  );
}

export function Dots() {
  return (
    <span className="inline-flex gap-1" aria-hidden>
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-1.5 w-1.5 animate-dot bg-current"
          style={{ animationDelay: `${i * 0.18}s` }}
        />
      ))}
    </span>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-1 items-center justify-center p-8 text-center font-mono text-xs leading-relaxed text-muted">
      {children}
    </div>
  );
}
