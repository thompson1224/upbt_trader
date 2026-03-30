"use client";
import { useEffect, useRef, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { useMarketStore } from "@/store/useMarketStore";
import { api } from "@/services/api";
import type { CandleData } from "@/types/market";

/** 현재 분봉 OHLC 상태 (실시간 업데이트 시 고/저가 추적) */
interface LiveCandle {
  time: number; // Unix seconds, 분 단위 정규화
  open: number;
  high: number;
  low: number;
}

type IChartApi = import("lightweight-charts").IChartApi;
type ISeriesApi = import("lightweight-charts").ISeriesApi<"Candlestick">;

const TIMEFRAMES = ["1m", "5m", "15m", "1h"];

export default function TradingViewChart() {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi | null>(null);
  const liveCandleRef = useRef<LiveCandle | null>(null);
  const selectedMarket = useMarketStore((s) => s.selectedMarket);
  // useShallow: 선택된 마켓 ticker만 구독 → 다른 마켓 tick 시 리렌더링 없음
  const ticker = useMarketStore(
    useShallow((s) => s.tickers[s.selectedMarket] ?? null)
  );
  const [timeframe, setTimeframe] = useState("1m");
  const [isChartReady, setIsChartReady] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  // 차트 초기화
  useEffect(() => {
    if (!chartContainerRef.current) return;

    let chart: IChartApi;
    let isMounted = true;
    let removeResizeObserver: (() => void) | undefined;

    import("lightweight-charts")
      .then(({ createChart, CandlestickSeries, ColorType }) => {
        if (!chartContainerRef.current || !isMounted) return;

        chart = createChart(chartContainerRef.current, {
          layout: {
            background: { type: ColorType.Solid, color: "#111827" },
            textColor: "#9ca3af",
          },
          grid: {
            vertLines: { color: "#1f2937" },
            horzLines: { color: "#1f2937" },
          },
          crosshair: { mode: 1 },
          rightPriceScale: { borderColor: "#374151" },
          timeScale: {
            borderColor: "#374151",
            timeVisible: true,
          },
          width: chartContainerRef.current.clientWidth,
          height: chartContainerRef.current.clientHeight,
        });

        const candleSeries = chart.addSeries(CandlestickSeries, {
          upColor: "#10b981",
          downColor: "#ef4444",
          borderVisible: false,
          wickUpColor: "#10b981",
          wickDownColor: "#ef4444",
        });

        chartRef.current = chart;
        candleSeriesRef.current = candleSeries;
        setIsChartReady(true);
        setLoadError(null);

        // 리사이즈 대응
        const resizeObserver = new ResizeObserver(() => {
          if (chartContainerRef.current) {
            chart.applyOptions({
              width: chartContainerRef.current.clientWidth,
              height: chartContainerRef.current.clientHeight,
            });
          }
        });
        resizeObserver.observe(chartContainerRef.current);
        removeResizeObserver = () => resizeObserver.disconnect();
      })
      .catch((error) => {
        console.error(error);
        if (!isMounted) return;
        setLoadError("차트 엔진을 불러오지 못했습니다.");
      });

    return () => {
      isMounted = false;
      removeResizeObserver?.();
      chart?.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      setIsChartReady(false);
    };
  }, []);

  // 캔들 데이터 로드 (마켓/타임프레임 변경 시 liveCandleRef 초기화)
  useEffect(() => {
    if (!isChartReady || !candleSeriesRef.current) return;

    liveCandleRef.current = null; // 새 데이터 로드 전 live 상태 초기화
    setIsLoading(true);
    setLoadError(null);
    api.markets
      .candles(selectedMarket, timeframe, 200)
      .then((candles: CandleData[]) => {
        if (!candleSeriesRef.current) return;
        const data = candles.map((c) => ({
          time: (new Date(c.ts).getTime() / 1000) as import("lightweight-charts").Time,
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
        }));
        candleSeriesRef.current.setData(data);
        // 마지막 캔들을 live 초기값으로 설정
        const last = candles[candles.length - 1];
        if (last) {
          const lastTime = Math.floor(new Date(last.ts).getTime() / 1000 / 60) * 60;
          liveCandleRef.current = { time: lastTime, open: last.open, high: last.high, low: last.low };
        }
      })
      .catch((error) => {
        console.error(error);
        setLoadError("캔들 데이터를 불러오지 못했습니다.");
      })
      .finally(() => setIsLoading(false));
  }, [isChartReady, selectedMarket, timeframe]);

  // 실시간 가격 업데이트 — High/Low 유지하여 캔들 꼬리 정확하게 표현
  useEffect(() => {
    if (!ticker || !candleSeriesRef.current) return;

    const candleTime = Math.floor(ticker.timestamp / 1000 / 60) * 60;
    const price = ticker.tradePrice;
    const prev = liveCandleRef.current;

    if (!prev || prev.time !== candleTime) {
      // 새 분봉 시작: open = 이전 close (연속성), high/low 초기화
      liveCandleRef.current = { time: candleTime, open: price, high: price, low: price };
    } else {
      // 같은 분봉: high/low 갱신, open 유지
      liveCandleRef.current = {
        ...prev,
        high: Math.max(prev.high, price),
        low: Math.min(prev.low, price),
      };
    }

    candleSeriesRef.current.update({
      time: candleTime as import("lightweight-charts").Time,
      open: liveCandleRef.current.open,
      high: liveCandleRef.current.high,
      low: liveCandleRef.current.low,
      close: price,
    });
  }, [ticker]);

  return (
    <div className="flex flex-col h-full">
      {/* 차트 헤더 */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-800">
        <span className="font-mono font-semibold text-sm">{selectedMarket}</span>
        <div className="flex gap-1">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              onClick={() => setTimeframe(tf)}
              className={`px-2 py-0.5 rounded text-xs font-medium transition-colors ${
                timeframe === tf
                  ? "bg-emerald-500/20 text-emerald-400"
                  : "text-gray-500 hover:text-gray-300"
              }`}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>

      {/* 차트 영역 */}
      <div className="relative flex-1">
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-gray-900/50 z-10">
            <div className="text-sm text-gray-500">로딩 중...</div>
          </div>
        )}
        {loadError && (
          <div className="absolute inset-0 flex items-center justify-center bg-gray-900/80 z-20 px-4 text-center">
            <div className="text-sm text-red-300">{loadError}</div>
          </div>
        )}
        <div ref={chartContainerRef} className="w-full h-full" />
      </div>
    </div>
  );
}
