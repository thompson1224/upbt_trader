"use client";
import { useMarketStore } from "@/store/useMarketStore";
import { useTradeStore } from "@/store/useTradeStore";
import { Bell, Power } from "lucide-react";
import { cn } from "@/utils/cn";

export default function GlobalHeader() {
  const tickers = useMarketStore((s) => s.tickers);
  const { totalEquity, dailyPnl, isAutoTrading, toggleAutoTrading } =
    useTradeStore();

  const btc = tickers["KRW-BTC"];
  const eth = tickers["KRW-ETH"];

  return (
    <header className="h-14 bg-gray-900 border-b border-gray-800 flex items-center px-4 gap-4 shrink-0">
      {/* 주요 지수 */}
      <div className="flex items-center gap-6 text-sm">
        {btc && (
          <PriceTag
            label="BTC"
            price={btc.tradePrice}
            changeRate={btc.changeRate}
            change={btc.change}
          />
        )}
        {eth && (
          <PriceTag
            label="ETH"
            price={eth.tradePrice}
            changeRate={eth.changeRate}
            change={eth.change}
          />
        )}
      </div>

      <div className="flex-1" />

      {/* 자산 요약 */}
      {totalEquity > 0 && (
        <div className="hidden md:flex items-center gap-4 text-sm">
          <div>
            <span className="text-gray-500 mr-1">총 자산</span>
            <span className="font-mono font-bold">
              {totalEquity.toLocaleString("ko-KR")}
            </span>
            <span className="text-gray-500 ml-0.5">원</span>
          </div>
          <div>
            <span className="text-gray-500 mr-1">일 손익</span>
            <span
              className={cn(
                "font-mono font-bold",
                dailyPnl >= 0 ? "text-emerald-400" : "text-red-400"
              )}
            >
              {dailyPnl >= 0 ? "+" : ""}
              {dailyPnl.toLocaleString("ko-KR")}
            </span>
          </div>
        </div>
      )}

      {/* 자동매매 토글 */}
      <button
        onClick={toggleAutoTrading}
        className={cn(
          "flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
          isAutoTrading
            ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
            : "bg-gray-800 text-gray-400 border border-gray-700"
        )}
      >
        <Power className="w-3.5 h-3.5" />
        {isAutoTrading ? "자동매매 ON" : "자동매매 OFF"}
      </button>

      <button className="text-gray-500 hover:text-gray-300 transition-colors">
        <Bell className="w-5 h-5" />
      </button>
    </header>
  );
}

function PriceTag({
  label,
  price,
  changeRate,
  change,
}: {
  label: string;
  price: number;
  changeRate: number;
  change: string;
}) {
  const isRise = change === "RISE";
  const isFall = change === "FALL";

  return (
    <div className="flex items-center gap-1.5">
      <span className="text-gray-400">{label}</span>
      <span className="font-mono font-semibold">
        {price.toLocaleString("ko-KR")}
      </span>
      <span
        className={cn(
          "text-xs",
          isRise && "text-emerald-400",
          isFall && "text-red-400",
          !isRise && !isFall && "text-gray-500"
        )}
      >
        {isRise ? "+" : isFall ? "-" : ""}
        {(Math.abs(changeRate) * 100).toFixed(2)}%
      </span>
    </div>
  );
}
