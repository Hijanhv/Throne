import axios, { AxiosError } from "axios";

import type {
  BacktestBody,
  BacktestResult,
  DeployBody,
  ExecutorStatus,
  Health,
  ParseBody,
  ParsedStrategy,
} from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

const http = axios.create({ baseURL: API_URL, timeout: 90_000 });

interface ValidationIssue {
  loc: (string | number)[];
  msg: string;
}

interface ErrorBody {
  detail?: string | ValidationIssue[];
}

/** Turns axios and FastAPI errors into one readable line. */
export function errorMessage(err: unknown): string {
  if (err instanceof AxiosError) {
    if (!err.response) return `Cannot reach the Throne API at ${API_URL}`;
    const detail = (err.response.data as ErrorBody | undefined)?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail[0]) {
      const issue = detail[0];
      return `${issue.loc.slice(1).join(".")}: ${issue.msg}`;
    }
    return `Request failed (${err.response.status})`;
  }
  return err instanceof Error ? err.message : "Unknown error";
}

export const api = {
  health: async (): Promise<Health> => (await http.get<Health>("/health", { timeout: 5000 })).data,
  parse: async (body: ParseBody): Promise<ParsedStrategy> =>
    (await http.post<ParsedStrategy>("/parse", body)).data,
  backtest: async (body: BacktestBody): Promise<BacktestResult> =>
    (await http.post<BacktestResult>("/backtest", body)).data,
  deploy: async (body: DeployBody): Promise<{ status: string; strategy_id: string; mode: string }> =>
    (await http.post<{ status: string; strategy_id: string; mode: string }>("/deploy", body)).data,
  status: async (id: string): Promise<ExecutorStatus> =>
    (await http.get<ExecutorStatus>(`/status/${id}`)).data,
  stop: async (id: string): Promise<ExecutorStatus> => (await http.post<ExecutorStatus>(`/stop/${id}`)).data,
  remove: async (id: string): Promise<void> => {
    await http.delete(`/strategy/${id}`);
  },
};
