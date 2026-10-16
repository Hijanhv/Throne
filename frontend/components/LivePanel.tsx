"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Label, Select } from "@/components/ui/input";
import { Dots, Empty } from "@/components/ui/panel";
import { Switch } from "@/components/ui/switch";
import { api, errorMessage } from "@/lib/api";
import type { ExchangeSegment, ExecutorStatus, Health, ParsedStrategy } from "@/lib/types";
import { cn, formatNum, signed } from "@/lib/utils";

const POLL_MS = 5000;

interface Props {
  strategy: ParsedStrategy | null;
  health: Health | null;
  liveId: string | null;
  setLiveId: (id: string | null) => void;
}

export function LivePanel({ strategy, health, liveId, setLiveId }: Props) {
  const [capital, setCapital] = useState("100000");
  const [live, setLive] = useState(false);
  const [securityId, setSecurityId] = useState("");
  const [segment, setSegment] = useState<ExchangeSegment>("NSE_EQ");
  const [confirmed, setConfirmed] = useState(false);
  const [deploying, setDeploying] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [status, setStatus] = useState<ExecutorStatus | null>(null);

  const refresh = useCallback(async () => {
    if (!liveId) return;
    try {
      setStatus(await api.status(liveId));
    } catch (err) {
      toast.error(errorMessage(err), { id: "status-error" });
    }
  }, [liveId]);

  useEffect(() => {
    if (!liveId) {
      setStatus(null);
      return;
    }
    void refresh();
    const t = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(t);
  }, [liveId, refresh]);

  async function deploy() {
    if (!strategy) return;
    const cap = Number(capital);
    if (!Number.isFinite(cap) || cap <= 0) {
      toast.error("Capital must be a positive number");
      return;
    }
    if (live && !securityId.trim()) {
      toast.error("Live mode needs the Dhan security ID");
      return;
    }
    if (live && !confirmed) {
      toast.error("Confirm that live mode places real orders");
      return;
    }
    setDeploying(true);
    try {
      await api.deploy({
        strategy_id: strategy.id,
        mode: live ? "live" : "paper",
        capital: cap,
        ...(live ? { security_id: securityId.trim(), exchange_segment: segment, confirm_live: true } : {}),
      });
      setLiveId(strategy.id);
      toast.success(`Deployed in ${live ? "LIVE" : "paper"} mode`);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setDeploying(false);
    }
  }

  async function stop() {
    if (!liveId) return;
    setStopping(true);
    try {
      setStatus(await api.stop(liveId));
      toast.success("Executor stopped");
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setStopping(false);
    }
  }

  const running = status?.status === "running";
  const showingOther = liveId !== null && strategy !== null && liveId !== strategy.id;

  if (!strategy && !liveId)
    return (
      <Empty>Parse a strategy to deploy it. Paper mode simulates fills in memory with no broker calls.</Empty>
    );

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      {(!running || showingOther) && strategy && (
        <div className="space-y-4 border-b border-line p-4">
          <div>
            <Label htmlFor="capital">Deploy with ₹</Label>
            <Input
              id="capital"
              inputMode="numeric"
              value={capital}
              onChange={(e) => setCapital(e.target.value.replace(/[^\d.]/g, ""))}
            />
          </div>

          <div className="flex items-center justify-between border border-line bg-bg px-3 py-2.5">
            <span className="flex items-center gap-3 font-mono text-xs font-bold tracking-[0.18em]">
              <span className={live ? "text-muted" : "text-accent"}>PAPER</span>
              <Switch checked={live} onCheckedChange={setLive} aria-label="Toggle live mode" />
              <span className={live ? "text-warn" : "text-muted"}>LIVE</span>
            </span>
            {live && !health?.dhan_configured && <Badge tone="danger">Dhan keys missing</Badge>}
          </div>

          {live && (
            <div className="space-y-3 border border-warn/30 bg-warn/5 p-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label htmlFor="security">Dhan security ID</Label>
                  <Input
                    id="security"
                    value={securityId}
                    onChange={(e) => setSecurityId(e.target.value.replace(/\D/g, ""))}
                    placeholder="e.g. 2885"
                  />
                </div>
                <div>
                  <Label htmlFor="segment">Segment</Label>
                  <Select
                    id="segment"
                    value={segment}
                    onChange={(e) => setSegment(e.target.value as ExchangeSegment)}
                  >
                    <option value="NSE_EQ">NSE_EQ</option>
                    <option value="BSE_EQ">BSE_EQ</option>
                    <option value="NSE_FNO">NSE_FNO</option>
                  </Select>
                </div>
              </div>
              <label className="flex cursor-pointer items-start gap-2 font-mono text-[11px] leading-relaxed text-warn">
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(e) => setConfirmed(e.target.checked)}
                  className="mt-0.5 accent-[#ff9f1a]"
                />
                I understand this sends real market orders to my Dhan account.
              </label>
            </div>
          )}

          <Button
            variant={live ? "live" : "primary"}
            className="w-full"
            disabled={deploying || strategy.rules.length === 0}
            onClick={() => void deploy()}
          >
            {deploying ? (
              <>
                Deploying <Dots />
              </>
            ) : (
              `Deploy ${live ? "live" : "paper"} →`
            )}
          </Button>
        </div>
      )}

      {status && (
        <div className="space-y-4 p-4">
          <div className="border border-line bg-bg">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2.5">
              <span className="font-mono text-[11px] text-muted">{status.strategy_id.slice(0, 8)}</span>
              <span className="flex items-center gap-2">
                <Badge tone={status.mode === "live" ? "warn" : "muted"}>{status.mode}</Badge>
                <Badge tone={running ? "accent" : status.status === "error" ? "danger" : "muted"}>
                  {running && <span className="h-1.5 w-1.5 animate-blink bg-accent" />}
                  {status.status}
                </Badge>
              </span>
            </div>
            <div className="grid grid-cols-2 gap-px bg-line">
              <div className="bg-bg p-3">
                <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted">
                  Current P&amp;L
                </div>
                <div
                  className={cn(
                    "tabular mt-1 font-mono text-xl font-bold",
                    status.current_pnl > 0
                      ? "text-accent"
                      : status.current_pnl < 0
                        ? "text-danger"
                        : "text-fg",
                  )}
                >
                  {signed(status.current_pnl)}
                </div>
              </div>
              <div className="bg-bg p-3">
                <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted">
                  Trades today
                </div>
                <div className="tabular mt-1 font-mono text-xl font-bold">{status.trades_today}</div>
              </div>
            </div>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 border-t border-line px-3 py-3 font-mono text-[11px]">
              <dt className="text-muted">Position</dt>
              <dd className="tabular text-right">
                {status.position_qty
                  ? `${status.position_qty} @ ${formatNum(status.entry_price ?? 0)}`
                  : "Flat"}
              </dd>
              <dt className="text-muted">Last price</dt>
              <dd className="tabular text-right">{status.last_price ? formatNum(status.last_price) : "…"}</dd>
              <dt className="text-muted">Realized</dt>
              <dd className="tabular text-right">{signed(status.realized_pnl)}</dd>
              <dt className="text-muted">Unrealized</dt>
              <dd className="tabular text-right">{signed(status.unrealized_pnl)}</dd>
              <dt className="text-muted">Last tick</dt>
              <dd className="tabular text-right">
                {status.last_tick ? new Date(status.last_tick).toLocaleTimeString("en-IN") : "waiting"}
              </dd>
            </dl>
            {status.last_signal && (
              <div className="border-t border-line px-3 py-2 font-mono text-[11px] text-fg/80">
                {status.last_signal}
              </div>
            )}
            {status.last_error && (
              <div className="border-t border-line px-3 py-2 font-mono text-[11px] text-danger">
                {status.last_error}
              </div>
            )}
          </div>

          {running ? (
            <Button variant="danger" className="w-full" disabled={stopping} onClick={() => void stop()}>
              {stopping ? (
                <>
                  Stopping <Dots />
                </>
              ) : (
                "Stop executor"
              )}
            </Button>
          ) : (
            <Button variant="ghost" size="sm" className="w-full" onClick={() => setLiveId(null)}>
              Clear status
            </Button>
          )}

          <div>
            <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.18em] text-muted">Fills</div>
            {status.fills.length === 0 ? (
              <div className="font-mono text-[11px] text-muted">
                No fills yet. The executor checks for new candles every 60 seconds.
              </div>
            ) : (
              <ul className="space-y-1">
                {status.fills.map((f, i) => (
                  <li
                    key={`${f.time}-${i}`}
                    className="flex items-center justify-between gap-2 border border-line bg-bg px-3 py-2 font-mono text-[11px]"
                  >
                    <span className={f.side === "BUY" ? "text-accent" : "text-danger"}>
                      {f.side} {f.quantity}
                    </span>
                    <span className="tabular text-fg/80">@ {formatNum(f.price)}</span>
                    <span className="truncate text-muted">{f.reason}</span>
                    <span className="tabular text-muted">
                      {new Date(f.time).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
