import axios from "axios";
import { QueryClient } from "@tanstack/react-query";
import type { AuditEvent, PerformanceResponse, Position } from "@/types/market";

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

type RawSignalData = {
  id: number;
  strategy_id: string;
  coin_id: number;
  market: string;
  timeframe: string;
  ts: string;
  ta_score: number;
  sentiment_score: number | null;
  final_score: number;
  confidence: number;
  side: "buy" | "sell" | "hold";
  status: string;
  suggested_stop_loss: number | null;
  suggested_take_profit: number | null;
};

export function mapSignalData(signal: RawSignalData) {
  return {
    id: signal.id,
    strategyId: signal.strategy_id,
    coinId: signal.coin_id,
    market: signal.market,
    timeframe: signal.timeframe,
    ts: signal.ts,
    taScore: signal.ta_score,
    sentimentScore: signal.sentiment_score,
    finalScore: signal.final_score,
    confidence: signal.confidence,
    side: signal.side,
    status: signal.status,
    suggestedStopLoss: signal.suggested_stop_loss,
    suggestedTakeProfit: signal.suggested_take_profit,
  };
}

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
      apiClient
        .get("/signals", { params })
        .then((r) => (r.data as RawSignalData[]).map(mapSignalData)),
  },
  orders: {
    list: (state?: string) =>
      apiClient.get("/orders", { params: { state } }).then((r) => r.data),
  },
  audit: {
    list: (params?: { eventType?: string; source?: string; limit?: number }) =>
      apiClient
        .get("/audit-events", {
          params: {
            event_type: params?.eventType,
            source: params?.source,
            limit: params?.limit,
          },
        })
        .then((r) => r.data as AuditEvent[]),
  },
  portfolio: {
    positions: () =>
      apiClient.get("/positions").then((r) =>
        (r.data as Array<{
          id: number;
          market: string;
          qty: number;
          avg_entry_price: number;
          unrealized_pnl: number;
          realized_pnl: number;
          source: "strategy" | "external";
          stop_loss: number | null;
          take_profit: number | null;
          auto_trade_managed: boolean;
          latest_signal: {
            id: number;
            strategy_id: string;
            ts: string;
            side: "buy" | "sell" | "hold";
            status: string;
            final_score: number;
            confidence: number;
            rejection_reason: string | null;
          } | null;
          sell_wait_reason_code: string;
          sell_wait_reason: string;
        }>).map((pos): Position => ({
          id: pos.id,
          market: pos.market,
          qty: pos.qty,
          avgEntryPrice: pos.avg_entry_price,
          unrealizedPnl: pos.unrealized_pnl,
          realizedPnl: pos.realized_pnl,
          source: pos.source,
          stopLoss: pos.stop_loss,
          takeProfit: pos.take_profit,
          autoTradeManaged: pos.auto_trade_managed,
          latestSignal: pos.latest_signal
            ? {
                id: pos.latest_signal.id,
                strategyId: pos.latest_signal.strategy_id,
                ts: pos.latest_signal.ts,
                side: pos.latest_signal.side,
                status: pos.latest_signal.status,
                finalScore: pos.latest_signal.final_score,
                confidence: pos.latest_signal.confidence,
                rejectionReason: pos.latest_signal.rejection_reason,
              }
            : null,
          sellWaitReasonCode: pos.sell_wait_reason_code,
          sellWaitReason: pos.sell_wait_reason,
        }))
      ),
    equityCurve: (params?: { limit?: number; days?: number }) =>
      apiClient.get("/portfolio/equity-curve", {
        params: {
          limit: params?.limit,
          days: params?.days,
        },
      }).then((r) => r.data),
    performance: (params?: { limit?: number; days?: number; market?: string }) =>
      apiClient
        .get("/portfolio/performance", {
          params: {
            limit: params?.limit ?? 100,
            days: params?.days,
            market: params?.market,
          },
        })
        .then((r) => r.data as PerformanceResponse),
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
    setGroqKey: (apiKey: string) =>
      apiClient.post("/secrets/groq-key", { api_key: apiKey }),
    setAutoTrade: (enabled: boolean) =>
      apiClient.patch("/settings/auto-trade", { enabled }).then((r) => r.data),
    getAutoTrade: () =>
      apiClient.get("/settings/auto-trade").then((r) => r.data as { enabled: boolean }),
    setExternalPositionStopLoss: (enabled: boolean) =>
      apiClient.patch("/settings/external-position-stop-loss", { enabled }).then((r) => r.data),
    getExternalPositionStopLoss: () =>
      apiClient.get("/settings/external-position-stop-loss").then((r) => r.data as { enabled: boolean }),
    setMinBuyFinalScore: (value: number) =>
      apiClient.patch("/settings/min-buy-final-score", { value }).then((r) => r.data as { value: number }),
    getMinBuyFinalScore: () =>
      apiClient.get("/settings/min-buy-final-score").then((r) => r.data as { value: number }),
    resetLossStreak: () =>
      apiClient.post("/settings/risk/reset-loss-streak").then((r) => r.data as {
        lossStreak: number;
        streakDate: string;
      }),
  },
};
