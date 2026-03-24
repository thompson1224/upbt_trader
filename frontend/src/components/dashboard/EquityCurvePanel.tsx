"use client";
import { useEffect, useRef } from "react";
import { useTradeStore } from "@/store/useTradeStore";
import { cn } from "@/utils/cn";

type IChartApi = import("lightweight-charts").IChartApi;
type ISeriesApi = import("lightweight-charts").ISeriesApi<"Area">;

export default function EquityCurvePanel() {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const areaSeriesRef = useRef<ISeriesApi | null>(null);
  const equityCurve = useTradeStore((s) => s.equityCurve);
  const totalEquity = useTradeStore((s) => s.totalEquity);
  const availableKrw = useTradeStore((s) => s.availableKrw);
  const dailyPnl = useTradeStore((s) => s.dailyPnl);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    let removeResizeObserver: (() => void) | undefined;

    import("lightweight-charts").then(({ createChart, AreaSeries, ColorType }) => {
      if (!chartContainerRef.current) return;

      const chart = createChart(chartContainerRef.current, {
        layout: {
          background: { type: ColorType.Solid, color: "#111827" },
          textColor: "#6b7280",
        },
        grid: {
          vertLines: { color: "#17202e" },
          horzLines: { color: "#17202e" },
        },
        rightPriceScale: {
          borderColor: "#243041",
          scaleMargins: { top: 0.2, bottom: 0.18 },
        },
        timeScale: {
          borderColor: "#243041",
          timeVisible: true,
        },
        crosshair: { mode: 0 },
        width: chartContainerRef.current.clientWidth,
        height: chartContainerRef.current.clientHeight,
      });

      const series = chart.addSeries(AreaSeries, {
        lineColor: "#22c55e",
        topColor: "rgba(34, 197, 94, 0.28)",
        bottomColor: "rgba(34, 197, 94, 0.02)",
        lineWidth: 2,
      });

      chartRef.current = chart;
      areaSeriesRef.current = series;

      const resizeObserver = new ResizeObserver(() => {
        if (!chartContainerRef.current) return;
        chart.applyOptions({
          width: chartContainerRef.current.clientWidth,
          height: chartContainerRef.current.clientHeight,
        });
      });
      resizeObserver.observe(chartContainerRef.current);
      removeResizeObserver = () => resizeObserver.disconnect();
    });

    return () => {
      removeResizeObserver?.();
      chartRef.current?.remove();
      chartRef.current = null;
      areaSeriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!areaSeriesRef.current) return;
    const data = equityCurve.map((point) => ({
      time: (new Date(point.ts).getTime() / 1000) as import("lightweight-charts").Time,
      value: point.equity,
    }));
    areaSeriesRef.current.setData(data);
    chartRef.current?.timeScale().fitContent();
  }, [equityCurve]);

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-2 border-b border-gray-800 flex items-center justify-between">
        <div>
          <div className="text-[11px] font-semibold tracking-[0.18em] text-gray-500 uppercase">
            Portfolio Curve
          </div>
          <div className="mt-1 font-mono text-lg font-bold text-gray-100">
            {totalEquity > 0 ? `${Math.round(totalEquity).toLocaleString("ko-KR")}원` : "대기 중"}
          </div>
        </div>
        <div className="text-right text-[11px] text-gray-500">
          <div>현금 {Math.round(availableKrw).toLocaleString("ko-KR")}원</div>
          <div
            className={cn(
              "font-mono mt-1",
              dailyPnl >= 0 ? "text-emerald-400" : "text-red-400"
            )}
          >
            {dailyPnl >= 0 ? "+" : ""}
            {Math.round(dailyPnl).toLocaleString("ko-KR")}원
          </div>
        </div>
      </div>
      <div className="relative flex-1 px-2 py-2">
        {equityCurve.length === 0 ? (
          <div className="flex h-full items-center justify-center text-xs text-gray-600">
            자산 곡선 데이터 대기 중
          </div>
        ) : (
          <div ref={chartContainerRef} className="h-full w-full" />
        )}
      </div>
    </div>
  );
}
