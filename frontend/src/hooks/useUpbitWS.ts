"use client";
import { useEffect, useRef, useCallback } from "react";
import { useMarketStore } from "@/store/useMarketStore";
import { TickerData, SignalData } from "@/types/market";

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
  const { updateTicker, setConnected } = useMarketStore();

  const connect = useCallback(() => {
    const params = codes.join(",");
    const url = `${WS_BASE}/ws/market?codes=${encodeURIComponent(params)}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      // 30초마다 ping
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
      // 재연결 (3초 후)
      reconnectTimer.current = setTimeout(connect, 3_000);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [codes, updateTicker, setConnected]);

  useEffect(() => {
    connect();
    return () => {
      reconnectTimer.current && clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);
}

export function useSignalWS() {
  const wsRef = useRef<WebSocket | null>(null);
  const { addSignal } = useMarketStore();

  useEffect(() => {
    const ws = new WebSocket(`${WS_BASE}/ws/signals`);
    wsRef.current = ws;

    ws.onmessage = (e) => {
      try {
        const signal: SignalData = JSON.parse(e.data);
        addSignal(signal);
      } catch {
        // 무시
      }
    };

    return () => ws.close();
  }, [addSignal]);
}
