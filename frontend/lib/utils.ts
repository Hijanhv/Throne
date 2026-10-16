import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

import type { StrategyRule } from "./types";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 });
const num = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });

export const formatINR = (v: number): string => inr.format(v);
export const formatNum = (v: number): string => num.format(v);
export const formatPct = (v: number, signed = true): string =>
  `${signed && v > 0 ? "+" : ""}${v.toFixed(2)}%`;
export const signed = (v: number): string => `${v > 0 ? "+" : ""}${formatINR(v)}`;

function label(ind: string, period: number | null): string {
  if (ind === "PRICE" || ind === "MACD" || ind === "VOLUME" || period === null) return ind;
  return `${ind}(${period})`;
}

/** Same wording as StrategyRule.describe() in the backend. */
export function describeRule(r: StrategyRule): string {
  const left = label(r.indicator, r.period);
  let right: string;
  if (r.compare_to) right = label(r.compare_to, r.compare_period);
  else if (r.value === null) right = "SIGNAL LINE";
  else if (r.indicator === "VOLUME") right = `${r.value}x AVG VOLUME`;
  else if (r.indicator === "BB")
    right = r.value === 0 ? "LOWER BAND" : r.value === 1 ? "UPPER BAND" : `${r.value}`;
  else right = `${r.value}`;
  return `IF ${left} ${r.operator.replace(/_/g, " ")} ${right}`;
}
