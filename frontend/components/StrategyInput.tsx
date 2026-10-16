"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input, Label, Select } from "@/components/ui/input";
import { Dots, Panel, PanelLabel } from "@/components/ui/panel";
import { api, errorMessage } from "@/lib/api";
import type { ParsedStrategy, Timeframe } from "@/lib/types";

const PLACEHOLDER =
  "Describe your strategy in plain English. e.g. Buy NIFTY50 when RSI drops below 30 and 20 EMA crosses above 50 EMA. Sell when RSI exceeds 70 or 2% stop loss hits.";

const EXAMPLES: { label: string; text: string; symbol: string }[] = [
  {
    label: "RSI mean reversion",
    text: "Buy when RSI drops below 35. Sell when RSI exceeds 65 or 2% stop loss hits.",
    symbol: "RELIANCE",
  },
  {
    label: "EMA trend",
    text: "Buy when 20 EMA crosses above 50 EMA. Sell when 20 EMA crosses below 50 EMA. Stop loss 3%.",
    symbol: "NIFTY50",
  },
  {
    label: "MACD + trend filter",
    text: "Buy when MACD crosses above signal line and price is above 200 SMA. Exit when MACD crosses below signal. Target 6%, stop loss 2%.",
    symbol: "HDFCBANK",
  },
  {
    label: "Bollinger bounce",
    text: "Buy when price touches the lower bollinger band. Sell at the upper band or 2.5% stop loss.",
    symbol: "INFY",
  },
];

export function StrategyInput({ onParsed }: { onParsed: (s: ParsedStrategy) => void }) {
  const [text, setText] = useState("");
  const [symbol, setSymbol] = useState("NIFTY50");
  const [timeframe, setTimeframe] = useState<Timeframe>("1d");
  const [loading, setLoading] = useState(false);

  async function submit() {
    if (text.trim().length < 3) {
      toast.error("Write a strategy first");
      return;
    }
    setLoading(true);
    try {
      const parsed = await api.parse({ text: text.trim(), symbol: symbol.trim() || "NIFTY50", timeframe });
      onParsed(parsed);
      toast.success(`Parsed ${parsed.rules.length} rule${parsed.rules.length === 1 ? "" : "s"}`);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <Panel className="border-b lg:border-b-0 lg:border-r">
      <PanelLabel>Strategy</PanelLabel>
      <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void submit();
          }}
          placeholder={PLACEHOLDER}
          spellCheck={false}
          aria-label="Strategy in plain English"
          className="min-h-[220px] flex-1 resize-none border border-line bg-bg p-4 font-mono text-sm leading-relaxed text-fg caret-accent placeholder:text-muted/50 focus:border-accent/60 focus:outline-none lg:min-h-0"
        />

        <div className="flex flex-wrap gap-1.5">
          {EXAMPLES.map((ex) => (
            <button
              key={ex.label}
              type="button"
              onClick={() => {
                setText(ex.text);
                setSymbol(ex.symbol);
              }}
              className="border border-line px-2 py-1 font-mono text-[10px] uppercase tracking-[0.1em] text-muted transition-colors hover:border-accent/50 hover:text-accent"
            >
              {ex.label}
            </button>
          ))}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label htmlFor="symbol">Symbol</Label>
            <Input
              id="symbol"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              placeholder="NIFTY50"
              maxLength={32}
            />
          </div>
          <div>
            <Label htmlFor="timeframe">Timeframe</Label>
            <Select
              id="timeframe"
              value={timeframe}
              onChange={(e) => setTimeframe(e.target.value as Timeframe)}
            >
              <option value="1d">1d</option>
              <option value="1h">1h</option>
              <option value="15m">15m</option>
            </Select>
          </div>
        </div>

        <Button onClick={() => void submit()} disabled={loading} className="w-full">
          {loading ? (
            <>
              Parsing <Dots />
            </>
          ) : (
            "Parse strategy →"
          )}
        </Button>
        <p className="font-mono text-[10px] leading-relaxed text-muted">
          Indian symbols resolve to NSE (RELIANCE → RELIANCE.NS). NIFTY50, BANKNIFTY and SENSEX map to their
          indices. ⌘/Ctrl + Enter to parse.
        </p>
      </div>
    </Panel>
  );
}
