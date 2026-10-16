// Mirrors backend/models.py

export type Indicator = "RSI" | "MACD" | "EMA" | "SMA" | "BB" | "VOLUME" | "PRICE";
export type Operator = "CROSSES_ABOVE" | "CROSSES_BELOW" | "GREATER_THAN" | "LESS_THAN";
export type Action = "BUY" | "SELL";
export type Timeframe = "1d" | "1h" | "15m";
export type Mode = "paper" | "live";
export type Period = "1mo" | "3mo" | "6mo" | "1y" | "2y" | "5y";
export type ExchangeSegment = "NSE_EQ" | "BSE_EQ" | "NSE_FNO";

export interface StrategyRule {
  indicator: Indicator;
  period: number | null;
  operator: Operator;
  value: number | null;
  compare_to: Indicator | null;
  compare_period: number | null;
  action: Action;
  stop_loss_pct: number | null;
  take_profit_pct: number | null;
}

export interface ParsedStrategy {
  id: string;
  name: string;
  text: string;
  rules: StrategyRule[];
  entry_logic: "all" | "any";
  exit_logic: "all" | "any";
  stop_loss_pct: number | null;
  take_profit_pct: number | null;
  symbol: string;
  timeframe: Timeframe;
  parser: "ai" | "regex";
  confidence: number;
  warnings: string[];
  created_at: string;
}

export interface Trade {
  entry_date: string;
  exit_date: string;
  entry_price: number;
  exit_price: number;
  pnl: number;
  pnl_pct: number;
  exit_reason: "signal" | "stop_loss" | "take_profit" | "end_of_data";
  action: "LONG";
}

export interface EquityPoint {
  date: string;
  time: number;
  value: number;
}

export interface BacktestResult {
  strategy_id: string;
  symbol: string;
  ticker: string;
  period: string;
  interval: Timeframe;
  initial_capital: number;
  trades: Trade[];
  total_pnl: number;
  total_return_pct: number;
  benchmark_return_pct: number;
  sharpe_ratio: number;
  max_drawdown: number;
  win_rate: number;
  total_trades: number;
  bars: number;
  equity_curve: EquityPoint[];
  warnings: string[];
}

export interface Fill {
  time: string;
  side: Action;
  price: number;
  quantity: number;
  reason: string;
  order_id: string | null;
}

export interface ExecutorStatus {
  strategy_id: string;
  mode: Mode;
  status: "running" | "stopped" | "error";
  capital: number;
  current_pnl: number;
  realized_pnl: number;
  unrealized_pnl: number;
  position_qty: number;
  entry_price: number | null;
  last_price: number | null;
  trades_today: number;
  last_signal: string | null;
  last_tick: string | null;
  last_error: string | null;
  fills: Fill[];
}

export interface Health {
  status: string;
  ollama: boolean;
  ollama_model: string;
  dhan_configured: boolean;
  dhan_sandbox: boolean;
  strategies: number;
  running: number;
}

export interface ParseBody {
  text: string;
  symbol: string;
  timeframe: Timeframe;
}

export interface BacktestBody {
  strategy_id: string;
  period: Period;
  initial_capital: number;
  fee_bps?: number;
}

export interface DeployBody {
  strategy_id: string;
  mode: Mode;
  capital: number;
  security_id?: string;
  exchange_segment?: ExchangeSegment;
  confirm_live?: boolean;
  poll_seconds?: number;
}
