"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, ShieldAlert, TrendingDown, TrendingUp } from "lucide-react";
import { api } from "@/services/api";
import { cn } from "@/utils/cn";
import type {
  DailyReportResponse,
  ExcludedMarketItem,
  ExcludedMarketState,
  MarketTransitionQualityRow,
  PerformanceBreakdownRow,
  PerformanceResponse,
  PerformanceTrade,
  SignalTransitionRow,
  TransitionRecommendationSettings,
} from "@/types/market";

const RANGE_OPTIONS = [
  { label: "7D", value: 7 },
  { label: "30D", value: 30 },
  { label: "ALL", value: null },
] as const;

function formatCurrency(value: number) {
  const rounded = Math.round(value);
  return `${rounded >= 0 ? "+" : ""}${rounded.toLocaleString("ko-KR")}원`;
}

function formatPct(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}

function formatPrice(value: number) {
  return Math.round(value).toLocaleString("ko-KR");
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatScore(value: number | null) {
  if (value == null || Number.isNaN(value)) {
    return "-";
  }
  return value.toFixed(2);
}

function formatMinutes(value: number) {
  if (value < 60) {
    return `${Math.round(value)}분`;
  }
  const hours = Math.floor(value / 60);
  const minutes = Math.round(value % 60);
  return minutes > 0 ? `${hours}시간 ${minutes}분` : `${hours}시간`;
}

function formatDelta(value: number, suffix = "") {
  const rounded = Math.round(value * 10) / 10;
  const sign = rounded > 0 ? "+" : "";
  return `${sign}${rounded}${suffix}`;
}

function getWeakestBreakdown(rows: PerformanceBreakdownRow[]) {
  if (rows.length === 0) {
    return null;
  }
  return [...rows].sort((a, b) => a.netPnl - b.netPnl)[0] ?? null;
}

function getBreakdownLabel(
  row: PerformanceBreakdownRow | null,
  key: "market" | "scoreBand" | "hourBlock"
) {
  if (!row) {
    return "없음";
  }
  return row[key] ?? "unknown";
}

function getTransitionRecommendation(
  row: MarketTransitionQualityRow,
  isExcluded: boolean,
  settings: TransitionRecommendationSettings
): { label: string; description: string; tone: "red" | "emerald"; details: string[] } | null {
  const excludeRecommended =
    !isExcluded &&
    row.holdOriginCount >= settings.min_hold_origin_count &&
    row.holdToSellRate <= settings.exclude_max_hold_to_sell_rate &&
    row.holdToHoldRate >= settings.exclude_min_hold_to_hold_rate;
  if (excludeRecommended) {
    return {
      label: "제외 추천",
      description: "hold→sell 전환이 낮고 hold 유지 비율이 높습니다.",
      tone: "red",
      details: [
        `hold 시작 ${row.holdOriginCount}건 / 기준 ${settings.min_hold_origin_count}건 이상`,
        `hold→sell ${formatPct(row.holdToSellRate)} / 기준 ${formatPct(settings.exclude_max_hold_to_sell_rate)} 이하`,
        `hold→hold ${formatPct(row.holdToHoldRate)} / 기준 ${formatPct(settings.exclude_min_hold_to_hold_rate)} 이상`,
      ],
    };
  }

  const restoreRecommended =
    isExcluded &&
    row.holdOriginCount >= settings.min_hold_origin_count &&
    row.holdToSellRate >= settings.restore_min_hold_to_sell_rate &&
    row.holdToHoldRate <= settings.restore_max_hold_to_hold_rate;
  if (restoreRecommended) {
    return {
      label: "복귀 검토",
      description: "hold→sell 전환이 개선돼 재진입 후보로 볼 수 있습니다.",
      tone: "emerald",
      details: [
        `hold 시작 ${row.holdOriginCount}건 / 기준 ${settings.min_hold_origin_count}건 이상`,
        `hold→sell ${formatPct(row.holdToSellRate)} / 기준 ${formatPct(settings.restore_min_hold_to_sell_rate)} 이상`,
        `hold→hold ${formatPct(row.holdToHoldRate)} / 기준 ${formatPct(settings.restore_max_hold_to_hold_rate)} 이하`,
      ],
    };
  }

  return null;
}

function BreakdownList({
  title,
  rows,
  keyName,
}: {
  title: string;
  rows: PerformanceBreakdownRow[];
  keyName: "market" | "exitReason" | "scoreBand" | "sentimentBand" | "hourBlock";
}) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-950/40 p-3">
      <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">
        {title}
      </div>
      <div className="space-y-2">
        {rows.length === 0 ? (
          <div className="text-xs text-gray-600">데이터 없음</div>
        ) : (
          rows.slice(0, 4).map((row) => (
            <div key={`${keyName}-${row[keyName]}`} className="flex items-center justify-between text-xs">
              <div>
                {keyName === "market" ? (
                  <Link
                    href={`/performance/market/${row[keyName]}`}
                    className="font-mono text-sky-300 hover:text-sky-200"
                  >
                    {row[keyName] ?? "unknown"}
                  </Link>
                ) : (
                  <div className="font-mono text-gray-200">{row[keyName] ?? "unknown"}</div>
                )}
                <div className="text-gray-600">
                  {row.trades}건 · 승률 {formatPct(row.winRate)}
                </div>
              </div>
              <div
                className={cn(
                  "font-mono font-semibold",
                  row.netPnl >= 0 ? "text-emerald-400" : "text-red-400"
                )}
              >
                {formatCurrency(row.netPnl)}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function RecentTradesTable({ trades }: { trades: PerformanceTrade[] }) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-950/40">
      <div className="flex items-center justify-between border-b border-gray-800 px-3 py-2">
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">
          최근 종료 거래
        </div>
        <div className="text-[11px] text-gray-600">
          최근 {Math.min(trades.length, 6)}건
        </div>
      </div>
      <div className="max-h-[210px] overflow-auto">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-gray-950 text-gray-500">
            <tr>
              <th className="px-3 py-2 text-left font-medium">시장</th>
              <th className="px-3 py-2 text-left font-medium">전략 / 점수</th>
              <th className="px-3 py-2 text-left font-medium">청산</th>
              <th className="px-3 py-2 text-right font-medium">진입/청산가</th>
              <th className="px-3 py-2 text-right font-medium">수익률</th>
              <th className="px-3 py-2 text-right font-medium">순손익</th>
              <th className="px-3 py-2 text-right font-medium">보유</th>
            </tr>
          </thead>
          <tbody>
            {trades.slice(0, 6).map((trade) => (
              <tr key={`${trade.market}-${trade.exitTs}`} className="border-t border-gray-900 text-gray-300">
                <td className="px-3 py-2">
                  <Link
                    href={`/performance/market/${trade.market}`}
                    className="font-mono text-sky-300 hover:text-sky-200"
                  >
                    {trade.market}
                  </Link>
                  <div className="text-[11px] text-gray-600">{trade.exitReason}</div>
                </td>
                <td className="px-3 py-2">
                  <div className="font-mono text-gray-200">{trade.strategyId ?? "unknown"}</div>
                  <div className="text-[11px] text-gray-600">
                    TA {formatScore(trade.taScore)} · AI {formatScore(trade.sentimentScore)} · F {formatScore(trade.finalScore)}
                  </div>
                </td>
                <td className="px-3 py-2 text-gray-400">{formatDate(trade.exitTs)}</td>
                <td className="px-3 py-2 text-right">
                  <div className="font-mono text-gray-200">{formatPrice(trade.entryPrice)}</div>
                  <div className="font-mono text-[11px] text-gray-600">{formatPrice(trade.exitPrice)}</div>
                </td>
                <td
                  className={cn(
                    "px-3 py-2 text-right font-mono",
                    trade.returnPct >= 0 ? "text-emerald-400" : "text-red-400"
                  )}
                >
                  {formatPct(trade.returnPct)}
                </td>
                <td
                  className={cn(
                    "px-3 py-2 text-right font-mono font-semibold",
                    trade.netPnl >= 0 ? "text-emerald-400" : "text-red-400"
                  )}
                >
                  {formatCurrency(trade.netPnl)}
                </td>
                <td className="px-3 py-2 text-right font-mono text-gray-400">
                  {Math.round(trade.holdMinutes)}분
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TransitionList({ rows }: { rows: SignalTransitionRow[] }) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-950/40 p-3">
      <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">
        신호 전환 빈도
      </div>
      <div className="space-y-2">
        {rows.length === 0 ? (
          <div className="text-xs text-gray-600">데이터 없음</div>
        ) : (
          rows.slice(0, 4).map((row) => (
            <div key={row.transition} className="flex items-center justify-between text-xs">
              <div>
                <div className="font-mono text-gray-200">{row.transition}</div>
                <div className="text-gray-600">
                  {row.count}건 · 비중 {formatPct(row.share)} · 평균 간격 {formatMinutes(row.avgGapMinutes)}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function MarketTransitionQualityList({
  rows,
  excludedMarkets,
  pendingMarket,
  onToggleExcluded,
  recommendationSettings,
}: {
  rows: MarketTransitionQualityRow[];
  excludedMarkets: string[];
  pendingMarket: string | null;
  onToggleExcluded: (market: string) => void;
  recommendationSettings: TransitionRecommendationSettings;
}) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-950/40 p-3">
      <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">
        전환 취약 코인
      </div>
      <div className="space-y-2">
        {rows.length === 0 ? (
          <div className="text-xs text-gray-600">데이터 없음</div>
        ) : (
          rows.slice(0, 4).map((row) => (
            <div key={row.market} className="flex items-center justify-between text-xs">
              <div>
                <div className="flex items-center gap-2">
                  <Link
                    href={`/performance/market/${row.market}`}
                    className="font-mono text-sky-300 hover:text-sky-200"
                  >
                    {row.market}
                  </Link>
                  {excludedMarkets.includes(row.market) && (
                    <span className="rounded bg-red-950 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-red-300">
                      excluded
                    </span>
                  )}
                  {(() => {
                    const recommendation = getTransitionRecommendation(
                      row,
                      excludedMarkets.includes(row.market),
                      recommendationSettings
                    );
                    if (!recommendation) {
                      return null;
                    }
                    return (
                      <span
                        className={cn(
                          "rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide",
                          recommendation.tone === "red"
                            ? "bg-amber-950 text-amber-300"
                            : "bg-emerald-950 text-emerald-300"
                        )}
                      >
                        {recommendation.label}
                      </span>
                    );
                  })()}
                </div>
                <div className="text-gray-600">
                  hold→sell {formatPct(row.holdToSellRate)} · hold→hold {formatPct(row.holdToHoldRate)}
                </div>
                {(() => {
                  const recommendation = getTransitionRecommendation(
                    row,
                    excludedMarkets.includes(row.market),
                    recommendationSettings
                  );
                  if (!recommendation) {
                    return null;
                  }
                  return (
                    <div className="mt-1 text-[11px] text-gray-500">
                      <div>{recommendation.description}</div>
                      <div className="mt-1 space-y-0.5">
                        {recommendation.details.map((detail) => (
                          <div key={detail}>{detail}</div>
                        ))}
                      </div>
                    </div>
                  );
                })()}
              </div>
              <div className="text-right text-[11px] text-gray-500">
                <div>hold 시작 {row.holdOriginCount}건</div>
                <div>전체 전환 {row.totalTransitions}건</div>
                <button
                  type="button"
                  onClick={() => onToggleExcluded(row.market)}
                  disabled={pendingMarket === row.market}
                  className={cn(
                    "mt-2 rounded border px-2 py-1 text-[10px] font-semibold uppercase tracking-wide transition",
                    excludedMarkets.includes(row.market)
                      ? "border-emerald-700 text-emerald-300 hover:border-emerald-500"
                      : "border-red-700 text-red-300 hover:border-red-500",
                    pendingMarket === row.market && "opacity-50"
                  )}
                >
                  {pendingMarket === row.market
                    ? "저장 중"
                    : excludedMarkets.includes(row.market)
                      ? "복귀"
                      : "제외"}
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function DailyOpsSummary({ report }: { report: DailyReportResponse }) {
  const summary = report.summary;
  const weakestMarket = report.analysis.weakMarkets[0];
  const topRiskReason = report.analysis.riskRejectedReasons[0];
  const weakestPosition = report.positions[0] ?? null;
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-950/40 p-3">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">
          오늘 운영 요약
        </div>
        <div className="font-mono text-[11px] text-gray-600">{report.date}</div>
      </div>
      <div className="grid grid-cols-2 gap-3 text-xs">
        <div>
          <div className="text-gray-500">오늘 손익</div>
          <div className={cn("font-mono font-semibold", summary.dailyPnl >= 0 ? "text-emerald-400" : "text-red-400")}>
            {formatCurrency(summary.dailyPnl)}
          </div>
        </div>
        <div>
          <div className="text-gray-500">연속 손실</div>
          <div className={cn("font-mono font-semibold", summary.lossStreak >= 3 ? "text-amber-300" : "text-gray-200")}>
            {summary.lossStreak}회
          </div>
        </div>
        <div>
          <div className="text-gray-500">닫힌 거래</div>
          <div className="font-mono text-gray-200">
            {summary.closedTrades}건 · 승 {summary.wins} / 패 {summary.losses}
          </div>
        </div>
        <div>
          <div className="text-gray-500">열린 포지션</div>
          <div className="font-mono text-gray-200">
            {summary.openPositions}건 · 제외 {summary.excludedMarkets}개
          </div>
        </div>
        <div>
          <div className="text-gray-500">리스크 거절</div>
          <div className={cn("font-mono", summary.riskRejectedCount > 0 ? "text-amber-300" : "text-gray-200")}>
            {summary.riskRejectedCount}건
          </div>
        </div>
        <div>
          <div className="text-gray-500">주문 실패</div>
          <div className={cn("font-mono", summary.orderFailedCount > 0 ? "text-red-300" : "text-gray-200")}>
            {summary.orderFailedCount}건
          </div>
        </div>
      </div>
      {weakestPosition && (
        <div className="mt-3 border-t border-gray-800 pt-3 text-xs">
          <div className="mb-1 text-gray-500">가장 약한 열린 포지션</div>
          <div className="flex items-center justify-between gap-3">
            <div>
              <Link
                href={`/performance/market/${weakestPosition.market}`}
                className="font-mono text-sky-300 hover:text-sky-200"
              >
                {weakestPosition.market}
              </Link>
              <div className="text-gray-600">
                {weakestPosition.excluded ? `excluded · ${weakestPosition.excludedReason || "사유 없음"}` : weakestPosition.source}
              </div>
            </div>
            <div className={cn("font-mono font-semibold", weakestPosition.unrealizedPnl >= 0 ? "text-emerald-400" : "text-red-400")}>
              {formatCurrency(weakestPosition.unrealizedPnl)}
            </div>
          </div>
        </div>
      )}
      {(weakestMarket || topRiskReason) && (
        <div className="mt-3 border-t border-gray-800 pt-3 text-xs space-y-2">
          {weakestMarket && (
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-gray-500">오늘 최약 종료 시장</div>
                <Link
                  href={`/performance/market/${weakestMarket.market}`}
                  className="font-mono text-sky-300 hover:text-sky-200"
                >
                  {weakestMarket.market}
                </Link>
              </div>
              <div className={cn("font-mono font-semibold", weakestMarket.netPnl >= 0 ? "text-emerald-400" : "text-red-400")}>
                {formatCurrency(weakestMarket.netPnl)}
              </div>
            </div>
          )}
          {topRiskReason && (
            <div>
              <div className="text-gray-500">주요 리스크 거절 사유</div>
              <div className="text-gray-300">{topRiskReason.reason}</div>
              <div className="font-mono text-[11px] text-gray-600">{topRiskReason.count}건</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function DailyOpsHistory({ rows }: { rows: DailyReportResponse[] }) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-950/40 p-3">
      <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">
        최근 운영 이력
      </div>
      <div className="space-y-2">
        {rows.length === 0 ? (
          <div className="text-xs text-gray-600">저장된 일일 리포트 없음</div>
        ) : (
          rows.slice(0, 5).map((row) => (
            <div key={row.date} className="flex items-center justify-between text-xs">
              <div>
                <div className="font-mono text-gray-200">{row.date}</div>
                <div className="text-gray-600">
                  열린 {row.summary.openPositions}건 · 리스크 {row.summary.riskRejectedCount}건 · 실패 {row.summary.orderFailedCount}건
                </div>
              </div>
              <div
                className={cn(
                  "font-mono font-semibold",
                  row.summary.dailyPnl >= 0 ? "text-emerald-400" : "text-red-400"
                )}
              >
                {formatCurrency(row.summary.dailyPnl)}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function DailyOpsChanges({ rows }: { rows: DailyReportResponse[] }) {
  const current = rows[0] ?? null;
  const previous = rows[1] ?? null;

  if (!current) {
    return (
      <div className="rounded-xl border border-gray-800 bg-gray-950/40 p-3 text-xs text-gray-600">
        비교할 운영 snapshot이 아직 없습니다.
      </div>
    );
  }

  if (!previous) {
    return (
      <div className="rounded-xl border border-gray-800 bg-gray-950/40 p-3">
        <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">
          최근 7일 변화
        </div>
        <div className="text-xs text-gray-600">
          직전 일일 snapshot이 아직 없어 오늘 기준 변화 비교는 대기 중입니다.
        </div>
      </div>
    );
  }

  const currentWeakMarket = getWeakestBreakdown(current.analysis.weakMarkets);
  const previousWeakMarket = getWeakestBreakdown(previous.analysis.weakMarkets);
  const currentWeakScore = getWeakestBreakdown(current.analysis.byFinalScoreBand);
  const previousWeakScore = getWeakestBreakdown(previous.analysis.byFinalScoreBand);
  const currentWeakHour = getWeakestBreakdown(current.analysis.byHourBlock);
  const previousWeakHour = getWeakestBreakdown(previous.analysis.byHourBlock);
  const currentRiskReason = current.analysis.riskRejectedReasons[0] ?? null;
  const previousRiskReason = previous.analysis.riskRejectedReasons[0] ?? null;

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-950/40 p-3">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">
          최근 7일 변화
        </div>
        <div className="text-[11px] text-gray-600">
          {current.date} vs {previous.date}
        </div>
      </div>

      <div className="space-y-3 text-xs">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <div className="text-gray-500">일일 손익 변화</div>
            <div
              className={cn(
                "font-mono font-semibold",
                current.summary.dailyPnl - previous.summary.dailyPnl >= 0 ? "text-emerald-400" : "text-red-400"
              )}
            >
              {formatCurrency(current.summary.dailyPnl - previous.summary.dailyPnl)}
            </div>
          </div>
          <div>
            <div className="text-gray-500">리스크 거절 변화</div>
            <div
              className={cn(
                "font-mono font-semibold",
                current.summary.riskRejectedCount - previous.summary.riskRejectedCount <= 0 ? "text-emerald-400" : "text-amber-300"
              )}
            >
              {formatDelta(current.summary.riskRejectedCount - previous.summary.riskRejectedCount, "건")}
            </div>
          </div>
        </div>

        <div className="border-t border-gray-800 pt-3">
          <div className="text-gray-500">최약 score 구간 변화</div>
          <div className="mt-1 text-gray-300">
            {getBreakdownLabel(previousWeakScore, "scoreBand")} → {getBreakdownLabel(currentWeakScore, "scoreBand")}
          </div>
          <div className="font-mono text-[11px] text-gray-600">
            {formatCurrency(previousWeakScore?.netPnl ?? 0)} → {formatCurrency(currentWeakScore?.netPnl ?? 0)}
          </div>
        </div>

        <div className="border-t border-gray-800 pt-3">
          <div className="text-gray-500">최약 시간대 변화</div>
          <div className="mt-1 text-gray-300">
            {getBreakdownLabel(previousWeakHour, "hourBlock")} → {getBreakdownLabel(currentWeakHour, "hourBlock")}
          </div>
          <div className="font-mono text-[11px] text-gray-600">
            {formatCurrency(previousWeakHour?.netPnl ?? 0)} → {formatCurrency(currentWeakHour?.netPnl ?? 0)}
          </div>
        </div>

        <div className="border-t border-gray-800 pt-3">
          <div className="text-gray-500">취약 코인 변화</div>
          <div className="mt-1 text-gray-300">
            {getBreakdownLabel(previousWeakMarket, "market")} → {getBreakdownLabel(currentWeakMarket, "market")}
          </div>
          <div className="font-mono text-[11px] text-gray-600">
            {formatCurrency(previousWeakMarket?.netPnl ?? 0)} → {formatCurrency(currentWeakMarket?.netPnl ?? 0)}
          </div>
        </div>

        <div className="border-t border-gray-800 pt-3">
          <div className="text-gray-500">주요 리스크 거절 사유 변화</div>
          <div className="mt-1 text-gray-300">
            {(previousRiskReason?.reason ?? "없음")} → {(currentRiskReason?.reason ?? "없음")}
          </div>
          <div className="font-mono text-[11px] text-gray-600">
            {(previousRiskReason?.count ?? 0)}건 → {(currentRiskReason?.count ?? 0)}건
          </div>
        </div>
      </div>
    </div>
  );
}

export default function PerformancePanel() {
  const [days, setDays] = useState<number | null>(30);
  const [pendingMarket, setPendingMarket] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery<PerformanceResponse>({
    queryKey: ["portfolio-performance", days],
    queryFn: () => api.portfolio.performance({ limit: 100, days: days ?? undefined }),
    refetchInterval: 30_000,
  });
  const { data: excludedMarketState } = useQuery<ExcludedMarketState>({
    queryKey: ["excluded-markets"],
    queryFn: () => api.settings.getExcludedMarkets(),
    refetchInterval: 30_000,
  });
  const { data: recommendationSettings } = useQuery<TransitionRecommendationSettings>({
    queryKey: ["transition-recommendation-settings"],
    queryFn: () => api.settings.getTransitionRecommendationSettings(),
    refetchInterval: 30_000,
  });
  const { data: dailyReport } = useQuery<DailyReportResponse>({
    queryKey: ["portfolio-daily-report"],
    queryFn: () => api.portfolio.dailyReport(),
    refetchInterval: 30_000,
  });
  const { data: dailyReportHistory = [] } = useQuery<DailyReportResponse[]>({
    queryKey: ["portfolio-daily-report-history"],
    queryFn: () => api.portfolio.dailyReportHistory({ limit: 7 }),
    refetchInterval: 60_000,
  });

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-gray-600">
        성과 지표 로딩 중...
      </div>
    );
  }

  const summary = data?.summary;
  const byMarket = data?.byMarket ?? [];
  const byExitReason = data?.byExitReason ?? [];
  const byFinalScoreBand = data?.byFinalScoreBand ?? [];
  const bySentimentBand = data?.bySentimentBand ?? [];
  const byHourBlock = data?.byHourBlock ?? [];
  const byTransition = data?.byTransition ?? [];
  const byMarketTransitionQuality = data?.byMarketTransitionQuality ?? [];
  const excludedMarkets = excludedMarketState?.markets ?? [];
  const excludedItems = excludedMarketState?.items ?? [];
  const effectiveRecommendationSettings = recommendationSettings ?? {
    min_hold_origin_count: 3,
    exclude_max_hold_to_sell_rate: 0.2,
    exclude_min_hold_to_hold_rate: 0.6,
    restore_min_hold_to_sell_rate: 0.4,
    restore_max_hold_to_hold_rate: 0.35,
  };
  const trades = data?.trades ?? [];

  const handleToggleExcluded = async (market: string) => {
    const nextItems: ExcludedMarketItem[] = excludedMarkets.includes(market)
      ? excludedItems.filter((item) => item.market !== market)
      : [
          ...excludedItems,
          {
            market,
            reason: "전환 취약 코인 카드에서 수동 제외",
            updated_at: new Date().toISOString(),
          },
        ].sort((a, b) => a.market.localeCompare(b.market));
    setPendingMarket(market);
    try {
      await api.settings.setExcludedMarkets(nextItems);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["excluded-markets"] }),
        queryClient.invalidateQueries({ queryKey: ["portfolio-performance"] }),
      ]);
    } finally {
      setPendingMarket(null);
    }
  };

  if (!summary || summary.totalTrades === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-gray-600">
        아직 집계할 종료 거래가 없습니다.
      </div>
    );
  }

  const summaryCards = [
    {
      label: "순손익",
      value: formatCurrency(summary.netPnl),
      positive: summary.netPnl >= 0,
      icon: summary.netPnl >= 0 ? TrendingUp : TrendingDown,
    },
    {
      label: "승률",
      value: formatPct(summary.winRate),
      positive: summary.winRate >= 0.5,
      icon: BarChart3,
    },
    {
      label: "Profit Factor",
      value: Number.isFinite(summary.profitFactor) ? summary.profitFactor.toFixed(2) : "∞",
      positive: summary.profitFactor >= 1,
      icon: BarChart3,
    },
    {
      label: "최대 낙폭",
      value: formatCurrency(-summary.maxDrawdown),
      positive: false,
      icon: ShieldAlert,
    },
    {
      label: "평균 승리",
      value: formatCurrency(summary.avgWin),
      positive: summary.avgWin >= 0,
      icon: TrendingUp,
    },
    {
      label: "평균 손실",
      value: formatCurrency(summary.avgLoss),
      positive: false,
      icon: TrendingDown,
    },
  ];

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-gray-800 px-4 py-3">
        <div className="flex items-center gap-2">
          <BarChart3 className="h-4 w-4 text-sky-400" />
          <span className="text-sm font-semibold text-gray-100">실거래 성과</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="rounded-lg border border-gray-800 bg-gray-950/60 p-1">
            {RANGE_OPTIONS.map((option) => (
              <button
                key={option.label}
                type="button"
                onClick={() => setDays(option.value)}
                className={cn(
                  "rounded-md px-2 py-1 text-[11px] font-semibold tracking-[0.12em] transition",
                  days === option.value
                    ? "bg-sky-500/20 text-sky-300"
                    : "text-gray-500 hover:text-gray-200"
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
          <div className="text-xs text-gray-500">
            종료 거래 {summary.totalTrades}건
          </div>
        </div>
      </div>

      <div className="grid flex-1 grid-rows-[auto_1fr] gap-3 p-3">
        <div className="grid grid-cols-[1fr_0.7fr_0.6fr_0.5fr_0.5fr_0.5fr_0.5fr_0.5fr_0.5fr_0.5fr] gap-3">
          <div className="grid grid-cols-2 gap-3">
            {summaryCards.map((card) => {
              const Icon = card.icon;
              return (
                <div key={card.label} className="rounded-xl border border-gray-800 bg-gray-950/40 p-3">
                  <div className="mb-2 flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-gray-500">
                    <Icon className="h-3.5 w-3.5" />
                    <span>{card.label}</span>
                  </div>
                  <div
                    className={cn(
                      "font-mono text-lg font-bold",
                      card.positive ? "text-emerald-400" : "text-red-400"
                    )}
                  >
                    {card.value}
                  </div>
                </div>
              );
            })}
          </div>

          {dailyReport ? <DailyOpsSummary report={dailyReport} /> : <div className="rounded-xl border border-gray-800 bg-gray-950/40 p-3 text-xs text-gray-600">오늘 운영 요약 로딩 중...</div>}
          <DailyOpsHistory rows={dailyReportHistory} />
          <DailyOpsChanges rows={dailyReportHistory} />
          <BreakdownList title="시장별 손익" rows={byMarket} keyName="market" />
          <BreakdownList title="청산 사유" rows={byExitReason} keyName="exitReason" />
          <BreakdownList title="Final Score 구간" rows={byFinalScoreBand} keyName="scoreBand" />
          <BreakdownList title="감성 점수 구간" rows={bySentimentBand} keyName="sentimentBand" />
          <BreakdownList title="시간대별 성과" rows={byHourBlock} keyName="hourBlock" />
          <TransitionList rows={byTransition} />
          <MarketTransitionQualityList
            rows={byMarketTransitionQuality}
            excludedMarkets={excludedMarkets}
            pendingMarket={pendingMarket}
            onToggleExcluded={handleToggleExcluded}
            recommendationSettings={effectiveRecommendationSettings}
          />
        </div>

        <RecentTradesTable trades={trades} />
      </div>
    </div>
  );
}
