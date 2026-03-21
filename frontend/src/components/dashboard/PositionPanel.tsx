"use client";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/services/api";
import { cn } from "@/utils/cn";
import type { Position } from "@/types/market";

export default function PositionPanel() {
  const { data: positions = [] } = useQuery<Position[]>({
    queryKey: ["positions"],
    queryFn: api.portfolio.positions,
    refetchInterval: 5_000,
  });

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-2 border-b border-gray-800 text-xs font-semibold text-gray-400">
        보유 포지션
      </div>
      <div className="overflow-y-auto flex-1">
        {positions.length === 0 ? (
          <div className="flex items-center justify-center h-20 text-xs text-gray-600">
            보유 포지션 없음
          </div>
        ) : (
          positions.map((pos) => (
            <div
              key={pos.id}
              className="px-3 py-2 border-b border-gray-800/30 text-xs"
            >
              <div className="flex justify-between mb-0.5">
                <span className="font-mono text-gray-300">{pos.market}</span>
                <span
                  className={cn(
                    "font-mono font-bold",
                    pos.unrealizedPnl >= 0 ? "text-emerald-400" : "text-red-400"
                  )}
                >
                  {pos.unrealizedPnl >= 0 ? "+" : ""}
                  {pos.unrealizedPnl.toLocaleString("ko-KR")}
                </span>
              </div>
              <div className="text-gray-600">
                수량: {pos.qty.toFixed(6)} | 평균: {pos.avgEntryPrice.toLocaleString("ko-KR")}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
