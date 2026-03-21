import TradingViewChart from "@/components/charts/TradingViewChart";
import AISignalPanel from "@/components/dashboard/AISignalPanel";
import MarketWatchlist from "@/components/dashboard/MarketWatchlist";
import PositionPanel from "@/components/dashboard/PositionPanel";

export default function DashboardPage() {
  return (
    <div className="h-full grid grid-cols-[1fr_300px] grid-rows-[1fr_200px] gap-3">
      {/* 메인 차트 */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
        <TradingViewChart />
      </div>

      {/* AI 신호 패널 */}
      <div className="row-span-2 bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
        <AISignalPanel />
      </div>

      {/* 하단: 마켓 목록 + 포지션 */}
      <div className="grid grid-cols-2 gap-3">
        <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
          <MarketWatchlist />
        </div>
        <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
          <PositionPanel />
        </div>
      </div>
    </div>
  );
}
