"use client";

import { useCallback, useEffect, useState } from "react";

import { BacktestPanel } from "@/components/BacktestPanel";
import { LivePanel } from "@/components/LivePanel";
import { RuleViewer } from "@/components/RuleViewer";
import { StrategyInput } from "@/components/StrategyInput";
import { TopBar } from "@/components/TopBar";
import { Panel } from "@/components/ui/panel";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import type { BacktestResult, Health, ParsedStrategy } from "@/lib/types";

type Tab = "backtest" | "live";

export default function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  const [reachable, setReachable] = useState(true);
  const [strategy, setStrategy] = useState<ParsedStrategy | null>(null);
  const [backtest, setBacktest] = useState<BacktestResult | null>(null);
  const [backtesting, setBacktesting] = useState(false);
  const [tab, setTab] = useState<Tab>("backtest");
  const [liveId, setLiveId] = useState<string | null>(null);

  const checkHealth = useCallback(async () => {
    try {
      setHealth(await api.health());
      setReachable(true);
    } catch {
      setReachable(false);
    }
  }, []);

  useEffect(() => {
    void checkHealth();
    const t = setInterval(() => void checkHealth(), 15_000);
    return () => clearInterval(t);
  }, [checkHealth]);

  return (
    <div className="flex min-h-screen flex-col lg:h-screen">
      <TopBar health={health} reachable={reachable} />
      <main className="grid flex-1 grid-cols-1 lg:min-h-0 lg:grid-cols-[minmax(300px,1fr)_minmax(300px,1fr)_minmax(420px,1.5fr)]">
        <StrategyInput
          onParsed={(s) => {
            setStrategy(s);
            setBacktest(null);
            setTab("backtest");
          }}
        />
        <RuleViewer
          strategy={strategy}
          onBacktest={(r) => {
            setBacktest(r);
            setTab("backtest");
          }}
          onBacktestStart={() => setBacktesting(true)}
          onBacktestEnd={() => setBacktesting(false)}
        />
        <Panel className="min-h-[640px] lg:min-h-0">
          <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)} className="flex min-h-0 flex-1 flex-col">
            <TabsList>
              <TabsTrigger value="backtest">Backtest</TabsTrigger>
              <TabsTrigger value="live">
                Live
                {liveId && (
                  <span className="ml-2 inline-block h-1.5 w-1.5 animate-blink bg-accent align-middle" />
                )}
              </TabsTrigger>
            </TabsList>
            <TabsContent
              value="backtest"
              className="flex min-h-0 flex-1 flex-col data-[state=inactive]:hidden"
            >
              <BacktestPanel result={backtest} loading={backtesting} />
            </TabsContent>
            <TabsContent value="live" className="flex min-h-0 flex-1 flex-col data-[state=inactive]:hidden">
              <LivePanel strategy={strategy} health={health} liveId={liveId} setLiveId={setLiveId} />
            </TabsContent>
          </Tabs>
        </Panel>
      </main>
    </div>
  );
}
