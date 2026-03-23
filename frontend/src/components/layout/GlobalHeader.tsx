"use client";
import { useEffect } from "react";
import { useMarketStore } from "@/store/useMarketStore";
import { useTradeStore } from "@/store/useTradeStore";
import { Bell } from "lucide-react";
import { cn } from "@/utils/cn";
import { api } from "@/services/api";
import AutoTradeToggle from "./AutoTradeToggle";

export default function GlobalHeader() {
  const tickers = useMarketStore((s) => s.tickers);
  const { totalEquity, dailyPnl, setAutoTrading } = useTradeStore();

  const btc = tickers["KRW-BTC"];
  const eth = tickers["KRW-ETH"];

  useEffect(() => {
    api.settings.getAutoTrade().then(({ enabled }) => setAutoTrading(enabled)).catch(() => {});
  }, [setAutoTrading]);

  return (
    <header className="h-14 bg-gray-900 border-b border-gray-800 flex items-center px-4 gap-4 shrink-0">
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

      <AutoTradeToggle />

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
