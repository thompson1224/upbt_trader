"use client";
import { useMarketStore } from "@/store/useMarketStore";
import { cn } from "@/utils/cn";
import { Brain, TrendingUp, TrendingDown, Minus } from "lucide-react";

export default function AISignalPanel() {
  const signals = useMarketStore((s) => s.signals);

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-3 border-b border-gray-800 flex items-center gap-2">
        <Brain className="w-4 h-4 text-emerald-400" />
        <span className="text-sm font-semibold">AI 신호</span>
      </div>

      <div className="flex-1 overflow-y-auto">
        {signals.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-gray-600 text-sm">
            신호 대기 중...
          </div>
        ) : (
          signals.map((signal) => (
            <SignalCard key={signal.id} signal={signal} />
          ))
        )}
      </div>
    </div>
  );
}

function SignalCard({ signal }: { signal: import("@/types/market").SignalData }) {
  const scorePercent = ((signal.finalScore + 1) / 2) * 100;

  return (
    <div className="px-4 py-3 border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
      {/* 헤더 */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          {signal.side === "buy" ? (
            <TrendingUp className="w-4 h-4 text-emerald-400" />
          ) : signal.side === "sell" ? (
            <TrendingDown className="w-4 h-4 text-red-400" />
          ) : (
            <Minus className="w-4 h-4 text-gray-500" />
          )}
          <span className="text-xs font-mono font-bold">
            {signal.market || `Coin#${signal.coinId}`}
          </span>
        </div>
        <span
          className={cn(
            "text-xs px-1.5 py-0.5 rounded font-medium",
            signal.side === "buy" && "bg-emerald-500/20 text-emerald-400",
            signal.side === "sell" && "bg-red-500/20 text-red-400",
            signal.side === "hold" && "bg-gray-700 text-gray-400"
          )}
        >
          {signal.side.toUpperCase()}
        </span>
      </div>

      {/* AI 점수 게이지 */}
      <div className="mb-1.5">
        <div className="flex justify-between text-xs text-gray-500 mb-1">
          <span>AI 점수</span>
          <span className="font-mono">
            {(signal.finalScore * 100).toFixed(0)}
          </span>
        </div>
        <div className="h-1.5 bg-gray-800 rounded-full overflow-hidden">
          <div
            className={cn(
              "h-full rounded-full transition-all duration-500",
              signal.finalScore > 0 ? "bg-emerald-500" : "bg-red-500"
            )}
            style={{ width: `${scorePercent}%` }}
          />
        </div>
      </div>

      {/* 세부 점수 */}
      <div className="grid grid-cols-2 gap-x-4 text-xs text-gray-500">
        <div>
          <span>TA: </span>
          <span className="font-mono text-gray-300">
            {(signal.taScore * 100).toFixed(0)}
          </span>
        </div>
        {signal.sentimentScore !== null && (
          <div>
            <span>감성: </span>
            <span className="font-mono text-gray-300">
              {(signal.sentimentScore * 100).toFixed(0)}
            </span>
          </div>
        )}
        <div>
          <span>신뢰도: </span>
          <span className="font-mono text-gray-300">
            {(signal.confidence * 100).toFixed(0)}%
          </span>
        </div>
      </div>

      <div className="mt-1 text-xs text-gray-600">
        {new Date(signal.ts).toLocaleTimeString("ko-KR")}
      </div>
    </div>
  );
}
