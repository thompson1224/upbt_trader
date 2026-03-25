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
            const latestSignal = pos.latestSignal;
            const tpGapPct =
              pos.takeProfit && livePrice > 0
                ? ((pos.takeProfit - livePrice) / livePrice) * 100
                : null;
            const slGapPct =
              pos.stopLoss && livePrice > 0
                ? ((livePrice - pos.stopLoss) / livePrice) * 100
                : null;
            const pendingReason =
              pos.takeProfit && livePrice >= pos.takeProfit
                ? "익절 가격 도달 구간입니다. 체결 동기화 여부를 확인하세요."
                : pos.stopLoss && livePrice <= pos.stopLoss
                  ? "손절 가격 도달 구간입니다. 체결 동기화 여부를 확인하세요."
                  : pos.sellWaitReason;

            return (
              <div
                key={pos.id}
                className="px-3 py-2 border-b border-gray-800/30 text-xs"
              >
                <div className="flex justify-between mb-0.5">
                  <span className="font-mono text-gray-300 flex items-center gap-2">
                    <span>{pos.market}</span>
                    <span
                      className={cn(
                        "rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide",
                        pos.source === "strategy"
                          ? "bg-emerald-950 text-emerald-300"
                          : "bg-amber-950 text-amber-300"
                      )}
                    >
                      {pos.source === "strategy" ? "strategy" : "external"}
                    </span>
                  </span>
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
                {latestSignal && (
                  <div className="mt-0.5 text-gray-500">
                    최근 신호:
                    <span
                      className={cn(
                        "ml-1 rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide",
                        latestSignal.side === "buy" && "bg-emerald-950 text-emerald-300",
                        latestSignal.side === "sell" && "bg-red-950 text-red-300",
                        latestSignal.side === "hold" && "bg-slate-800 text-slate-300"
                      )}
                    >
                      {latestSignal.side}
                    </span>
                    <span className="ml-2 text-gray-600">
                      {new Date(latestSignal.ts).toLocaleTimeString("ko-KR")} · {latestSignal.status}
                    </span>
                  </div>
                )}
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
                {(slGapPct != null || tpGapPct != null) && (
                  <div className="mt-0.5 text-gray-600">
                    {slGapPct != null && (
                      <span className="mr-2">
                        {slGapPct <= 0 ? "SL 도달" : `SL까지 -${slGapPct.toFixed(2)}%`}
                      </span>
                    )}
                    {tpGapPct != null && (
                      <span>
                        {tpGapPct <= 0 ? "TP 도달" : `TP까지 +${tpGapPct.toFixed(2)}%`}
                      </span>
                    )}
                  </div>
                )}
                <div className="mt-1 text-[11px] text-gray-500">
                  매도 대기 사유: {pendingReason}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
