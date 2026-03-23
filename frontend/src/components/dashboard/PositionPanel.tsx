"use client";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/services/api";
import { useMarketStore } from "@/store/useMarketStore";
import { cn } from "@/utils/cn";
import type { Position } from "@/types/market";

export default function PositionPanel() {
  const { data: positions = [] } = useQuery<Position[]>({
    queryKey: ["positions"],
    queryFn: api.portfolio.positions,
    refetchInterval: 30_000,
  });
  const tickers = useMarketStore((s) => s.tickers);

  const totalUnrealized = positions.reduce((acc, pos) => {
    const livePrice = tickers[pos.market]?.tradePrice ?? pos.avgEntryPrice;
    return acc + (livePrice - pos.avgEntryPrice) * pos.qty;
  }, 0);

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-2 border-b border-gray-800 flex items-center justify-between">
        <span className="text-xs font-semibold text-gray-400">보유 포지션</span>
        {positions.length > 0 && (
          <span
            className={cn(
              "text-xs font-mono font-bold",
              totalUnrealized >= 0 ? "text-emerald-400" : "text-red-400"
            )}
          >
            {totalUnrealized >= 0 ? "+" : ""}
            {Math.round(totalUnrealized).toLocaleString("ko-KR")}원
          </span>
        )}
      </div>
      <div className="overflow-y-auto flex-1">
        {positions.length === 0 ? (
          <div className="flex items-center justify-center h-20 text-xs text-gray-600">
            보유 포지션 없음
          </div>
        ) : (
          positions.map((pos) => {
            const livePrice = tickers[pos.market]?.tradePrice ?? pos.avgEntryPrice;
            const liveUnrealized = (livePrice - pos.avgEntryPrice) * pos.qty;
            const pnlPct =
              pos.avgEntryPrice > 0
                ? ((livePrice - pos.avgEntryPrice) / pos.avgEntryPrice) * 100
                : 0;

            return (
              <div
                key={pos.id}
                className="px-3 py-2 border-b border-gray-800/30 text-xs"
              >
                <div className="flex justify-between mb-0.5">
                  <span className="font-mono text-gray-300">{pos.market}</span>
                  <span
                    className={cn(
                      "font-mono font-bold",
                      liveUnrealized >= 0 ? "text-emerald-400" : "text-red-400"
                    )}
                  >
                    {liveUnrealized >= 0 ? "+" : ""}
                    {Math.round(liveUnrealized).toLocaleString("ko-KR")}
                    <span className="ml-1 text-gray-500">
                      ({pnlPct >= 0 ? "+" : ""}{pnlPct.toFixed(2)}%)
                    </span>
                  </span>
                </div>
                <div className="text-gray-600">
                  수량: {pos.qty.toFixed(6)} | 평균: {pos.avgEntryPrice.toLocaleString("ko-KR")} | 현재: {livePrice.toLocaleString("ko-KR")}
                </div>
                {(pos.stopLoss || pos.takeProfit) && (
                  <div className="text-gray-700 mt-0.5">
                    {pos.stopLoss && (
                      <span className="mr-2">SL: {pos.stopLoss.toLocaleString("ko-KR")}</span>
                    )}
                    {pos.takeProfit && (
                      <span>TP: {pos.takeProfit.toLocaleString("ko-KR")}</span>
                    )}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
