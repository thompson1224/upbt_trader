"use client";
import { useEffect, useRef } from "react";
import { useMarketStore } from "@/store/useMarketStore";
import { useTradeStore } from "@/store/useTradeStore";
import { useNotificationStore, NotificationType } from "@/store/useNotificationStore";
import { EquityCurvePoint, TickerData, SignalData } from "@/types/market";
import { api, mapSignalData } from "@/services/api";

/** 지수 백오프 재연결 지연 (1s → 2s → 4s ... 최대 30s, ±20% jitter) */
function getReconnectDelay(attempt: number): number {
  const delay = Math.min(1_000 * Math.pow(2, attempt), 30_000);
  return Math.round(delay * (0.8 + Math.random() * 0.4));
}

const DEFAULT_GATEWAY_PORT = process.env.NEXT_PUBLIC_GATEWAY_PORT || "8001";
const FALLBACK_WS_BASE = process.env.NEXT_PUBLIC_WS_URL || `ws://localhost:${DEFAULT_GATEWAY_PORT}`;

function isLoopbackHost(hostname: string) {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
}

function getWebSocketBaseUrl() {
  if (typeof window !== "undefined" && !process.env.NEXT_PUBLIC_WS_URL) {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}`;
  }

  const url = new URL(FALLBACK_WS_BASE);

  if (typeof window !== "undefined") {
    const browserHost = window.location.hostname;
    const browserProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    url.protocol = browserProtocol;
    if (browserHost && (isLoopbackHost(url.hostname) || !process.env.NEXT_PUBLIC_WS_URL)) {
      url.hostname = browserHost;
    }
  }

  return url.toString().replace(/\/$/, "");
}

function mapTickerPayload(data: Record<string, unknown>): TickerData {
  return {
    code: String(data.cd || data.code || ""),
    tradePrice: Number(data.tp || data.tradePrice || 0),
    change: (data.c || data.change || "EVEN") as TickerData["change"],
    changeRate: Number(data.cr || data.changeRate || 0),
    changePrice: Number(data.cp || data.changePrice || 0),
    accTradeVolume24h: Number(data.atv24h || data.accTradeVolume24h || 0),
    accTradePrice24h: Number(data.atp24h || data.accTradePrice24h || 0),
    high52WeekPrice: Number(data.h52wp || 0),
    low52WeekPrice: Number(data.l52wp || 0),
    timestamp: Number(data.tms || Date.now()),
  };
}

export function useUpbitMarketWS(codes: string[]) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryCount = useRef(0);
  const updateTicker = useMarketStore((s) => s.updateTicker);
  const setConnected = useMarketStore((s) => s.setConnected);

  useEffect(() => {
    const wsBaseUrl = getWebSocketBaseUrl();
    let isActive = true;

    function connect() {
      if (!isActive) return;
      const params = codes.join(",");
      const url = `${wsBaseUrl}/ws/market?codes=${encodeURIComponent(params)}`;
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!isActive) return;
        retryCount.current = 0; // 연결 성공 시 재시도 카운터 초기화
        setConnected(true);
        const pingInterval = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send("ping");
        }, 30_000);
        ws.addEventListener("close", () => clearInterval(pingInterval));
      };

      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          if (data === "pong") return;
          updateTicker(mapTickerPayload(data));
        } catch {
          // 무시
        }
      };

      ws.onclose = () => {
        if (!isActive) return;
        setConnected(false);
        const delay = getReconnectDelay(retryCount.current);
        retryCount.current += 1;
        reconnectTimer.current = setTimeout(connect, delay);
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();
    return () => {
      isActive = false;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [codes, setConnected, updateTicker]);
}

export function useSignalWS() {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const addSignal = useMarketStore((s) => s.addSignal);
  const setSignals = useMarketStore((s) => s.setSignals);

  useEffect(() => {
    const wsBaseUrl = getWebSocketBaseUrl();
    let isActive = true;

    // 초기 신호 로드: 최근 신호 50개 (hold 포함)
    const loadInitialSignals = async () => {
      try {
        const data = await api.signals.list({ limit: 50 });
        const combined: SignalData[] = [...data].sort(
          (a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime()
        );
        if (combined.length > 0) setSignals(combined.slice(0, 100));
      } catch {
        // 조용히 실패 — WebSocket으로 폴백
      }
    };
    loadInitialSignals();

    let retryCount = 0;
    const connect = () => {
      if (!isActive) return;
      const ws = new WebSocket(`${wsBaseUrl}/ws/signals`);
      wsRef.current = ws;

      ws.onopen = () => { retryCount = 0; };

      ws.onmessage = (e) => {
        try {
          const signal = mapSignalData(JSON.parse(e.data));
          addSignal(signal);
        } catch {
          // 무시
        }
      };

      ws.onclose = () => {
        if (!isActive) return;
        reconnectTimer.current = setTimeout(connect, getReconnectDelay(retryCount++));
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    connect();

    return () => {
      isActive = false;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [addSignal, setSignals]);
}

const TRADE_EVENT_LABELS: Record<string, { type: NotificationType; title: string }> = {
  order_placed: { type: "order_placed", title: "주문 접수" },
  order_filled: { type: "order_filled", title: "주문 체결" },
  sl_triggered: { type: "sl_triggered", title: "손절 실행" },
  tp_triggered: { type: "tp_triggered", title: "익절 실행" },
  risk_rejected: { type: "risk_rejected", title: "리스크 거절" },
};

export function useTradeEventWS() {
  const push = useNotificationStore((s) => s.push);

  useEffect(() => {
    const wsBaseUrl = getWebSocketBaseUrl();
    let isActive = true;
    let ws: WebSocket;
    let reconnectTimer: ReturnType<typeof setTimeout>;

    let retryCount = 0;
    const connect = () => {
      if (!isActive) return;
      ws = new WebSocket(`${wsBaseUrl}/ws/trade-events`);

      ws.onopen = () => { retryCount = 0; };

      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          const label = TRADE_EVENT_LABELS[data.type];
          if (!label) return;

          let message = data.market ?? "";
          if (data.side) message += ` ${data.side.toUpperCase()}`;
          if (data.price) message += ` @${Number(data.price).toLocaleString("ko-KR")}`;
          if (data.reason) message += ` — ${data.reason}`;

          push({ type: label.type, title: label.title, message });
        } catch {
          // 무시
        }
      };

      ws.onclose = () => {
        if (!isActive) return;
        reconnectTimer = setTimeout(connect, getReconnectDelay(retryCount++));
      };
      ws.onerror = () => ws.close();
    };

    connect();
    return () => {
      isActive = false;
      clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [push]);
}

export function usePortfolioWS() {
  const setEquityCurve = useTradeStore((s) => s.setEquityCurve);
  const addEquityPoint = useTradeStore((s) => s.addEquityPoint);
  const setEquity = useTradeStore((s) => s.setEquity);
  const setDailyPnl = useTradeStore((s) => s.setDailyPnl);

  useEffect(() => {
    const wsBaseUrl = getWebSocketBaseUrl();
    let isActive = true;
    let ws: WebSocket;
    let reconnectTimer: ReturnType<typeof setTimeout>;

    const applySnapshot = (point: EquityCurvePoint) => {
      addEquityPoint(point);
      setEquity(point.equity ?? 0, point.availableKrw ?? 0);
      setDailyPnl(point.dailyPnl ?? 0);
    };

    const loadInitialCurve = async () => {
      try {
        const response = await api.portfolio.equityCurve();
        const points: EquityCurvePoint[] = response.data ?? [];
        setEquityCurve(points);
        if (response.latest) applySnapshot(response.latest);
      } catch {
        // 조용히 실패, websocket으로 계속 시도
      }
    };

    let retryCount = 0;
    const connect = () => {
      if (!isActive) return;
      ws = new WebSocket(`${wsBaseUrl}/ws/portfolio`);

      ws.onmessage = (e) => {
        try {
          const raw = JSON.parse(e.data) as unknown;
          if (raw === "pong") return;
          const data = raw as EquityCurvePoint & { type?: string };
          if (data.type === "portfolio_snapshot") {
            applySnapshot(data);
          }
        } catch {
          // 무시
        }
      };

      ws.onopen = () => {
        retryCount = 0;
        const pingInterval = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send("ping");
        }, 30_000);
        ws.addEventListener("close", () => clearInterval(pingInterval));
      };

      ws.onclose = () => {
        if (!isActive) return;
        reconnectTimer = setTimeout(connect, getReconnectDelay(retryCount++));
      };
      ws.onerror = () => ws.close();
    };

    loadInitialCurve();
    connect();

    return () => {
      isActive = false;
      clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [addEquityPoint, setDailyPnl, setEquity, setEquityCurve]);
}
