"use client";

import { useState } from "react";
import { toast } from "sonner";

import { JsonView } from "@/components/JsonView";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Label, Select } from "@/components/ui/input";
import { Dots, Empty, Panel, PanelLabel } from "@/components/ui/panel";
import { api, errorMessage } from "@/lib/api";
import type { BacktestResult, ParsedStrategy, Period, StrategyRule } from "@/lib/types";
import { describeRule } from "@/lib/utils";

interface Props {
  strategy: ParsedStrategy | null;
  parsing: boolean;
  onBacktest: (r: BacktestResult) => void;
  onBacktestStart: () => void;
  onBacktestEnd: () => void;
}

function RuleCard({ rule }: { rule: StrategyRule }) {
  const buy = rule.action === "BUY";
  return (
    <div className="flex items-center justify-between gap-3 border border-line bg-bg px-3 py-2.5">
      <span className="font-mono text-xs text-fg">{describeRule(rule)}</span>
      <span className={`shrink-0 font-mono text-xs font-bold ${buy ? "text-accent" : "text-danger"}`}>
        → {rule.action}
      </span>
    </div>
  );
}

function RuleGroup({ title, logic, rules }: { title: string; logic: "all" | "any"; rules: StrategyRule[] }) {
  if (rules.length === 0) return null;
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.18em] text-muted">
        {title}
        {rules.length > 1 && (
          <span className="text-fg/70">· {logic === "all" ? "all must hold" : "any one"}</span>
        )}
      </div>
      {rules.map((r, i) => (
        <RuleCard key={i} rule={r} />
      ))}
    </div>
  );
}

export function RuleViewer({ strategy, parsing, onBacktest, onBacktestStart, onBacktestEnd }: Props) {
  const [period, setPeriod] = useState<Period>("1y");
  const [capital, setCapital] = useState("100000");
  const [loading, setLoading] = useState(false);
  const [showJson, setShowJson] = useState(false);

  async function run() {
    if (!strategy) return;
    const cap = Number(capital);
    if (!Number.isFinite(cap) || cap <= 0) {
      toast.error("Capital must be a positive number");
      return;
    }
    setLoading(true);
    onBacktestStart();
    try {
      const res = await api.backtest({ strategy_id: strategy.id, period, initial_capital: cap });
      onBacktest(res);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setLoading(false);
      onBacktestEnd();
    }
  }

  const buys = strategy?.rules.filter((r) => r.action === "BUY") ?? [];
  const sells = strategy?.rules.filter((r) => r.action === "SELL") ?? [];
  const ai = strategy?.parser === "ai";

  return (
    <Panel className="border-b lg:border-b-0 lg:border-r">
      <PanelLabel
        right={
          strategy && (
            <Badge
              tone={ai ? "accent" : "warn"}
              title={ai ? "Parsed by the local LLM" : "Parsed by the offline regex engine"}
            >
              {ai ? "AI" : "Regex fallback"} · {Math.round(strategy.confidence * 100)}%
            </Badge>
          )
        }
      >
        Parsed rules
      </PanelLabel>

      {!strategy ? (
        <Empty>
          Parsed rules appear here.
          <br />
          Each rule is deterministic JSON, so the backtest and live engine read the same thing.
        </Empty>
      ) : (
        <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
          <div>
            <div className="font-mono text-sm font-bold text-fg">{strategy.name}</div>
            <div className="mt-1 font-mono text-[10px] uppercase tracking-[0.14em] text-muted">
              {strategy.symbol} · {strategy.timeframe} · {strategy.id.slice(0, 8)}
            </div>
          </div>

          <RuleGroup title="Entry" logic={strategy.entry_logic} rules={buys} />
          <RuleGroup title="Exit" logic={strategy.exit_logic} rules={sells} />

          {(strategy.stop_loss_pct || strategy.take_profit_pct) && (
            <div className="flex flex-wrap gap-2">
              {strategy.stop_loss_pct && <Badge tone="danger">Stop loss {strategy.stop_loss_pct}%</Badge>}
              {strategy.take_profit_pct && (
                <Badge tone="accent">Take profit {strategy.take_profit_pct}%</Badge>
              )}
            </div>
          )}

          {strategy.warnings.length > 0 && (
            <ul className="space-y-1 border-l-2 border-warn/60 pl-3">
              {strategy.warnings.map((w, i) => (
                <li key={i} className="font-mono text-[11px] leading-relaxed text-warn/90">
                  {w}
                </li>
              ))}
            </ul>
          )}

          <div>
            <button
              type="button"
              onClick={() => setShowJson((v) => !v)}
              className="mb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-muted hover:text-fg"
            >
              {showJson ? "▾" : "▸"} JSON
            </button>
            {showJson && <JsonView data={strategy.rules} />}
          </div>

          <div className="mt-auto space-y-3 border-t border-line pt-4">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label htmlFor="period">Period</Label>
                <Select id="period" value={period} onChange={(e) => setPeriod(e.target.value as Period)}>
                  <option value="3mo">3 months</option>
                  <option value="6mo">6 months</option>
                  <option value="1y">1 year</option>
                  <option value="2y">2 years</option>
                  <option value="5y">5 years</option>
                </Select>
              </div>
              <div>
                <Label htmlFor="bt-capital">Capital ₹</Label>
                <Input
                  id="bt-capital"
                  inputMode="numeric"
                  value={capital}
                  onChange={(e) => setCapital(e.target.value.replace(/[^\d.]/g, ""))}
                />
              </div>
            </div>
            <Button
              variant="outline"
              className="w-full"
              onClick={() => void run()}
              disabled={loading || parsing || strategy.rules.length === 0}
            >
              {loading ? (
                <>
                  Backtesting <Dots />
                </>
              ) : (
                "Backtest"
              )}
            </Button>
          </div>
        </div>
      )}
    </Panel>
  );
}
