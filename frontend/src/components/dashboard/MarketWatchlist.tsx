"use client";
import { useMarketStore } from "@/store/useMarketStore";
import { cn } from "@/utils/cn";

const TOP_MARKETS = [
  "KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL",
  "KRW-ADA", "KRW-DOGE", "KRW-AVAX", "KRW-DOT",
];

export default function MarketWatchlist() {
  const tickers = useMarketStore((s) => s.tickers);
  const selectedMarket = useMarketStore((s) => s.selectedMarket);
  const setSelectedMarket = useMarketStore((s) => s.setSelectedMarket);

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-2 border-b border-gray-800 text-xs font-semibold text-gray-400">
        마켓 현황
      </div>
      <div className="overflow-y-auto flex-1">
        {TOP_MARKETS.map((market) => {
          const ticker = tickers[market];
          const isSelected = selectedMarket === market;
          const isRise = ticker?.change === "RISE";
          const isFall = ticker?.change === "FALL";

          return (
            <button
              key={market}
              onClick={() => setSelectedMarket(market)}
              className={cn(
                "w-full flex items-center justify-between px-3 py-2 text-xs hover:bg-gray-800/50 transition-colors border-b border-gray-800/30",
                isSelected && "bg-emerald-500/5 border-l-2 border-l-emerald-500"
              )}
            >
              <span className="font-mono text-gray-300">
                {market.replace("KRW-", "")}
              </span>
              {ticker ? (
                <div className="text-right">
                  <div className="font-mono">
                    {ticker.tradePrice.toLocaleString("ko-KR")}
                  </div>
                  <div
                    className={cn(
                      "text-xs",
                      isRise && "text-emerald-400",
                      isFall && "text-red-400",
                      !isRise && !isFall && "text-gray-500"
                    )}
                  >
                    {isRise ? "+" : isFall ? "-" : ""}
                    {(Math.abs(ticker.changeRate) * 100).toFixed(2)}%
                  </div>
                </div>
              ) : (
                <span className="text-gray-600">--</span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
