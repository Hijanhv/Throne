"use client";

import dynamic from "next/dynamic";

import { Dots, Empty } from "@/components/ui/panel";
import type { BacktestResult, Trade } from "@/lib/types";
import { cn, formatINR, formatNum, formatPct, signed } from "@/lib/utils";

const EquityChart = dynamic(() => import("@/components/EquityChart").then((m) => m.EquityChart), {
  ssr: false,
});

function Stat({ label, value, tone }: { label: string; value: string; tone?: "up" | "down" }) {
  return (
    <div className="bg-surface p-3">
      <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted">{label}</div>
      <div
        className={cn(
          "tabular mt-1 font-mono text-lg font-bold",
          tone === "up" && "text-accent",
          tone === "down" && "text-danger",
        )}
      >
        {value}
      </div>
    </div>
  );
}

const REASON: Record<Trade["exit_reason"], string> = {
  signal: "Signal",
  stop_loss: "Stop",
  take_profit: "Target",
  end_of_data: "Open",
};

export function BacktestPanel({ result, loading }: { result: BacktestResult | null; loading: boolean }) {
  if (loading && !result)
    return (
      <Empty>
        <span className="flex items-center gap-2 text-accent">
          Running backtest <Dots />
        </span>
      </Empty>
    );
  if (!result)
    return (
      <Empty>
        Parse a strategy, then run a backtest.
        <br />
        Signals fire on a bar close and fill at the next bar open, so there is no lookahead.
      </Empty>
    );

  const tone = (v: number) => (v > 0 ? "up" : v < 0 ? "down" : undefined);

  return (
    <div className={cn("flex min-h-0 flex-1 flex-col", loading && "opacity-50")}>
      <div className="h-64 shrink-0 border-b border-line lg:h-[38%]">
        <EquityChart points={result.equity_curve} interval={result.interval} />
      </div>

      <div className="grid grid-cols-2 gap-px border-b border-line bg-line">
        <Stat label="Total P&L" value={signed(result.total_pnl)} tone={tone(result.total_pnl)} />
        <Stat label="Sharpe ratio" value={result.sharpe_ratio.toFixed(2)} tone={tone(result.sharpe_ratio)} />
        <Stat
          label="Max drawdown"
          value={formatPct(result.max_drawdown, false)}
          tone={result.max_drawdown < 0 ? "down" : undefined}
        />
        <Stat label="Win rate" value={formatPct(result.win_rate, false)} />
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-1 border-b border-line px-4 py-2.5 font-mono text-[10px] uppercase tracking-[0.12em] text-muted sm:grid-cols-4">
        <span>
          Return{" "}
          <b className={cn("tabular", result.total_return_pct >= 0 ? "text-accent" : "text-danger")}>
            {formatPct(result.total_return_pct)}
          </b>
        </span>
        <span>
          Buy &amp; hold <b className="tabular text-fg">{formatPct(result.benchmark_return_pct)}</b>
        </span>
        <span>
          Trades <b className="tabular text-fg">{result.total_trades}</b>
        </span>
        <span>
          {result.ticker} · {result.period} · {result.interval}
        </span>
      </div>

      {result.warnings.length > 0 && (
        <ul className="space-y-1 border-b border-line px-4 py-2">
          {result.warnings.map((w, i) => (
            <li key={i} className="font-mono text-[11px] text-warn/90">
              {w}
            </li>
          ))}
        </ul>
      )}

      <div className="min-h-[200px] flex-1 overflow-auto">
        <table className="w-full min-w-[480px] font-mono text-[11px]">
          <thead className="sticky top-0 bg-surface text-left text-[10px] uppercase tracking-[0.14em] text-muted">
            <tr className="border-b border-line">
              <th className="px-4 py-2 font-normal">Entry date</th>
              <th className="px-2 py-2 font-normal">Exit date</th>
              <th className="px-2 py-2 text-right font-normal">Entry → Exit</th>
              <th className="px-2 py-2 text-right font-normal">P&amp;L</th>
              <th className="px-4 py-2 text-right font-normal">Action</th>
            </tr>
          </thead>
          <tbody>
            {result.trades.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-muted">
                  No trades in this period
                </td>
              </tr>
            )}
            {[...result.trades].reverse().map((t, i) => (
              <tr key={`${t.entry_date}-${i}`} className="border-b border-line/60 hover:bg-raised">
                <td className="tabular px-4 py-2 text-fg/90">{t.entry_date}</td>
                <td className="tabular px-2 py-2 text-fg/90">{t.exit_date}</td>
                <td className="tabular px-2 py-2 text-right text-muted">
                  {formatNum(t.entry_price)} → {formatNum(t.exit_price)}
                </td>
                <td
                  className={cn("tabular px-2 py-2 text-right", t.pnl >= 0 ? "text-accent" : "text-danger")}
                >
                  {signed(t.pnl)}
                  <span className="ml-1 text-muted">({formatPct(t.pnl_pct)})</span>
                </td>
                <td className="px-4 py-2 text-right text-muted">LONG · {REASON[t.exit_reason]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="border-t border-line px-4 py-2 font-mono text-[10px] text-muted">
        Starting capital {formatINR(result.initial_capital)} · long only · fees 5 bps per side · {result.bars}{" "}
        bars
      </div>
    </div>
  );
}
