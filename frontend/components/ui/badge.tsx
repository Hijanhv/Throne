import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 border px-2 py-0.5 font-mono text-[10px] font-bold uppercase tracking-[0.14em]",
  {
    variants: {
      tone: {
        accent: "border-accent/40 bg-accent/10 text-accent",
        danger: "border-danger/40 bg-danger/10 text-danger",
        warn: "border-warn/40 bg-warn/10 text-warn",
        muted: "border-line bg-raised text-muted",
      },
    },
    defaultVariants: { tone: "muted" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}
