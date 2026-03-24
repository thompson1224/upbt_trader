import axios from "axios";
import { QueryClient } from "@tanstack/react-query";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const apiClient = axios.create({
  baseURL: `${API_BASE}/api/v1`,
  timeout: 10_000,
  headers: { "Content-Type": "application/json" },
});

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      retry: 2,
    },
  },
});

// API 함수들
export const api = {
  markets: {
    list: () =>
      apiClient.get("/markets").then((r) => r.data),
    candles: (market: string, interval = "1m", limit = 200) =>
      apiClient
        .get(`/markets/${market}/candles`, { params: { interval, limit } })
        .then((r) => r.data),
  },
  signals: {
    list: (params?: { market?: string; side?: string; limit?: number }) =>
      apiClient.get("/signals", { params }).then((r) => r.data),
  },
  orders: {
    list: (state?: string) =>
      apiClient.get("/orders", { params: { state } }).then((r) => r.data),
  },
  portfolio: {
    positions: () => apiClient.get("/positions").then((r) => r.data),
    equityCurve: () =>
      apiClient.get("/portfolio/equity-curve").then((r) => r.data),
  },
  backtests: {
    create: (payload: object) =>
      apiClient.post("/backtests/runs", payload).then((r) => r.data),
    get: (runId: number) =>
      apiClient.get(`/backtests/runs/${runId}`).then((r) => r.data),
    metrics: (runId: number) =>
      apiClient.get(`/backtests/runs/${runId}/metrics`).then((r) => r.data),
  },
  settings: {
    setUpbitKeys: (accessKey: string, secretKey: string) =>
      apiClient.post("/secrets/upbit-keys", {
        access_key: accessKey,
        secret_key: secretKey,
      }),
    setGeminiKey: (apiKey: string) =>
      apiClient.post("/secrets/gemini-key", { api_key: apiKey }),
    setAutoTrade: (enabled: boolean) =>
      apiClient.patch("/settings/auto-trade", { enabled }).then((r) => r.data),
    getAutoTrade: () =>
      apiClient.get("/settings/auto-trade").then((r) => r.data as { enabled: boolean }),
  },
};
