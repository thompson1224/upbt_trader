"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, BarChart2, Clock3, GitBranch, Play } from "lucide-react";
import Sidebar from "@/components/layout/Sidebar";
import GlobalHeader from "@/components/layout/GlobalHeader";
import { api } from "@/services/api";
import type {
  BacktestMetrics,
  BacktestRunSummary,
  BacktestTradeRow,
  BacktestWindowRow,
} from "@/types/market";
import { cn } from "@/utils/cn";

function formatDate(value: string | null) {
  if (!value) {
    return "-";
  }
  return new Intl.DateTimeFormat("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatDay(value: string) {
  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(value));
}

function formatShortDay(value: string) {
  return new Intl.DateTimeFormat("ko-KR", {
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(value));
}

function formatCurrency(value: number | null) {
  if (value == null || Number.isNaN(value)) {
    return "-";
  }
  const rounded = Math.round(value);
  return `${rounded >= 0 ? "+" : ""}${rounded.toLocaleString("ko-KR")}원`;
}

function formatCompactCurrency(value: number | null) {
  if (value == null || Number.isNaN(value)) {
    return "-";
  }
  return new Intl.NumberFormat("ko-KR", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(Math.round(value));
}

function formatPct(value: number | null) {
  if (value == null || Number.isNaN(value)) {
    return "-";
  }
  return `${(value * 100).toFixed(2)}%`;
}

function formatPrice(value: number | null) {
  if (value == null || Number.isNaN(value)) {
    return "-";
  }
  return Math.round(value).toLocaleString("ko-KR");
}

function formatMinutes(value: number) {
  if (value < 60) {
    return `${Math.round(value)}분`;
  }
  const hours = Math.floor(value / 60);
  const minutes = Math.round(value % 60);
  return minutes > 0 ? `${hours}시간 ${minutes}분` : `${hours}시간`;
}

function shiftDateString(value: string, deltaDays: number) {
  const date = new Date(`${value}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + deltaDays);
  return date.toISOString().slice(0, 10);
}

function getStatusTone(status: string) {
  if (status === "completed") {
    return "text-emerald-300 border-emerald-900 bg-emerald-950/30";
  }
  if (status === "failed") {
    return "text-red-300 border-red-900 bg-red-950/30";
  }
  if (status === "running") {
    return "text-sky-300 border-sky-900 bg-sky-950/30";
  }
  return "text-amber-300 border-amber-900 bg-amber-950/30";
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
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
      <div className="mb-1 text-xs text-gray-500">{label}</div>
      <div className={cn("text-xl font-mono font-bold", negative ? "text-red-400" : "text-emerald-400")}>
        {value}
      </div>
    </div>
  );
}

type RunSortMode = "latest" | "oldest" | "market" | "status";

function getRunSortTimestamp(run: BacktestRunSummary) {
  return new Date(run.finishedAt ?? run.startedAt ?? run.testTo).getTime();
}

function getStatusRank(status: BacktestRunSummary["status"]) {
  if (status === "running") {
    return 0;
  }
  if (status === "pending") {
    return 1;
  }
  if (status === "completed") {
    return 2;
  }
  if (status === "failed") {
    return 3;
  }
  return 4;
}

function RunList({
  runs,
  totalCount,
  selectedRunId,
  onSelect,
  filterMarket,
  filterStatus,
  filterMode,
  sortMode,
  onFilterMarketChange,
  onFilterStatusChange,
  onFilterModeChange,
  onSortModeChange,
}: {
  runs: BacktestRunSummary[];
  totalCount: number;
  selectedRunId: number | null;
  onSelect: (runId: number) => void;
  filterMarket: string;
  filterStatus: string;
  filterMode: string;
  sortMode: RunSortMode;
  onFilterMarketChange: (value: string) => void;
  onFilterStatusChange: (value: string) => void;
  onFilterModeChange: (value: string) => void;
  onSortModeChange: (value: RunSortMode) => void;
}) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-sm font-semibold text-gray-100">최근 실행</div>
        <div className="text-[11px] text-gray-500">{runs.length} / {totalCount}건</div>
      </div>
      <div className="mb-3 space-y-2">
        <input
          value={filterMarket}
          onChange={(e) => onFilterMarketChange(e.target.value.toUpperCase())}
          placeholder="마켓 필터"
          className="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm font-mono focus:border-emerald-500 focus:outline-none"
        />
        <div className="grid grid-cols-2 gap-2">
          <select
            value={filterStatus}
            onChange={(e) => onFilterStatusChange(e.target.value)}
            className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-200 focus:border-emerald-500 focus:outline-none"
          >
            <option value="all">모든 상태</option>
            <option value="pending">pending</option>
            <option value="running">running</option>
            <option value="completed">completed</option>
            <option value="failed">failed</option>
          </select>
          <select
            value={filterMode}
            onChange={(e) => onFilterModeChange(e.target.value)}
            className="rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-200 focus:border-emerald-500 focus:outline-none"
          >
            <option value="all">모든 모드</option>
            <option value="single">single</option>
            <option value="walk_forward">walk-forward</option>
          </select>
        </div>
        <select
          value={sortMode}
          onChange={(e) => onSortModeChange(e.target.value as RunSortMode)}
          className="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-200 focus:border-emerald-500 focus:outline-none"
        >
          <option value="latest">최신순</option>
          <option value="oldest">오래된순</option>
          <option value="market">마켓순</option>
          <option value="status">상태순</option>
        </select>
      </div>
      <div className="space-y-2">
        {runs.length === 0 ? (
          <div className="text-xs text-gray-600">
            {totalCount === 0 ? "백테스트 실행 이력이 아직 없습니다." : "필터 조건에 맞는 실행 이력이 없습니다."}
          </div>
        ) : (
          runs.map((run) => (
            <button
              key={run.id}
              type="button"
              onClick={() => onSelect(run.id)}
              className={cn(
                "w-full rounded-lg border px-3 py-2 text-left transition",
                selectedRunId === run.id
                  ? "border-emerald-700 bg-emerald-950/20"
                  : "border-gray-800 bg-gray-950/40 hover:border-gray-700"
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <div className="font-mono text-sm text-gray-200">
                  {run.market ?? "unknown"} <span className="text-gray-600">#{run.id}</span>
                </div>
                <span className={cn("rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wide", getStatusTone(run.status))}>
                  {run.status}
                </span>
              </div>
              <div className="mt-1 flex items-center gap-2 text-[11px] text-gray-600">
                <span>{run.mode === "walk_forward" ? "walk-forward" : "single"}</span>
                <span>·</span>
                <span>{formatDay(run.testFrom)} ~ {formatDay(run.testTo)}</span>
              </div>
              {run.errorMessage ? (
                <div className="mt-1 line-clamp-2 text-[11px] text-red-300">{run.errorMessage}</div>
              ) : null}
            </button>
          ))
        )}
      </div>
    </div>
  );
}

function TradesTable({ trades }: { trades: BacktestTradeRow[] }) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900">
      <div className="flex items-center justify-between border-b border-gray-800 px-4 py-3">
        <div className="text-sm font-semibold text-gray-100">체결 상세</div>
        <div className="text-[11px] text-gray-500">{trades.length}건</div>
      </div>
      <div className="max-h-[420px] overflow-auto">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-gray-900 text-gray-500">
            <tr>
              <th className="px-4 py-2 text-left font-medium">시장</th>
              <th className="px-4 py-2 text-left font-medium">진입 / 청산</th>
              <th className="px-4 py-2 text-right font-medium">가격</th>
              <th className="px-4 py-2 text-right font-medium">수익률</th>
              <th className="px-4 py-2 text-right font-medium">손익</th>
              <th className="px-4 py-2 text-right font-medium">보유</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((trade) => (
              <tr key={trade.id} className="border-t border-gray-800 text-gray-300">
                <td className="px-4 py-2 font-mono">{trade.market}</td>
                <td className="px-4 py-2">
                  <div>{formatDate(trade.entryTs)}</div>
                  <div className="text-[11px] text-gray-600">{formatDate(trade.exitTs)}</div>
                </td>
                <td className="px-4 py-2 text-right font-mono">
                  <div>{formatPrice(trade.entryPrice)}</div>
                  <div className="text-[11px] text-gray-600">{formatPrice(trade.exitPrice)}</div>
                </td>
                <td className={cn("px-4 py-2 text-right font-mono", trade.returnPct >= 0 ? "text-emerald-400" : "text-red-400")}>
                  {formatPct(trade.returnPct)}
                </td>
                <td className={cn("px-4 py-2 text-right font-mono font-semibold", trade.pnl >= 0 ? "text-emerald-400" : "text-red-400")}>
                  {formatCurrency(trade.pnl)}
                  <div className="text-[11px] text-gray-600">fee {formatCurrency(trade.fee)}</div>
                </td>
                <td className="px-4 py-2 text-right font-mono text-gray-400">{formatMinutes(trade.holdMinutes)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function WindowsTable({ windows }: { windows: BacktestWindowRow[] }) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900">
      <div className="flex items-center justify-between border-b border-gray-800 px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-gray-100">
          <GitBranch className="h-4 w-4 text-sky-300" />
          <span>실행 구간</span>
        </div>
        <div className="text-[11px] text-gray-500">{windows.length}개</div>
      </div>
      <div className="max-h-[360px] overflow-auto">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-gray-900 text-gray-500">
            <tr>
              <th className="px-4 py-2 text-left font-medium">구간</th>
              <th className="px-4 py-2 text-left font-medium">Train / Test</th>
              <th className="px-4 py-2 text-right font-medium">손익</th>
              <th className="px-4 py-2 text-right font-medium">승률</th>
              <th className="px-4 py-2 text-right font-medium">거래</th>
              <th className="px-4 py-2 text-right font-medium">자산</th>
            </tr>
          </thead>
          <tbody>
            {windows.map((window) => (
              <tr key={window.id} className="border-t border-gray-800 text-gray-300">
                <td className="px-4 py-2 font-mono">W{window.windowSeq}</td>
                <td className="px-4 py-2">
                  <div className="text-gray-400">
                    train {formatDay(window.trainFrom)} ~ {formatDay(window.trainTo)}
                  </div>
                  <div className="text-[11px] text-gray-600">
                    test {formatDay(window.testFrom)} ~ {formatDay(window.testTo)}
                  </div>
                </td>
                <td className={cn("px-4 py-2 text-right font-mono font-semibold", window.netPnl >= 0 ? "text-emerald-400" : "text-red-400")}>
                  {formatCurrency(window.netPnl)}
                </td>
                <td className="px-4 py-2 text-right font-mono">{formatPct(window.winRate)}</td>
                <td className="px-4 py-2 text-right font-mono text-gray-400">{window.totalTrades ?? 0}건</td>
                <td className="px-4 py-2 text-right font-mono text-gray-400">
                  {formatCurrency(window.startEquity)}
                  <div className="text-[11px] text-gray-600">{formatCurrency(window.endEquity)}</div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function buildLinePath(points: Array<{ x: number; y: number }>) {
  if (points.length === 0) {
    return "";
  }
  return points
    .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`)
    .join(" ");
}

type WindowBarMode = "net_pnl" | "win_rate" | "total_trades";

function getWindowBarValue(window: BacktestWindowRow, mode: WindowBarMode) {
  if (mode === "win_rate") {
    return window.winRate ?? 0;
  }
  if (mode === "total_trades") {
    return window.totalTrades ?? 0;
  }
  return window.netPnl;
}

function formatWindowBarValue(value: number, mode: WindowBarMode) {
  if (mode === "win_rate") {
    return formatPct(value);
  }
  if (mode === "total_trades") {
    return `${Math.round(value)}건`;
  }
  return formatCurrency(value);
}

function WindowOverviewChart({ windows }: { windows: BacktestWindowRow[] }) {
  const [barMode, setBarMode] = useState<WindowBarMode>("net_pnl");
  const ordered = [...windows].sort((a, b) => a.windowSeq - b.windowSeq);
  if (ordered.length === 0) {
    return null;
  }

  const width = 720;
  const height = 280;
  const paddingX = 26;
  const topTop = 20;
  const topBottom = 128;
  const dividerY = 156;
  const bottomTop = 178;
  const bottomBottom = 246;
  const chartWidth = width - paddingX * 2;

  const equityValues = ordered.flatMap((window) => [window.startEquity, window.endEquity]);
  let equityMin = Math.min(...equityValues);
  let equityMax = Math.max(...equityValues);
  if (equityMin === equityMax) {
    equityMin -= 1;
    equityMax += 1;
  }

  const chartModes: Array<{ value: WindowBarMode; label: string }> = [
    { value: "net_pnl", label: "순손익" },
    { value: "win_rate", label: "승률" },
    { value: "total_trades", label: "거래수" },
  ];
  const isSignedMode = barMode === "net_pnl";
  const barValues = ordered.map((window) => getWindowBarValue(window, barMode));
  const maxAbsBarValue = Math.max(...barValues.map((value) => Math.abs(value)), 1);
  const maxBarValue = Math.max(...barValues, 1);
  const pnlZeroY = isSignedMode ? (bottomTop + bottomBottom) / 2 : bottomBottom;
  const barTopY = isSignedMode ? bottomTop : bottomTop + 8;

  const points = ordered.map((window, index) => {
    const ratio = ordered.length === 1 ? 0.5 : index / (ordered.length - 1);
    const x = paddingX + chartWidth * ratio;
    const equityRatio = (window.endEquity - equityMin) / (equityMax - equityMin);
    const y = topBottom - equityRatio * (topBottom - topTop);
    return { x, y, window };
  });

  const linePath = buildLinePath(points);
  const areaPath = points.length
    ? `${linePath} L ${points[points.length - 1].x.toFixed(2)} ${topBottom} L ${points[0].x.toFixed(2)} ${topBottom} Z`
    : "";

  const cumulativePnl = ordered.reduce((sum, window) => sum + window.netPnl, 0);
  const endingDelta = ordered[ordered.length - 1].endEquity - ordered[0].startEquity;
  const metricLeader = ordered.reduce(
    (best, window) => (getWindowBarValue(window, barMode) > getWindowBarValue(best, barMode) ? window : best),
    ordered[0]
  );
  const metricLagging = ordered.reduce(
    (worst, window) => (getWindowBarValue(window, barMode) < getWindowBarValue(worst, barMode) ? window : worst),
    ordered[0]
  );
  const averageBarValue = barValues.reduce((sum, value) => sum + value, 0) / Math.max(barValues.length, 1);
  const barAxisTopLabel =
    barMode === "net_pnl"
      ? `손익 +${formatCompactCurrency(maxAbsBarValue)}`
      : barMode === "win_rate"
        ? `승률 ${formatPct(maxBarValue)}`
        : `거래수 ${Math.round(maxBarValue)}건`;
  const barAxisBottomLabel =
    barMode === "net_pnl"
      ? `손익 -${formatCompactCurrency(maxAbsBarValue)}`
      : barMode === "win_rate"
        ? "승률 0.00%"
        : "거래수 0건";
  const metricAverageLabel =
    barMode === "net_pnl"
      ? "평균 구간 손익"
      : barMode === "win_rate"
        ? "평균 구간 승률"
        : "평균 거래 수";
  const metricLeaderLabel =
    barMode === "net_pnl"
      ? "최고 손익 구간"
      : barMode === "win_rate"
        ? "최고 승률 구간"
        : "거래 집중 구간";
  const metricLaggingLabel =
    barMode === "net_pnl"
      ? "최저 손익 구간"
      : barMode === "win_rate"
        ? "최저 승률 구간"
        : "거래 저조 구간";

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-gray-100">워크포워드 구간 추이</div>
          <div className="mt-1 text-xs text-gray-500">
            상단은 윈도우 종료 자산, 하단은 선택한 지표의 구간별 분포입니다.
          </div>
        </div>
        <div className="flex flex-col items-end gap-2">
          <div className="flex items-center gap-1 rounded-lg border border-gray-800 bg-gray-950/40 p-1">
            {chartModes.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => setBarMode(option.value)}
                className={cn(
                  "rounded-md px-2.5 py-1 text-[11px] font-medium transition",
                  barMode === option.value
                    ? "bg-sky-500/20 text-sky-300"
                    : "text-gray-500 hover:text-gray-200"
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
          <div className="text-right text-[11px] text-gray-500">
            <div>{ordered.length}개 window</div>
            <div>{formatDay(ordered[0].testFrom)} ~ {formatDay(ordered[ordered.length - 1].testTo)}</div>
          </div>
        </div>
      </div>

      <svg viewBox={`0 0 ${width} ${height}`} className="h-[280px] w-full overflow-visible">
        <defs>
          <linearGradient id="window-equity-fill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="rgb(34 197 94 / 0.35)" />
            <stop offset="100%" stopColor="rgb(34 197 94 / 0.03)" />
          </linearGradient>
        </defs>

        <line x1={paddingX} y1={topBottom} x2={width - paddingX} y2={topBottom} stroke="rgb(55 65 81)" strokeDasharray="4 4" />
        <line x1={paddingX} y1={dividerY} x2={width - paddingX} y2={dividerY} stroke="rgb(31 41 55)" />
        <line x1={paddingX} y1={pnlZeroY} x2={width - paddingX} y2={pnlZeroY} stroke="rgb(55 65 81)" strokeDasharray="4 4" />

        <text x={paddingX} y={topTop - 4} fill="rgb(107 114 128)" fontSize="10">
          자산 {formatCompactCurrency(equityMax)}
        </text>
        <text x={paddingX} y={topBottom + 12} fill="rgb(107 114 128)" fontSize="10">
          {formatCompactCurrency(equityMin)}
        </text>
        <text x={paddingX} y={bottomTop - 6} fill="rgb(107 114 128)" fontSize="10">
          {barAxisTopLabel}
        </text>
        <text x={paddingX} y={bottomBottom + 14} fill="rgb(107 114 128)" fontSize="10">
          {barAxisBottomLabel}
        </text>

        {areaPath ? <path d={areaPath} fill="url(#window-equity-fill)" /> : null}
        {linePath ? <path d={linePath} fill="none" stroke="rgb(74 222 128)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" /> : null}

        {points.map((point) => (
          <g key={point.window.id}>
            <line x1={point.x} y1={topBottom} x2={point.x} y2={bottomBottom} stroke="rgb(31 41 55)" />
            <circle cx={point.x} cy={point.y} r="4" fill="rgb(17 24 39)" stroke="rgb(74 222 128)" strokeWidth="2" />
            <text x={point.x} y={264} textAnchor="middle" fill="rgb(107 114 128)" fontSize="10">
              W{point.window.windowSeq}
            </text>
            <text x={point.x} y={276} textAnchor="middle" fill="rgb(75 85 99)" fontSize="9">
              {formatShortDay(point.window.testFrom)}
            </text>
          </g>
        ))}

        {ordered.map((window, index) => {
          const ratio = ordered.length === 1 ? 0.5 : index / (ordered.length - 1);
          const x = paddingX + chartWidth * ratio;
          const barWidth = Math.min(34, chartWidth / Math.max(ordered.length, 1) * 0.55);
          const rawValue = getWindowBarValue(window, barMode);
          const scaleMax = isSignedMode ? maxAbsBarValue : maxBarValue;
          const availableHeight = isSignedMode ? (bottomBottom - bottomTop) / 2 - 6 : bottomBottom - barTopY;
          const barHeight = (Math.abs(rawValue) / Math.max(scaleMax, 1)) * availableHeight;
          const y = isSignedMode
            ? rawValue >= 0
              ? pnlZeroY - barHeight
              : pnlZeroY
            : bottomBottom - barHeight;
          const fill =
            barMode === "net_pnl"
              ? rawValue >= 0
                ? "rgb(52 211 153 / 0.85)"
                : "rgb(248 113 113 / 0.85)"
              : barMode === "win_rate"
                ? "rgb(56 189 248 / 0.85)"
                : "rgb(251 191 36 / 0.85)";
          return (
            <g key={window.id}>
              <rect
                x={x - barWidth / 2}
                y={y}
                width={barWidth}
                height={Math.max(barHeight, 2)}
                rx={6}
                fill={fill}
              />
              <text x={x} y={y - 6} textAnchor="middle" fill="rgb(156 163 175)" fontSize="9">
                {formatWindowBarValue(rawValue, barMode)}
              </text>
            </g>
          );
        })}
      </svg>

      <div className="mt-4 grid gap-3 md:grid-cols-4">
        <div className="rounded-lg border border-gray-800 bg-gray-950/40 p-3">
          <div className="text-xs text-gray-500">누적 구간 손익</div>
          <div className={cn("mt-1 font-mono text-sm font-semibold", cumulativePnl >= 0 ? "text-emerald-400" : "text-red-400")}>
            {formatCurrency(cumulativePnl)}
          </div>
        </div>
        <div className="rounded-lg border border-gray-800 bg-gray-950/40 p-3">
          <div className="text-xs text-gray-500">종료 자산 변화</div>
          <div className={cn("mt-1 font-mono text-sm font-semibold", endingDelta >= 0 ? "text-emerald-400" : "text-red-400")}>
            {formatCurrency(endingDelta)}
          </div>
        </div>
        <div className="rounded-lg border border-gray-800 bg-gray-950/40 p-3">
          <div className="text-xs text-gray-500">{metricAverageLabel}</div>
          <div
            className={cn(
              "mt-1 font-mono text-sm font-semibold",
              barMode === "net_pnl"
                ? averageBarValue >= 0
                  ? "text-emerald-400"
                  : "text-red-400"
                : barMode === "win_rate"
                  ? "text-sky-300"
                  : "text-amber-300"
            )}
          >
            {formatWindowBarValue(averageBarValue, barMode)}
          </div>
          <div className="text-[11px] text-gray-600">window당 평균</div>
        </div>
        <div className="rounded-lg border border-gray-800 bg-gray-950/40 p-3">
          <div className="text-xs text-gray-500">{metricLeaderLabel}</div>
          <div className="mt-1 font-mono text-sm text-gray-200">W{metricLeader.windowSeq}</div>
          <div
            className={cn(
              "text-[11px]",
              barMode === "net_pnl"
                ? getWindowBarValue(metricLeader, barMode) >= 0
                  ? "text-emerald-400"
                  : "text-red-400"
                : barMode === "win_rate"
                  ? "text-sky-300"
                  : "text-amber-300"
            )}
          >
            {formatWindowBarValue(getWindowBarValue(metricLeader, barMode), barMode)}
          </div>
        </div>
        <div className="rounded-lg border border-gray-800 bg-gray-950/40 p-3">
          <div className="text-xs text-gray-500">{metricLaggingLabel}</div>
          <div className="mt-1 font-mono text-sm text-gray-200">W{metricLagging.windowSeq}</div>
          <div
            className={cn(
              "text-[11px]",
              barMode === "net_pnl"
                ? getWindowBarValue(metricLagging, barMode) >= 0
                  ? "text-emerald-400"
                  : "text-red-400"
                : barMode === "win_rate"
                  ? "text-sky-300"
                  : "text-amber-300"
            )}
          >
            {formatWindowBarValue(getWindowBarValue(metricLagging, barMode), barMode)}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function BacktestPage() {
  const queryClient = useQueryClient();
  const [market, setMarket] = useState("KRW-BTC");
  const [mode, setMode] = useState<"single" | "walk_forward">("single");
  const [testFrom, setTestFrom] = useState("2024-01-01");
  const [testTo, setTestTo] = useState("2024-12-31");
  const [trainWindowDays, setTrainWindowDays] = useState(30);
  const [testWindowDays, setTestWindowDays] = useState(7);
  const [stepDays, setStepDays] = useState(7);
  const [runId, setRunId] = useState<number | null>(null);
  const [runFilterMarket, setRunFilterMarket] = useState("");
  const [runFilterStatus, setRunFilterStatus] = useState("all");
  const [runFilterMode, setRunFilterMode] = useState("all");
  const [runSortMode, setRunSortMode] = useState<RunSortMode>("latest");

  const { data: runs = [] } = useQuery<BacktestRunSummary[]>({
    queryKey: ["backtest-runs"],
    queryFn: () => api.backtests.list({ limit: 12 }),
    refetchInterval: 5_000,
  });

  const { mutate: runBacktest, isPending, error: runError } = useMutation({
    mutationFn: () =>
      api.backtests.create({
        market,
        mode,
        train_from: `${shiftDateString(testFrom, -trainWindowDays)}T00:00:00`,
        train_to: `${testFrom}T00:00:00`,
        test_from: `${testFrom}T00:00:00`,
        test_to: `${testTo}T23:59:59`,
        test_window_days: testWindowDays,
        step_days: stepDays,
      }),
    onSuccess: async (data) => {
      setRunId(data.run_id);
      await queryClient.invalidateQueries({ queryKey: ["backtest-runs"] });
    },
  });

  const filteredRuns = runs
    .filter((run) => {
      const marketMatched =
        runFilterMarket.trim().length === 0 ||
        (run.market ?? "").includes(runFilterMarket.trim());
      const statusMatched =
        runFilterStatus === "all" || run.status === runFilterStatus;
      const modeMatched =
        runFilterMode === "all" || run.mode === runFilterMode;
      return marketMatched && statusMatched && modeMatched;
    })
    .sort((left, right) => {
      if (runSortMode === "oldest") {
        return getRunSortTimestamp(left) - getRunSortTimestamp(right);
      }
      if (runSortMode === "market") {
        const marketCompare = (left.market ?? "").localeCompare(right.market ?? "");
        if (marketCompare !== 0) {
          return marketCompare;
        }
        return getRunSortTimestamp(right) - getRunSortTimestamp(left);
      }
      if (runSortMode === "status") {
        const statusCompare = getStatusRank(left.status) - getStatusRank(right.status);
        if (statusCompare !== 0) {
          return statusCompare;
        }
        return getRunSortTimestamp(right) - getRunSortTimestamp(left);
      }
      return getRunSortTimestamp(right) - getRunSortTimestamp(left);
    });

  const activeRunId = runId ?? filteredRuns[0]?.id ?? runs[0]?.id ?? null;

  const { data: activeRun } = useQuery<BacktestRunSummary>({
    queryKey: ["backtest-run", activeRunId],
    queryFn: () => api.backtests.get(activeRunId!),
    enabled: activeRunId != null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "completed" || status === "failed" ? false : 3_000;
    },
  });

  const { data: metrics } = useQuery<BacktestMetrics>({
    queryKey: ["backtest-metrics", activeRunId],
    queryFn: () => api.backtests.metrics(activeRunId!),
    enabled: activeRun?.status === "completed",
  });

  const { data: trades = [] } = useQuery<BacktestTradeRow[]>({
    queryKey: ["backtest-trades", activeRunId],
    queryFn: () => api.backtests.trades(activeRunId!),
    enabled: activeRun?.status === "completed",
  });

  const { data: windows = [] } = useQuery<BacktestWindowRow[]>({
    queryKey: ["backtest-windows", activeRunId],
    queryFn: () => api.backtests.windows(activeRunId!),
    enabled: activeRun?.status === "completed",
  });

  const invalidRange = testFrom > testTo;
  const invalidWalkForward = mode === "walk_forward" && stepDays < testWindowDays;
  const runErrorMessage = runError instanceof Error ? runError.message : null;

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <GlobalHeader />
        <main className="flex-1 overflow-auto p-6">
          <div className="mb-6 flex items-center gap-2">
            <BarChart2 className="h-5 w-5 text-emerald-400" />
            <h1 className="text-lg font-bold text-gray-100">백테스팅</h1>
          </div>

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1.2fr)_360px]">
            <div className="space-y-6">
              <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
                <div className="mb-4 flex items-center justify-between">
                  <div>
                    <div className="text-sm font-semibold text-gray-100">실행 설정</div>
                    <div className="mt-1 text-xs text-gray-500">
                      단일 구간 또는 워크포워드 검증을 같은 화면에서 실행합니다.
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => runBacktest()}
                    disabled={isPending || invalidRange || invalidWalkForward}
                    className="flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium transition-colors hover:bg-emerald-500 disabled:opacity-50"
                  >
                    <Play className="h-4 w-4" />
                    {isPending ? "실행 요청 중..." : "백테스트 실행"}
                  </button>
                </div>

                <div className="mb-4 flex items-center gap-2 rounded-lg border border-gray-800 bg-gray-950/40 p-1">
                  {[
                    { value: "single", label: "단일" },
                    { value: "walk_forward", label: "워크포워드" },
                  ].map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => setMode(option.value as "single" | "walk_forward")}
                      className={cn(
                        "rounded-md px-3 py-1.5 text-sm font-medium transition",
                        mode === option.value
                          ? "bg-sky-500/20 text-sky-300"
                          : "text-gray-500 hover:text-gray-200"
                      )}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>

                <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                  <div>
                    <label className="mb-1 block text-xs text-gray-500">마켓</label>
                    <input
                      value={market}
                      onChange={(e) => setMarket(e.target.value.toUpperCase())}
                      className="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm font-mono focus:border-emerald-500 focus:outline-none"
                      placeholder="KRW-BTC"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-gray-500">테스트 시작일</label>
                    <input
                      type="date"
                      value={testFrom}
                      onChange={(e) => setTestFrom(e.target.value)}
                      className="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-gray-500">테스트 종료일</label>
                    <input
                      type="date"
                      value={testTo}
                      onChange={(e) => setTestTo(e.target.value)}
                      className="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-gray-500">Train Window</label>
                    <input
                      type="number"
                      min={1}
                      value={trainWindowDays}
                      onChange={(e) => setTrainWindowDays(Number(e.target.value) || 1)}
                      className="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-gray-500">Test Window</label>
                    <input
                      type="number"
                      min={1}
                      value={testWindowDays}
                      onChange={(e) => setTestWindowDays(Number(e.target.value) || 1)}
                      disabled={mode === "single"}
                      className="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none disabled:opacity-50"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-gray-500">Step</label>
                    <input
                      type="number"
                      min={1}
                      value={stepDays}
                      onChange={(e) => setStepDays(Number(e.target.value) || 1)}
                      disabled={mode === "single"}
                      className="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none disabled:opacity-50"
                    />
                  </div>
                </div>

                <div className="mt-4 grid gap-3 md:grid-cols-2">
                  <div className="rounded-lg border border-gray-800 bg-gray-950/40 p-3 text-xs text-gray-500">
                    train {formatDay(`${shiftDateString(testFrom, -trainWindowDays)}T00:00:00`)} ~ {formatDay(`${testFrom}T00:00:00`)}
                  </div>
                  <div className="rounded-lg border border-gray-800 bg-gray-950/40 p-3 text-xs text-gray-500">
                    {mode === "walk_forward"
                      ? `test window ${testWindowDays}일 / step ${stepDays}일`
                      : `single test ${formatDay(`${testFrom}T00:00:00`)} ~ ${formatDay(`${testTo}T23:59:59`)}`}
                  </div>
                </div>

                {invalidRange ? (
                  <div className="mt-3 flex items-center gap-2 rounded-lg border border-amber-900 bg-amber-950/30 px-3 py-2 text-xs text-amber-200">
                    <AlertTriangle className="h-4 w-4 shrink-0" />
                    종료일이 시작일보다 빠를 수 없습니다.
                  </div>
                ) : null}
                {invalidWalkForward ? (
                  <div className="mt-3 flex items-center gap-2 rounded-lg border border-amber-900 bg-amber-950/30 px-3 py-2 text-xs text-amber-200">
                    <AlertTriangle className="h-4 w-4 shrink-0" />
                    워크포워드는 `step`이 `test window`보다 작을 수 없습니다.
                  </div>
                ) : null}
                {runErrorMessage ? (
                  <div className="mt-3 rounded-lg border border-red-900 bg-red-950/30 px-3 py-2 text-xs text-red-200">
                    실행 요청 실패: {runErrorMessage}
                  </div>
                ) : null}
              </div>

              {activeRun ? (
                <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
                  <div className="mb-4 flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold text-gray-100">
                        선택 실행 #{activeRun.id} · {activeRun.market ?? "unknown"}
                      </div>
                      <div className="mt-1 text-xs text-gray-500">
                        {activeRun.mode === "walk_forward" ? "walk-forward" : "single"} · 테스트 구간 {formatDay(activeRun.testFrom)} ~ {formatDay(activeRun.testTo)}
                      </div>
                    </div>
                    <span className={cn("rounded border px-2 py-1 text-[11px] uppercase tracking-wide", getStatusTone(activeRun.status))}>
                      {activeRun.status}
                    </span>
                  </div>

                  <div className="grid grid-cols-2 gap-3 text-xs md:grid-cols-4">
                    <div className="rounded-lg border border-gray-800 bg-gray-950/40 p-3">
                      <div className="text-gray-500">전략 / 모드</div>
                      <div className="mt-1 font-mono text-gray-200">{activeRun.strategyId}</div>
                      <div className="font-mono text-[11px] text-gray-600">{activeRun.mode}</div>
                    </div>
                    <div className="rounded-lg border border-gray-800 bg-gray-950/40 p-3">
                      <div className="text-gray-500">초기 자산</div>
                      <div className="mt-1 font-mono text-gray-200">{formatCurrency(activeRun.initialEquity)}</div>
                    </div>
                    <div className="rounded-lg border border-gray-800 bg-gray-950/40 p-3">
                      <div className="text-gray-500">손절 / 익절</div>
                      <div className="mt-1 font-mono text-gray-200">
                        {formatPct(activeRun.stopLossPct)} / {formatPct(activeRun.takeProfitPct)}
                      </div>
                    </div>
                    <div className="rounded-lg border border-gray-800 bg-gray-950/40 p-3">
                      <div className="text-gray-500">윈도우 / 스텝</div>
                      <div className="mt-1 font-mono text-gray-200">
                        {activeRun.testWindowDays ?? 0}일 / {activeRun.stepDays ?? 0}일
                      </div>
                    </div>
                  </div>

                  <div className="mt-3 grid grid-cols-2 gap-3 text-xs md:grid-cols-4">
                    <div className="rounded-lg border border-gray-800 bg-gray-950/40 p-3">
                      <div className="text-gray-500">Train</div>
                      <div className="mt-1 font-mono text-gray-200">{formatDay(activeRun.trainFrom)}</div>
                      <div className="font-mono text-[11px] text-gray-600">{formatDay(activeRun.trainTo)}</div>
                    </div>
                    <div className="rounded-lg border border-gray-800 bg-gray-950/40 p-3">
                      <div className="text-gray-500">Test</div>
                      <div className="mt-1 font-mono text-gray-200">{formatDay(activeRun.testFrom)}</div>
                      <div className="font-mono text-[11px] text-gray-600">{formatDay(activeRun.testTo)}</div>
                    </div>
                    <div className="rounded-lg border border-gray-800 bg-gray-950/40 p-3">
                      <div className="text-gray-500">시작 / 종료</div>
                      <div className="mt-1 font-mono text-gray-200">{formatDate(activeRun.startedAt)}</div>
                      <div className="font-mono text-[11px] text-gray-600">{formatDate(activeRun.finishedAt)}</div>
                    </div>
                    <div className="rounded-lg border border-gray-800 bg-gray-950/40 p-3">
                      <div className="text-gray-500">윈도우 수</div>
                      <div className="mt-1 font-mono text-gray-200">{windows.length}개</div>
                    </div>
                  </div>

                  {activeRun.status === "running" || activeRun.status === "pending" ? (
                    <div className="mt-4 flex items-center gap-2 rounded-lg border border-sky-900 bg-sky-950/30 px-3 py-2 text-xs text-sky-200">
                      <Clock3 className="h-4 w-4 shrink-0" />
                      백테스트가 아직 진행 중입니다. 상태와 결과를 자동으로 새로고침합니다.
                    </div>
                  ) : null}
                  {activeRun.status === "failed" && activeRun.errorMessage ? (
                    <div className="mt-4 rounded-lg border border-red-900 bg-red-950/30 px-3 py-2 text-xs text-red-200">
                      실패 사유: {activeRun.errorMessage}
                    </div>
                  ) : null}
                </div>
              ) : (
                <div className="rounded-xl border border-gray-800 bg-gray-900 p-6 text-sm text-gray-600">
                  아직 선택된 실행이 없습니다.
                </div>
              )}

              {activeRun?.status === "completed" && metrics ? (
                <>
                  <div className="grid gap-4 md:grid-cols-3">
                    <MetricCard label="CAGR" value={formatPct(metrics.cagr)} />
                    <MetricCard label="Sharpe" value={metrics.sharpe.toFixed(2)} />
                    <MetricCard label="최대 낙폭" value={formatPct(metrics.maxDrawdown)} negative />
                    <MetricCard label="승률" value={formatPct(metrics.winRate)} />
                    <MetricCard label="손익비" value={metrics.profitFactor.toFixed(2)} />
                    <MetricCard label="총 거래" value={`${metrics.totalTrades}건`} />
                  </div>

                  {windows.length > 0 ? <WindowOverviewChart windows={windows} /> : null}
                  {windows.length > 0 ? <WindowsTable windows={windows} /> : null}
                  <TradesTable trades={trades} />
                </>
              ) : null}
            </div>

            <RunList
              runs={filteredRuns}
              totalCount={runs.length}
              selectedRunId={activeRunId}
              onSelect={setRunId}
              filterMarket={runFilterMarket}
              filterStatus={runFilterStatus}
              filterMode={runFilterMode}
              sortMode={runSortMode}
              onFilterMarketChange={setRunFilterMarket}
              onFilterStatusChange={setRunFilterStatus}
              onFilterModeChange={setRunFilterMode}
              onSortModeChange={setRunSortMode}
            />
          </div>
        </main>
      </div>
    </div>
  );
}
