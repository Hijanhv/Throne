import * as React from "react";

import { cn } from "@/lib/utils";

export const fieldClass =
  "h-10 w-full border border-line bg-bg px-3 font-mono text-sm text-fg caret-accent placeholder:text-muted/60 focus:border-accent/60 focus:outline-none";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => <input ref={ref} className={cn(fieldClass, className)} {...props} />,
);
Input.displayName = "Input";

export const Select = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, children, ...props }, ref) => (
    <select ref={ref} className={cn(fieldClass, "appearance-none pr-8", className)} {...props}>
      {children}
    </select>
  ),
);
Select.displayName = "Select";

export function Label({ children, htmlFor }: { children: React.ReactNode; htmlFor?: string }) {
  return (
    <label
      htmlFor={htmlFor}
      className="mb-1.5 block font-mono text-[10px] uppercase tracking-[0.18em] text-muted"
    >
      {children}
    </label>
  );
}
