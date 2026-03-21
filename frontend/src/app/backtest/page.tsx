"use client";
import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { api } from "@/services/api";
import { BarChart2, Play } from "lucide-react";
import Sidebar from "@/components/layout/Sidebar";
import GlobalHeader from "@/components/layout/GlobalHeader";
import type { BacktestMetrics } from "@/types/market";

export default function BacktestPage() {
  const [market, setMarket] = useState("KRW-BTC");
  const [testFrom, setTestFrom] = useState("2024-01-01");
  const [testTo, setTestTo] = useState("2024-12-31");
  const [runId, setRunId] = useState<number | null>(null);

  const { mutate: runBacktest, isPending } = useMutation({
    mutationFn: () =>
      api.backtests.create({
        market,
        train_from: `${testFrom}T00:00:00`,
        train_to: `${testFrom}T00:00:00`,
        test_from: `${testFrom}T00:00:00`,
        test_to: `${testTo}T23:59:59`,
      }),
    onSuccess: (data) => setRunId(data.run_id),
  });

  const { data: metrics } = useQuery<BacktestMetrics>({
    queryKey: ["backtest-metrics", runId],
    queryFn: () => api.backtests.metrics(runId!),
    enabled: !!runId,
    refetchInterval: (query) =>
      query.state.data ? false : 3000,
  });

  return (
    <div className="h-screen flex overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <GlobalHeader />
        <main className="flex-1 overflow-auto p-6">
          <h1 className="text-lg font-bold mb-6 flex items-center gap-2">
            <BarChart2 className="w-5 h-5 text-emerald-400" />
            백테스팅
          </h1>

          {/* 설정 패널 */}
          <div className="bg-gray-900 rounded-xl border border-gray-800 p-6 mb-6 max-w-lg">
            <div className="grid grid-cols-2 gap-4 mb-4">
              <div>
                <label className="text-xs text-gray-500 mb-1 block">마켓</label>
                <input
                  value={market}
                  onChange={(e) => setMarket(e.target.value.toUpperCase())}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:border-emerald-500"
                  placeholder="KRW-BTC"
                />
              </div>
              <div />
              <div>
                <label className="text-xs text-gray-500 mb-1 block">시작일</label>
                <input
                  type="date"
                  value={testFrom}
                  onChange={(e) => setTestFrom(e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-emerald-500"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500 mb-1 block">종료일</label>
                <input
                  type="date"
                  value={testTo}
                  onChange={(e) => setTestTo(e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-emerald-500"
                />
              </div>
            </div>
            <button
              onClick={() => runBacktest()}
              disabled={isPending}
              className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
            >
              <Play className="w-4 h-4" />
              {isPending ? "실행 중..." : "백테스트 실행"}
            </button>
          </div>

          {/* 결과 */}
          {metrics && (
            <div className="grid grid-cols-3 gap-4 max-w-2xl">
              <MetricCard label="CAGR" value={`${(metrics.cagr * 100).toFixed(2)}%`} />
              <MetricCard label="Sharpe" value={metrics.sharpe.toFixed(2)} />
              <MetricCard
                label="최대 낙폭"
                value={`${(metrics.maxDrawdown * 100).toFixed(2)}%`}
                negative
              />
              <MetricCard label="승률" value={`${(metrics.winRate * 100).toFixed(1)}%`} />
              <MetricCard label="손익비" value={metrics.profitFactor.toFixed(2)} />
              <MetricCard label="총 거래" value={`${metrics.totalTrades}건`} />
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

function MetricCard({
  label,
  value,
  negative,
}: {
  label: string;
  value: string;
  negative?: boolean;
}) {
  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-4">
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      <div
        className={`text-xl font-mono font-bold ${negative ? "text-red-400" : "text-emerald-400"}`}
      >
        {value}
      </div>
    </div>
  );
}
