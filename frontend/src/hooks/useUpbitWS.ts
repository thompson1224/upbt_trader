"use client";
import { useEffect, useRef } from "react";
import { useMarketStore } from "@/store/useMarketStore";
import { useTradeStore } from "@/store/useTradeStore";
import { useNotificationStore, NotificationType } from "@/store/useNotificationStore";
import { EquityCurvePoint, TickerData, SignalData } from "@/types/market";
import { api, mapSignalData } from "@/services/api";

const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";

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
  const updateTicker = useMarketStore((s) => s.updateTicker);
  const setConnected = useMarketStore((s) => s.setConnected);

  useEffect(() => {
    function connect() {
      const params = codes.join(",");
      const url = `${WS_BASE}/ws/market?codes=${encodeURIComponent(params)}`;
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
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
        setConnected(false);
        reconnectTimer.current = setTimeout(connect, 3_000);
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [codes, setConnected, updateTicker]);
}

export function useSignalWS() {
  const wsRef = useRef<WebSocket | null>(null);
  const addSignal = useMarketStore((s) => s.addSignal);
  const setSignals = useMarketStore((s) => s.setSignals);

  useEffect(() => {
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

    const ws = new WebSocket(`${WS_BASE}/ws/signals`);
    wsRef.current = ws;

    ws.onmessage = (e) => {
      try {
        const signal = mapSignalData(JSON.parse(e.data));
        addSignal(signal);
      } catch {
        // 무시
      }
    };

    return () => ws.close();
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
    let ws: WebSocket;
    let reconnectTimer: ReturnType<typeof setTimeout>;

    const connect = () => {
      ws = new WebSocket(`${WS_BASE}/ws/trade-events`);

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
        reconnectTimer = setTimeout(connect, 3_000);
      };
      ws.onerror = () => ws.close();
    };

    connect();
    return () => {
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

    const connect = () => {
      ws = new WebSocket(`${WS_BASE}/ws/portfolio`);

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
        const pingInterval = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send("ping");
        }, 30_000);
        ws.addEventListener("close", () => clearInterval(pingInterval));
      };

      ws.onclose = () => {
        reconnectTimer = setTimeout(connect, 3_000);
      };
      ws.onerror = () => ws.close();
    };

    loadInitialCurve();
    connect();

    return () => {
      clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, [addEquityPoint, setDailyPnl, setEquity, setEquityCurve]);
}
