"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, ShieldAlert, TrendingDown, TrendingUp } from "lucide-react";
import { api } from "@/services/api";
import { cn } from "@/utils/cn";
import type {
  BacktestMetrics,
  BacktestRunSummary,
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

const DAILY_HISTORY_OPTIONS = [
  { label: "7D", value: 7 },
  { label: "30D", value: 30 },
  { label: "90D", value: 90 },
] as const;

function formatCurrency(value: number) {
  const rounded = Math.round(value);
  return `${rounded >= 0 ? "+" : ""}${rounded.toLocaleString("ko-KR")}원`;
}

function formatPct(value: number | null) {
  if (value == null || Number.isNaN(value)) {
    return "-";
  }
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

function formatDateKey(value: string) {
  const [, month = "00", day = "00"] = value.split("-");
  return `${month}.${day}`;
}

function formatScore(value: number | null) {
  if (value == null || Number.isNaN(value)) {
    return "-";
  }
  return value.toFixed(2);
}

function formatCount(value: number | null) {
  if (value == null || Number.isNaN(value)) {
    return "-";
  }
  return `${value}건`;
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

function buildSparklineMeta(values: number[], width: number, height: number) {
  if (values.length === 0) {
    return {
      points: [] as Array<{ x: number; y: number; value: number }>,
      linePath: "",
      areaPath: "",
      zeroY: height / 2,
    };
  }

  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const stepX = values.length === 1 ? 0 : width / (values.length - 1);
  const zeroY =
    max <= 0 ? 0 : min >= 0 ? height : height - ((0 - min) / range) * height;
  const points = values.map((value, index) => {
    const x = values.length === 1 ? width / 2 : index * stepX;
    const y = height - ((value - min) / range) * height;
    return { x, y, value };
  });
  const linePath = points
    .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`)
    .join(" ");
  const areaPath =
    points.length === 0
      ? ""
      : `M ${points[0].x} ${height} ${points
          .map((point) => `L ${point.x} ${point.y}`)
          .join(" ")} L ${points[points.length - 1].x} ${height} Z`;

  return {
    points,
    linePath,
    areaPath,
    zeroY,
  };
}

function getDailyHistoryStats(rows: DailyReportResponse[]) {
  if (rows.length === 0) {
    return null;
  }

  const ordered = [...rows].reverse();
  const totalPnl = ordered.reduce((sum, row) => sum + row.summary.dailyPnl, 0);
  const totalRiskRejected = ordered.reduce((sum, row) => sum + row.summary.riskRejectedCount, 0);
  const totalOrderFailures = ordered.reduce((sum, row) => sum + row.summary.orderFailedCount, 0);
  const bestDay =
    ordered.reduce((best, row) => (row.summary.dailyPnl > best.summary.dailyPnl ? row : best), ordered[0]) ?? null;
  const worstDay =
    ordered.reduce((worst, row) => (row.summary.dailyPnl < worst.summary.dailyPnl ? row : worst), ordered[0]) ?? null;

  return {
    ordered,
    totalPnl,
    avgPnl: totalPnl / ordered.length,
    totalRiskRejected,
    totalOrderFailures,
    bestDay,
    worstDay,
  };
}

function getMetricDeltaTone(value: number | null, inverse = false) {
  if (value == null || Number.isNaN(value)) {
    return "text-gray-600";
  }
  if (inverse) {
    return value <= 0 ? "text-emerald-400" : "text-red-400";
  }
  return value >= 0 ? "text-emerald-400" : "text-red-400";
}

function getDelta(base: number | null, current: number | null) {
  if (base == null || current == null || Number.isNaN(base) || Number.isNaN(current)) {
    return null;
  }
  return current - base;
}

function buildDailyTrendInsights(current: DailyReportResponse, previous: DailyReportResponse) {
  const insights: Array<{ tone: "emerald" | "amber" | "red"; message: string }> = [];
  const pnlDelta = current.summary.dailyPnl - previous.summary.dailyPnl;
  const riskDelta = current.summary.riskRejectedCount - previous.summary.riskRejectedCount;
  const failDelta = current.summary.orderFailedCount - previous.summary.orderFailedCount;

  const currentWeakScore = getWeakestBreakdown(current.analysis.byFinalScoreBand);
  const previousWeakScore = getWeakestBreakdown(previous.analysis.byFinalScoreBand);
  const currentWeakHour = getWeakestBreakdown(current.analysis.byHourBlock);
  const previousWeakHour = getWeakestBreakdown(previous.analysis.byHourBlock);
  const currentWeakMarket = getWeakestBreakdown(current.analysis.weakMarkets);
  const previousWeakMarket = getWeakestBreakdown(previous.analysis.weakMarkets);
  const currentRiskReason = current.analysis.riskRejectedReasons[0] ?? null;
  const previousRiskReason = previous.analysis.riskRejectedReasons[0] ?? null;

  if (pnlDelta >= 5000) {
    insights.push({ tone: "emerald", message: `일일 손익이 ${formatCurrency(pnlDelta)} 개선됐습니다.` });
  } else if (pnlDelta <= -5000) {
    insights.push({ tone: "red", message: `일일 손익이 ${formatCurrency(pnlDelta)} 악화됐습니다.` });
  }

  if (riskDelta <= -2) {
    insights.push({ tone: "emerald", message: `리스크 거절이 ${Math.abs(riskDelta)}건 줄었습니다.` });
  } else if (riskDelta >= 2) {
    insights.push({ tone: "amber", message: `리스크 거절이 ${riskDelta}건 늘었습니다.` });
  }

  if (failDelta <= -1) {
    insights.push({ tone: "emerald", message: `주문 실패가 ${Math.abs(failDelta)}건 줄었습니다.` });
  } else if (failDelta >= 1) {
    insights.push({ tone: "red", message: `주문 실패가 ${failDelta}건 늘었습니다.` });
  }

  if (
    currentWeakHour &&
    previousWeakHour &&
    currentWeakHour.hourBlock !== previousWeakHour.hourBlock &&
    currentWeakHour.netPnl < 0
  ) {
    insights.push({
      tone: "amber",
      message: `최약 시간대가 ${previousWeakHour.hourBlock}에서 ${currentWeakHour.hourBlock}로 바뀌었습니다.`,
    });
  }

  if (
    currentWeakScore &&
    previousWeakScore &&
    currentWeakScore.scoreBand !== previousWeakScore.scoreBand &&
    currentWeakScore.netPnl < 0
  ) {
    insights.push({
      tone: "amber",
      message: `최약 Final Score 구간이 ${previousWeakScore.scoreBand}에서 ${currentWeakScore.scoreBand}로 이동했습니다.`,
    });
  }

  if (
    currentWeakMarket &&
    previousWeakMarket &&
    currentWeakMarket.market !== previousWeakMarket.market &&
    currentWeakMarket.netPnl < 0
  ) {
    insights.push({
      tone: "red",
      message: `취약 코인이 ${previousWeakMarket.market}에서 ${currentWeakMarket.market}로 바뀌었습니다.`,
    });
  }

  if (
    currentRiskReason &&
    previousRiskReason &&
    currentRiskReason.reason !== previousRiskReason.reason &&
    currentRiskReason.count > 0
  ) {
    insights.push({
      tone: "amber",
      message: `주요 리스크 거절 사유가 '${currentRiskReason.reason}'로 바뀌었습니다.`,
    });
  }

  if (insights.length === 0) {
    insights.push({
      tone: "emerald",
      message: "직전 snapshot 대비 큰 악화 없이 비슷한 흐름을 유지했습니다.",
    });
  }

  return insights.slice(0, 4);
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

function BacktestBaselineCard({
  run,
  metrics,
  actual,
}: {
  run: BacktestRunSummary | null;
  metrics: BacktestMetrics | null;
  actual: PerformanceResponse["summary"];
}) {
  if (!run || !metrics) {
    return (
      <div className="rounded-xl border border-gray-800 bg-gray-950/40 p-3 text-xs text-gray-600">
        비교할 완료 백테스트가 아직 없습니다.
      </div>
    );
  }

  const winRateDelta = getDelta(metrics.winRate, actual.winRate);
  const profitFactorDelta = getDelta(metrics.profitFactor, actual.profitFactor);
  const tradeDelta = getDelta(metrics.totalTrades, actual.totalTrades);

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-950/40 p-3">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">
          백테스트 기준선
        </div>
        <div className="text-[11px] text-gray-600">#{run.id}</div>
      </div>

      <div className="mb-3 text-xs">
        <div className="font-mono text-sky-300">{run.market ?? "unknown"}</div>
        <div className="mt-1 text-gray-500">
          {run.mode === "walk_forward" ? "walk-forward" : "single"} · {run.testFrom.slice(0, 10)} ~ {run.testTo.slice(0, 10)}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="rounded-lg border border-gray-800 bg-gray-950/60 p-2">
          <div className="text-gray-500">기준 승률</div>
          <div className="mt-1 font-mono text-gray-200">{formatPct(metrics.winRate)}</div>
          <div className={cn("font-mono text-[11px]", getMetricDeltaTone(winRateDelta))}>
            실거래 {winRateDelta == null ? "-" : formatDelta(winRateDelta * 100, "%p")}
          </div>
        </div>
        <div className="rounded-lg border border-gray-800 bg-gray-950/60 p-2">
          <div className="text-gray-500">기준 PF</div>
          <div className="mt-1 font-mono text-gray-200">{formatScore(metrics.profitFactor)}</div>
          <div className={cn("font-mono text-[11px]", getMetricDeltaTone(profitFactorDelta))}>
            실거래 {profitFactorDelta == null ? "-" : formatDelta(profitFactorDelta)}
          </div>
        </div>
        <div className="rounded-lg border border-gray-800 bg-gray-950/60 p-2">
          <div className="text-gray-500">기준 거래수</div>
          <div className="mt-1 font-mono text-gray-200">{formatCount(metrics.totalTrades)}</div>
          <div className={cn("font-mono text-[11px]", getMetricDeltaTone(tradeDelta, true))}>
            실거래 {tradeDelta == null ? "-" : formatDelta(tradeDelta, "건")}
          </div>
        </div>
        <div className="rounded-lg border border-gray-800 bg-gray-950/60 p-2">
          <div className="text-gray-500">기준 낙폭</div>
          <div className="mt-1 font-mono text-gray-200">{formatPct(metrics.maxDrawdown)}</div>
          <div className="font-mono text-[11px] text-gray-600">
            CAGR {formatPct(metrics.cagr)}
          </div>
        </div>
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

function DailyOpsHistory({
  rows,
  selectedLimit,
  onSelectLimit,
}: {
  rows: DailyReportResponse[];
  selectedLimit: number;
  onSelectLimit: (limit: number) => void;
}) {
  const stats = getDailyHistoryStats(rows);
  const ordered = stats?.ordered ?? [];
  const pnlValues = ordered.map((row) => row.summary.dailyPnl);
  const sparkline = buildSparklineMeta(pnlValues, 240, 72);

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-950/40 p-3">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">
          운영 리포트 추세
        </div>
        <div className="rounded-lg border border-gray-800 bg-gray-950/60 p-1">
          {DAILY_HISTORY_OPTIONS.map((option) => (
            <button
              key={option.label}
              type="button"
              onClick={() => onSelectLimit(option.value)}
              className={cn(
                "rounded-md px-2 py-1 text-[10px] font-semibold tracking-[0.12em] transition",
                selectedLimit === option.value
                  ? "bg-sky-500/20 text-sky-300"
                  : "text-gray-500 hover:text-gray-200"
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="text-xs text-gray-600">저장된 일일 리포트 없음</div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div className="rounded-lg border border-gray-800 bg-gray-950/60 p-2">
              <div className="text-gray-500">누적 손익</div>
              <div className={cn("mt-1 font-mono font-semibold", (stats?.totalPnl ?? 0) >= 0 ? "text-emerald-400" : "text-red-400")}>
                {formatCurrency(stats?.totalPnl ?? 0)}
              </div>
            </div>
            <div className="rounded-lg border border-gray-800 bg-gray-950/60 p-2">
              <div className="text-gray-500">평균 일손익</div>
              <div className={cn("mt-1 font-mono font-semibold", (stats?.avgPnl ?? 0) >= 0 ? "text-emerald-400" : "text-red-400")}>
                {formatCurrency(stats?.avgPnl ?? 0)}
              </div>
            </div>
            <div className="rounded-lg border border-gray-800 bg-gray-950/60 p-2">
              <div className="text-gray-500">리스크 / 실패 누적</div>
              <div className="mt-1 font-mono text-gray-200">
                {stats?.totalRiskRejected ?? 0}건 / {stats?.totalOrderFailures ?? 0}건
              </div>
            </div>
            <div className="rounded-lg border border-gray-800 bg-gray-950/60 p-2">
              <div className="text-gray-500">최고 / 최저 일자</div>
              <div className="mt-1 font-mono text-gray-200">
                {stats?.bestDay ? formatDateKey(stats.bestDay.date) : "-"} / {stats?.worstDay ? formatDateKey(stats.worstDay.date) : "-"}
              </div>
            </div>
          </div>

          <div className="mt-3 rounded-lg border border-gray-800 bg-gray-950/60 p-2">
            <div className="mb-2 flex items-center justify-between text-[10px] text-gray-600">
              <span>
                {ordered[0] ? formatDateKey(ordered[0].date) : "-"} ~ {ordered[ordered.length - 1] ? formatDateKey(ordered[ordered.length - 1].date) : "-"}
              </span>
              <span>관찰 {ordered.length}일</span>
            </div>
            <div className="relative h-[88px]">
              <div
                className="pointer-events-none absolute inset-x-0 border-t border-dashed border-gray-800"
                style={{ top: `${sparkline.zeroY}px` }}
              />
              <svg viewBox="0 0 240 72" className="h-[72px] w-full overflow-visible">
                {sparkline.areaPath ? (
                  <path
                    d={sparkline.areaPath}
                    className="fill-sky-500/10"
                  />
                ) : null}
                {sparkline.linePath ? (
                  <path
                    d={sparkline.linePath}
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    className="text-sky-300"
                  />
                ) : null}
                {sparkline.points.map((point) => (
                  <circle
                    key={`${point.x}-${point.y}`}
                    cx={point.x}
                    cy={point.y}
                    r="2.5"
                    className={cn(point.value >= 0 ? "fill-emerald-400" : "fill-red-400")}
                  />
                ))}
              </svg>
              <div className="mt-2 flex items-center justify-between text-[10px] text-gray-600">
                <span>{ordered[0] ? formatDateKey(ordered[0].date) : "-"}</span>
                <span>일손익 추세</span>
                <span>{ordered[ordered.length - 1] ? formatDateKey(ordered[ordered.length - 1].date) : "-"}</span>
              </div>
            </div>
          </div>

          <div className="mt-3 space-y-2">
            {rows.slice(0, 4).map((row) => (
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
            ))}
          </div>
        </>
      )}
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
          직전 운영 변화
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
  const insights = buildDailyTrendInsights(current, previous);

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-950/40 p-3">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">
          직전 운영 변화
        </div>
        <div className="text-[11px] text-gray-600">
          {current.date} vs {previous.date}
        </div>
      </div>

      <div className="mb-3 space-y-2 border-b border-gray-800 pb-3 text-xs">
        {insights.map((insight) => (
          <div
            key={insight.message}
            className={cn(
              "rounded-lg border px-2 py-1.5",
              insight.tone === "emerald" && "border-emerald-900 bg-emerald-950/30 text-emerald-200",
              insight.tone === "amber" && "border-amber-900 bg-amber-950/30 text-amber-200",
              insight.tone === "red" && "border-red-900 bg-red-950/30 text-red-200"
            )}
          >
            {insight.message}
          </div>
        ))}
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
  const [dailyHistoryLimit, setDailyHistoryLimit] = useState<number>(7);
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
    queryKey: ["portfolio-daily-report-history", dailyHistoryLimit],
    queryFn: () => api.portfolio.dailyReportHistory({ limit: dailyHistoryLimit }),
    refetchInterval: 60_000,
  });
  const { data: backtestRuns = [] } = useQuery<BacktestRunSummary[]>({
    queryKey: ["dashboard-backtest-runs"],
    queryFn: () => api.backtests.list({ limit: 8 }),
    refetchInterval: 60_000,
  });
  const latestCompletedBacktest =
    backtestRuns.find((run) => run.status === "completed") ?? null;
  const { data: latestBacktestMetrics } = useQuery<BacktestMetrics | null>({
    queryKey: ["dashboard-backtest-metrics", latestCompletedBacktest?.id ?? null],
    queryFn: async () => {
      if (!latestCompletedBacktest) {
        return null;
      }
      return api.backtests.metrics(latestCompletedBacktest.id);
    },
    enabled: latestCompletedBacktest != null,
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
      value: Number.isFinite(summary.profitFactor) ? formatScore(summary.profitFactor) : "∞",
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
        <div className="grid grid-cols-[1fr_0.7fr_0.7fr_0.6fr_0.5fr_0.5fr_0.5fr_0.5fr_0.5fr_0.5fr_0.5fr] gap-3">
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
          <BacktestBaselineCard
            run={latestCompletedBacktest}
            metrics={latestBacktestMetrics ?? null}
            actual={summary}
          />
          <DailyOpsHistory
            rows={dailyReportHistory}
            selectedLimit={dailyHistoryLimit}
            onSelectLimit={setDailyHistoryLimit}
          />
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
