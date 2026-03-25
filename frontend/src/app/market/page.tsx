"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/services/api";
import { useMarketStore } from "@/store/useMarketStore";
import { Search, TrendingUp, TrendingDown } from "lucide-react";
import Sidebar from "@/components/layout/Sidebar";
import GlobalHeader from "@/components/layout/GlobalHeader";
import { cn } from "@/utils/cn";
import type { MarketInfo } from "@/types/market";

export default function MarketPage() {
  const [search, setSearch] = useState("");
  const tickers = useMarketStore((s) => s.tickers);
  const setSelectedMarket = useMarketStore((s) => s.setSelectedMarket);

  const { data: markets = [] } = useQuery<MarketInfo[]>({
    queryKey: ["markets"],
    queryFn: api.markets.list,
    staleTime: 60_000,
  });

  const filtered = markets.filter((m) =>
    m.market.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="h-screen flex overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <GlobalHeader />
        <main className="flex-1 overflow-auto p-6">
          <div className="flex items-center gap-4 mb-6">
            <h1 className="text-lg font-bold">KRW 마켓 전체</h1>
            <div className="relative">
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="코인 검색..."
                className="pl-9 pr-4 py-1.5 bg-gray-900 border border-gray-700 rounded-lg text-sm focus:outline-none focus:border-emerald-500"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {filtered.map((m) => {
              const ticker = tickers[m.market];
              const isRise = ticker?.change === "RISE";
              const isFall = ticker?.change === "FALL";

              return (
                <button
                  key={m.market}
                  onClick={() => setSelectedMarket(m.market)}
                  className="bg-gray-900 rounded-xl border border-gray-800 p-4 hover:border-emerald-500/50 transition-colors text-left"
                >
                  <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-bold text-sm">
                      {m.market.replace("KRW-", "")}
                    </span>
                    {m.excluded && (
                        <span className="rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide bg-red-950 text-red-300">
                          excluded
                        </span>
                      )}
                    </div>
                    {ticker && (
                      isRise ? (
                        <TrendingUp className="w-4 h-4 text-emerald-400" />
                      ) : isFall ? (
                        <TrendingDown className="w-4 h-4 text-red-400" />
                      ) : null
                    )}
                  </div>
                  {m.excluded && m.excluded_reason && (
                    <div className="mb-2 text-[11px] text-red-300 line-clamp-2">
                      {m.excluded_reason}
                    </div>
                  )}
                  {ticker ? (
                    <>
                      <div className="font-mono text-sm">
                        {ticker.tradePrice.toLocaleString("ko-KR")}
                      </div>
                      <div
                        className={cn(
                          "text-xs mt-0.5",
                          isRise && "text-emerald-400",
                          isFall && "text-red-400",
                          !isRise && !isFall && "text-gray-500"
                        )}
                      >
                        {isRise ? "+" : isFall ? "-" : ""}
                        {(Math.abs(ticker.changeRate) * 100).toFixed(2)}%
                      </div>
                    </>
                  ) : (
                    <div className="text-xs text-gray-600">데이터 로딩...</div>
                  )}
                </button>
              );
            })}
          </div>
        </main>
      </div>
    </div>
  );
}
