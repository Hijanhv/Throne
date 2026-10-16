"use client";

import { ColorType, createChart, type IChartApi, type Time, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";

import type { EquityPoint, Timeframe } from "@/lib/types";

const IST_OFFSET = 5.5 * 3600; // the chart renders UTC, so shift intraday bars to read as IST

export function EquityChart({ points, interval }: { points: EquityPoint[]; interval: Timeframe }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#111111" },
        textColor: "#888888",
        fontFamily: "var(--font-mono), monospace",
        fontSize: 10,
      },
      grid: { vertLines: { color: "#161616" }, horzLines: { color: "#161616" } },
      rightPriceScale: { borderColor: "#1f1f1f" },
      timeScale: { borderColor: "#1f1f1f", timeVisible: interval !== "1d", secondsVisible: false },
      crosshair: {
        vertLine: { color: "#2f2f2f", labelBackgroundColor: "#1f1f1f" },
        horzLine: { color: "#2f2f2f", labelBackgroundColor: "#1f1f1f" },
      },
    });
    chartRef.current = chart;

    const last = points[points.length - 1]?.value ?? 100;
    const up = last >= 100;
    const series = chart.addAreaSeries({
      lineColor: up ? "#00ff88" : "#ff4444",
      topColor: up ? "rgba(0,255,136,0.28)" : "rgba(255,68,68,0.25)",
      bottomColor: "rgba(0,0,0,0)",
      lineWidth: 2,
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });
    series.setData(
      points.map((p) => ({
        time: (interval === "1d" ? p.date : ((p.time + IST_OFFSET) as UTCTimestamp)) as Time,
        value: p.value,
      })),
    );
    series.createPriceLine({
      price: 100,
      color: "#2f2f2f",
      lineWidth: 1,
      lineStyle: 2,
      axisLabelVisible: false,
      title: "",
    });
    chart.timeScale().fitContent();

    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [points, interval]);

  return <div ref={ref} className="h-full w-full" />;
}
