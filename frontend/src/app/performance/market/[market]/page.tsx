"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, BarChart3, ShieldAlert, TrendingDown, TrendingUp } from "lucide-react";
import Sidebar from "@/components/layout/Sidebar";
import GlobalHeader from "@/components/layout/GlobalHeader";
import { api } from "@/services/api";
import { cn } from "@/utils/cn";
import type {
  AuditEvent,
  ExcludedMarketState,
  MarketTransitionQualityRow,
  PerformanceBreakdownRow,
  PerformanceResponse,
  PerformanceTrade,
  Position,
  SignalData,
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

function formatGapMinutes(currentTs: string, previousTs?: string) {
  if (!previousTs) {
    return "시작";
  }
  const diffMs = new Date(previousTs).getTime() - new Date(currentTs).getTime();
  const diffMinutes = Math.max(Math.round(diffMs / 60000), 0);
  if (diffMinutes < 1) {
    return "직전";
  }
  if (diffMinutes < 60) {
    return `${diffMinutes}분 후`;
  }
  const hours = Math.floor(diffMinutes / 60);
  const minutes = diffMinutes % 60;
  return minutes > 0 ? `${hours}시간 ${minutes}분 후` : `${hours}시간 후`;
}

function describeSignalAlignment(position: Position | null, signal: SignalData | null) {
  if (!signal) {
    return "최근 신호 없음";
  }
  if (!position) {
    if (signal.side === "buy") {
      return "현재 포지션 없음, 신규 진입 후보";
    }
    if (signal.side === "sell") {
      return "현재 포지션 없음, 청산 신호만 존재";
    }
    return "현재 포지션 없음, 관망 상태";
  }
  if (signal.side === "sell") {
    return "포지션 보유 중이지만 최근 신호는 청산 방향";
  }
  if (signal.side === "buy") {
    return "포지션 방향과 최근 매수 신호가 일치";
  }
  return "포지션 보유 중, 최근 신호는 관망";
}

function SummaryCard({
  label,
  value,
  positive,
  icon: Icon,
}: {
  label: string;
  value: string;
  positive: boolean;
  icon: typeof TrendingUp;
}) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
      <div className="mb-2 flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-gray-500">
        <Icon className="h-3.5 w-3.5" />
        <span>{label}</span>
      </div>
      <div className={cn("font-mono text-lg font-bold", positive ? "text-emerald-400" : "text-red-400")}>
        {value}
      </div>
    </div>
  );
}

function BreakdownCard({ rows }: { rows: PerformanceBreakdownRow[] }) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
      <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">
        청산 사유별 성과
      </div>
      <div className="space-y-3">
        {rows.length === 0 ? (
          <div className="text-sm text-gray-600">데이터 없음</div>
        ) : (
          rows.map((row) => (
            <div key={row.exitReason} className="flex items-center justify-between text-sm">
              <div>
                <div className="font-mono text-gray-200">{row.exitReason}</div>
                <div className="text-xs text-gray-600">
                  {row.trades}건 · 승률 {formatPct(row.winRate)}
                </div>
              </div>
              <div className={cn("font-mono font-semibold", row.netPnl >= 0 ? "text-emerald-400" : "text-red-400")}>
                {formatCurrency(row.netPnl)}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function getTransitionRecommendation(
  row: MarketTransitionQualityRow | null,
  isExcluded: boolean,
  settings: TransitionRecommendationSettings
): { label: string; description: string; tone: "red" | "emerald" } | null {
  if (!row) {
    return null;
  }

  const excludeRecommended =
    !isExcluded &&
    row.holdOriginCount >= settings.min_hold_origin_count &&
    row.holdToSellRate <= settings.exclude_max_hold_to_sell_rate &&
    row.holdToHoldRate >= settings.exclude_min_hold_to_hold_rate;
  if (excludeRecommended) {
    return {
      label: "제외 추천",
      description: "hold→sell 전환이 낮고 hold 유지 비율이 높아 운용 제외 후보입니다.",
      tone: "red",
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
      description: "hold→sell 전환이 개선돼 자동매매 복귀를 검토할 수 있습니다.",
      tone: "emerald",
    };
  }

  return null;
}

function getOperationLabel(event: AuditEvent) {
  if (event.eventType === "excluded_market_added") {
    return "제외";
  }
  if (event.eventType === "excluded_market_restored") {
    return "복귀";
  }
  if (event.eventType === "excluded_market_reason_updated") {
    return "사유 변경";
  }
  return event.eventType;
}

function ExclusionHistoryCard({
  isExcluded,
  excludedReason,
  excludedUpdatedAt,
  events,
  recommendation,
  transitionQuality,
}: {
  isExcluded: boolean;
  excludedReason: string;
  excludedUpdatedAt: string;
  events: AuditEvent[];
  recommendation: { label: string; description: string; tone: "red" | "emerald" } | null;
  transitionQuality: MarketTransitionQualityRow | null;
}) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">
          최근 운영 조치
        </div>
        <div className="text-xs text-gray-600">
          최근 {Math.min(events.length, 5)}건
        </div>
      </div>
      {isExcluded ? (
        <div className="mb-3 rounded-lg border border-red-900 bg-red-950/30 px-3 py-2 text-xs text-red-200">
          <div>현재 제외 상태입니다.</div>
          {excludedReason && <div className="mt-1">사유: {excludedReason}</div>}
          {excludedUpdatedAt && (
            <div className="mt-1 text-red-300/80">
              마지막 변경: {formatDate(excludedUpdatedAt)}
            </div>
          )}
        </div>
      ) : (
        <div className="mb-3 rounded-lg border border-gray-800 bg-gray-950/50 px-3 py-2 text-xs text-gray-400">
          현재는 자동매매 제외 상태가 아닙니다.
        </div>
      )}
      {recommendation && (
        <div
          className={cn(
            "mb-3 rounded-lg border px-3 py-2 text-xs",
            recommendation.tone === "red"
              ? "border-amber-900 bg-amber-950/30 text-amber-200"
              : "border-emerald-900 bg-emerald-950/30 text-emerald-200"
          )}
        >
          <div className="font-semibold">{recommendation.label}</div>
          <div className="mt-1">{recommendation.description}</div>
        </div>
      )}
      {transitionQuality && (
        <div className="mb-3 grid grid-cols-2 gap-3 text-xs text-gray-500">
          <div>
            hold→sell <span className="font-mono text-gray-300">{formatPct(transitionQuality.holdToSellRate)}</span>
          </div>
          <div>
            hold→hold <span className="font-mono text-gray-300">{formatPct(transitionQuality.holdToHoldRate)}</span>
          </div>
          <div>
            hold 시작 <span className="font-mono text-gray-300">{transitionQuality.holdOriginCount}건</span>
          </div>
          <div>
            전체 전환 <span className="font-mono text-gray-300">{transitionQuality.totalTransitions}건</span>
          </div>
        </div>
      )}
      {events.length === 0 ? (
        <div className="text-sm text-gray-600">최근 운영 조치 기록 없음</div>
      ) : (
        <div className="space-y-2">
          {events.slice(0, 5).map((event) => (
            <div key={event.id} className="rounded-lg border border-gray-800/80 bg-gray-950/40 px-3 py-2 text-xs">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <span className={cn(
                    "rounded px-2 py-1 text-[10px] uppercase tracking-wide",
                    event.eventType === "excluded_market_added" && "bg-red-950 text-red-300",
                    event.eventType === "excluded_market_restored" && "bg-emerald-950 text-emerald-300",
                    event.eventType === "excluded_market_reason_updated" && "bg-amber-950 text-amber-300",
                  )}>
                    {getOperationLabel(event)}
                  </span>
                  <span className="font-mono text-gray-200">{formatDate(event.ts)}</span>
                </div>
                <span className="text-[11px] text-gray-600">{event.source}</span>
              </div>
              <div className="mt-2 text-gray-300">{event.message}</div>
              {event.payload && (
                <div className="mt-2 text-[11px] text-gray-500">
                  {"reason" in event.payload && typeof event.payload.reason === "string" && event.payload.reason
                    ? `사유: ${event.payload.reason}`
                    : "previous_reason" in event.payload && "reason" in event.payload
                      ? `변경: ${String(event.payload.previous_reason || "-")} → ${String(event.payload.reason || "-")}`
                      : null}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function CurrentPositionCard({ position }: { position: Position | null }) {
  if (!position) {
    return (
      <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
        <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">
          현재 열린 포지션
        </div>
        <div className="text-sm text-gray-600">현재 보유 포지션 없음</div>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">
          현재 열린 포지션
        </div>
        <span
          className={cn(
            "rounded px-2 py-1 text-[10px] uppercase tracking-wide",
            position.source === "strategy"
              ? "bg-emerald-950 text-emerald-300"
              : "bg-amber-950 text-amber-300"
          )}
        >
          {position.source}
        </span>
      </div>
      {position.holdStale && position.holdWarning && (
        <div className="mb-3 rounded-lg border border-amber-900 bg-amber-950/40 px-3 py-2 text-xs text-amber-300">
          {position.holdWarning}
        </div>
      )}
      {!position.holdStale && position.consecutiveHoldCount > 0 && position.holdDurationMinutes != null && (
        <div className="mb-3 text-xs text-gray-500">
          최근 {position.consecutiveHoldCount}개 연속 hold · 약 {Math.round(position.holdDurationMinutes)}분째 관망 중
        </div>
      )}
      <div className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <div className="text-gray-500">수량</div>
          <div className="font-mono text-gray-100">{position.qty.toFixed(6)}</div>
        </div>
        <div>
          <div className="text-gray-500">평균단가</div>
          <div className="font-mono text-gray-100">{Math.round(position.avgEntryPrice).toLocaleString("ko-KR")}</div>
        </div>
        <div>
          <div className="text-gray-500">미실현손익</div>
          <div className={cn("font-mono font-semibold", position.unrealizedPnl >= 0 ? "text-emerald-400" : "text-red-400")}>
            {formatCurrency(position.unrealizedPnl)}
          </div>
        </div>
        <div>
          <div className="text-gray-500">실현손익</div>
          <div className={cn("font-mono font-semibold", position.realizedPnl >= 0 ? "text-emerald-400" : "text-red-400")}>
            {formatCurrency(position.realizedPnl)}
          </div>
        </div>
        <div>
          <div className="text-gray-500">Stop Loss</div>
          <div className="font-mono text-gray-100">
            {position.stopLoss ? Math.round(position.stopLoss).toLocaleString("ko-KR") : "-"}
          </div>
        </div>
        <div>
          <div className="text-gray-500">Take Profit</div>
          <div className="font-mono text-gray-100">
            {position.takeProfit ? Math.round(position.takeProfit).toLocaleString("ko-KR") : "-"}
          </div>
        </div>
      </div>
    </div>
  );
}

function RecentSignalCard({
  position,
  signals,
}: {
  position: Position | null;
  signals: SignalData[];
}) {
  const latestSignal = signals[0] ?? null;
  const alignmentText = describeSignalAlignment(position, latestSignal);

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">
          최근 신호
        </div>
        {latestSignal && (
          <span
            className={cn(
              "rounded px-2 py-1 text-[10px] uppercase tracking-wide",
              latestSignal.side === "buy" && "bg-emerald-950 text-emerald-300",
              latestSignal.side === "sell" && "bg-red-950 text-red-300",
              latestSignal.side === "hold" && "bg-slate-800 text-slate-300"
            )}
          >
            {latestSignal.side}
          </span>
        )}
      </div>

      {!latestSignal ? (
        <div className="text-sm text-gray-600">최근 신호 없음</div>
      ) : (
        <div className="space-y-3">
          <div>
            <div className="text-sm text-gray-300">{alignmentText}</div>
            <div className="mt-1 text-xs text-gray-600">{formatDate(latestSignal.ts)} · {latestSignal.strategyId}</div>
          </div>
          {(latestSignal.displayReason || latestSignal.rejectionReason) && (
            <div className="rounded-lg border border-gray-800 bg-gray-950/70 px-3 py-2 text-xs text-gray-400">
              최근 신호 사유: {latestSignal.displayReason || latestSignal.rejectionReason}
            </div>
          )}
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <div className="text-gray-500">TA</div>
              <div className="font-mono text-gray-100">{formatScore(latestSignal.taScore)}</div>
            </div>
            <div>
              <div className="text-gray-500">감성</div>
              <div className="font-mono text-gray-100">{formatScore(latestSignal.sentimentScore)}</div>
            </div>
            <div>
              <div className="text-gray-500">Final</div>
              <div className="font-mono text-gray-100">{formatScore(latestSignal.finalScore)}</div>
            </div>
            <div>
              <div className="text-gray-500">Confidence</div>
              <div className="font-mono text-gray-100">{formatScore(latestSignal.confidence)}</div>
            </div>
          </div>
          <div className="border-t border-gray-800 pt-3">
            <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">
              최근 5개
            </div>
            <div className="space-y-2">
              {signals.slice(0, 5).map((signal) => (
                <div key={signal.id} className="rounded-lg border border-gray-800/80 bg-gray-950/40 px-3 py-2 text-xs">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="font-mono text-gray-200">{signal.side}</div>
                      <div className="text-gray-600">{formatDate(signal.ts)}</div>
                    </div>
                    <div className="text-right">
                      <div className="font-mono text-gray-300">F {formatScore(signal.finalScore)}</div>
                      <div className="text-gray-600">{signal.status}</div>
                    </div>
                  </div>
                  {(signal.displayReason || signal.rejectionReason) && (
                    <div className="mt-2 text-[11px] text-gray-500">
                      {signal.displayReason || signal.rejectionReason}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function SignalTimelineCard({ signals }: { signals: SignalData[] }) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900">
      <div className="flex items-center justify-between border-b border-gray-800 px-4 py-3">
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">
          최근 신호 타임라인
        </div>
        <div className="text-xs text-gray-600">최근 {signals.length}건</div>
      </div>
      <div className="divide-y divide-gray-800/80">
        {signals.length === 0 ? (
          <div className="px-4 py-8 text-sm text-gray-600">신호 데이터 없음</div>
        ) : (
          signals.map((signal, index) => {
            const nextSignal = signals[index + 1];
            return (
              <div key={signal.id} className="px-4 py-3">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          "rounded px-2 py-1 text-[10px] uppercase tracking-wide",
                          signal.side === "buy" && "bg-emerald-950 text-emerald-300",
                          signal.side === "sell" && "bg-red-950 text-red-300",
                          signal.side === "hold" && "bg-slate-800 text-slate-300"
                        )}
                      >
                        {signal.side}
                      </span>
                      <span className="font-mono text-xs text-gray-200">{formatDate(signal.ts)}</span>
                      <span className="text-[11px] text-gray-600">{formatGapMinutes(signal.ts, nextSignal?.ts)}</span>
                    </div>
                    <div className="mt-2 grid grid-cols-2 gap-3 text-[11px] text-gray-500 sm:grid-cols-4">
                      <div>TA <span className="font-mono text-gray-300">{formatScore(signal.taScore)}</span></div>
                      <div>감성 <span className="font-mono text-gray-300">{formatScore(signal.sentimentScore)}</span></div>
                      <div>Final <span className="font-mono text-gray-300">{formatScore(signal.finalScore)}</span></div>
                      <div>Conf <span className="font-mono text-gray-300">{formatScore(signal.confidence)}</span></div>
                    </div>
                    {(signal.displayReason || signal.rejectionReason) && (
                      <div className="mt-2 text-xs text-gray-400">
                        {signal.displayReason || signal.rejectionReason}
                      </div>
                    )}
                  </div>
                  <div className="text-right text-[11px] text-gray-500">
                    <div>{signal.status}</div>
                    <div className="mt-1 font-mono text-gray-600">{signal.strategyId}</div>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

type IChartApi = import("lightweight-charts").IChartApi;
type ISeriesApi = import("lightweight-charts").ISeriesApi<"Area">;

function EquityCurveRangeCard({
  market,
  points,
  latest,
}: {
  market: string;
  points: Array<{ ts: string; equity: number }>;
  latest: { equity?: number } | null | undefined;
}) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const areaSeriesRef = useRef<ISeriesApi | null>(null);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    let removeResizeObserver: (() => void) | undefined;

    import("lightweight-charts").then(({ createChart, AreaSeries, ColorType }) => {
      if (!chartContainerRef.current) return;

      const chart = createChart(chartContainerRef.current, {
        layout: {
          background: { type: ColorType.Solid, color: "#111827" },
          textColor: "#6b7280",
        },
        grid: {
          vertLines: { color: "#17202e" },
          horzLines: { color: "#17202e" },
        },
        rightPriceScale: {
          borderColor: "#243041",
          scaleMargins: { top: 0.2, bottom: 0.18 },
        },
        timeScale: {
          borderColor: "#243041",
          timeVisible: true,
        },
        crosshair: { mode: 0 },
        width: chartContainerRef.current.clientWidth,
        height: 220,
      });

      const series = chart.addSeries(AreaSeries, {
        lineColor: "#38bdf8",
        topColor: "rgba(56, 189, 248, 0.24)",
        bottomColor: "rgba(56, 189, 248, 0.02)",
        lineWidth: 2,
      });

      chartRef.current = chart;
      areaSeriesRef.current = series;

      const resizeObserver = new ResizeObserver(() => {
        if (!chartContainerRef.current) return;
        chart.applyOptions({
          width: chartContainerRef.current.clientWidth,
          height: 220,
        });
      });
      resizeObserver.observe(chartContainerRef.current);
      removeResizeObserver = () => resizeObserver.disconnect();
    });

    return () => {
      removeResizeObserver?.();
      chartRef.current?.remove();
      chartRef.current = null;
      areaSeriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!areaSeriesRef.current) return;
    areaSeriesRef.current.setData(
      points.map((point) => ({
        time: (new Date(point.ts).getTime() / 1000) as import("lightweight-charts").Time,
        value: point.equity,
      }))
    );
    chartRef.current?.timeScale().fitContent();
  }, [points]);

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">
          포트폴리오 자산곡선 참고
        </div>
        <div className="font-mono text-sm text-gray-200">
          {latest?.equity ? `${Math.round(latest.equity).toLocaleString("ko-KR")}원` : "-"}
        </div>
      </div>
      <div className="mb-3 text-xs text-gray-600">
        이 곡선은 {`"${market}"`} 단일 코인 성과가 아니라, 선택 기간의 전체 포트폴리오 자산 흐름입니다.
      </div>
      {points.length === 0 ? (
        <div className="flex h-[220px] items-center justify-center text-sm text-gray-600">
          곡선 데이터 없음
        </div>
      ) : (
        <div ref={chartContainerRef} className="h-[220px] w-full" />
      )}
    </div>
  );
}

function TradesTable({ trades }: { trades: PerformanceTrade[] }) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900">
      <div className="flex items-center justify-between border-b border-gray-800 px-4 py-3">
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-gray-500">
          종료 거래 상세
        </div>
        <div className="text-xs text-gray-600">총 {trades.length}건</div>
      </div>
      <div className="overflow-auto">
        <table className="w-full text-xs">
          <thead className="bg-gray-950 text-gray-500">
            <tr>
              <th className="px-4 py-2 text-left font-medium">청산 시각</th>
              <th className="px-4 py-2 text-left font-medium">전략 / 점수</th>
              <th className="px-4 py-2 text-right font-medium">진입/청산가</th>
              <th className="px-4 py-2 text-right font-medium">수익률</th>
              <th className="px-4 py-2 text-right font-medium">순손익</th>
              <th className="px-4 py-2 text-right font-medium">보유</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((trade) => (
              <tr key={`${trade.market}-${trade.exitTs}`} className="border-t border-gray-800 text-gray-300">
                <td className="px-4 py-3">
                  <div className="text-gray-200">{formatDate(trade.exitTs)}</div>
                  <div className="text-[11px] text-gray-600">{trade.exitReason}</div>
                </td>
                <td className="px-4 py-3">
                  <div className="font-mono text-gray-200">{trade.strategyId ?? "unknown"}</div>
                  <div className="text-[11px] text-gray-600">
                    TA {formatScore(trade.taScore)} · AI {formatScore(trade.sentimentScore)} · F {formatScore(trade.finalScore)}
                  </div>
                </td>
                <td className="px-4 py-3 text-right">
                  <div className="font-mono text-gray-200">{Math.round(trade.entryPrice).toLocaleString("ko-KR")}</div>
                  <div className="font-mono text-[11px] text-gray-600">{Math.round(trade.exitPrice).toLocaleString("ko-KR")}</div>
                </td>
                <td className={cn("px-4 py-3 text-right font-mono", trade.returnPct >= 0 ? "text-emerald-400" : "text-red-400")}>
                  {formatPct(trade.returnPct)}
                </td>
                <td className={cn("px-4 py-3 text-right font-mono font-semibold", trade.netPnl >= 0 ? "text-emerald-400" : "text-red-400")}>
                  {formatCurrency(trade.netPnl)}
                </td>
                <td className="px-4 py-3 text-right font-mono text-gray-400">{Math.round(trade.holdMinutes)}분</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function MarketPerformancePage() {
  const params = useParams<{ market: string }>();
  const market = decodeURIComponent(params.market);
  const [days, setDays] = useState<number | null>(30);
  const { data: excludedMarketState } = useQuery<ExcludedMarketState>({
    queryKey: ["excluded-markets"],
    queryFn: () => api.settings.getExcludedMarkets(),
    refetchInterval: 30_000,
  });
  const excludedMarkets = excludedMarketState?.markets ?? [];
  const excludedItem = excludedMarketState?.items.find((item) => item.market === market);
  const excludedReason = excludedItem?.reason ?? "";
  const excludedUpdatedAt = excludedItem?.updated_at ?? "";
  const isExcluded = excludedMarkets.includes(market);

  const { data, isLoading } = useQuery<PerformanceResponse>({
    queryKey: ["portfolio-performance-market", market, days],
    queryFn: () => api.portfolio.performance({ limit: 100, days: days ?? undefined, market }),
    refetchInterval: 30_000,
  });
  const { data: positions = [] } = useQuery<Position[]>({
    queryKey: ["positions", market],
    queryFn: api.portfolio.positions,
    refetchInterval: 30_000,
  });
  const { data: signals = [] } = useQuery<SignalData[]>({
    queryKey: ["signals", market, "recent"],
    queryFn: () => api.signals.list({ market, limit: 20 }),
    refetchInterval: 30_000,
  });
  const { data: transitionQualityRows = [] } = useQuery<MarketTransitionQualityRow[]>({
    queryKey: ["portfolio-performance-transition-quality", days],
    queryFn: async () => {
      const response = await api.portfolio.performance({ limit: 100, days: days ?? undefined });
      return response.byMarketTransitionQuality ?? [];
    },
    refetchInterval: 30_000,
  });
  const { data: recommendationSettings } = useQuery<TransitionRecommendationSettings>({
    queryKey: ["transition-recommendation-settings"],
    queryFn: () => api.settings.getTransitionRecommendationSettings(),
    refetchInterval: 30_000,
  });
  const { data: operationEvents = [] } = useQuery<AuditEvent[]>({
    queryKey: ["audit", "market-exclusion-ops", market],
    queryFn: async () => {
      const rows = await api.audit.list({ source: "settings", market, limit: 20 });
      return rows.filter((row) =>
        [
          "excluded_market_added",
          "excluded_market_restored",
          "excluded_market_reason_updated",
        ].includes(row.eventType)
      );
    },
    refetchInterval: 30_000,
  });
  const { data: equityCurveResponse } = useQuery<{
    data: Array<{ ts: string; equity: number }>;
    latest: { equity?: number } | null;
  }>({
    queryKey: ["equity-curve", days],
    queryFn: () => api.portfolio.equityCurve({ limit: 300, days: days ?? undefined }),
    refetchInterval: 30_000,
  });

  const summary = data?.summary;
  const trades = data?.trades ?? [];
  const byExitReason = data?.byExitReason ?? [];
  const currentPosition = positions.find((position) => position.market === market) ?? null;
  const equityCurve = equityCurveResponse?.data ?? [];
  const equityLatest = equityCurveResponse?.latest;
  const transitionQuality = transitionQualityRows.find((row) => row.market === market) ?? null;
  const effectiveRecommendationSettings = recommendationSettings ?? {
    min_hold_origin_count: 3,
    exclude_max_hold_to_sell_rate: 0.2,
    exclude_min_hold_to_hold_rate: 0.6,
    restore_min_hold_to_sell_rate: 0.4,
    restore_max_hold_to_hold_rate: 0.35,
  };
  const recommendation = getTransitionRecommendation(
    transitionQuality,
    isExcluded,
    effectiveRecommendationSettings
  );

  return (
    <div className="h-screen flex overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <GlobalHeader />
        <main className="flex-1 overflow-auto p-6">
          <div className="mb-6 flex items-center justify-between gap-4">
            <div>
              <Link href="/" className="mb-3 inline-flex items-center gap-2 text-sm text-gray-500 hover:text-gray-200">
                <ArrowLeft className="h-4 w-4" />
                대시보드로 돌아가기
              </Link>
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-bold text-gray-100">{market} 상세 성과</h1>
                {isExcluded && (
                  <span className="rounded px-2 py-1 text-[10px] uppercase tracking-wide bg-red-950 text-red-300">
                    excluded
                  </span>
                )}
              </div>
              <div className="mt-1 text-sm text-gray-500">코인별 종료 거래와 청산 사유를 분리해서 봅니다.</div>
              {isExcluded && (
                <div className="mt-2 text-xs text-red-300">
                  현재 이 코인은 자동매매 신호 생성 대상에서 제외돼 있습니다.
                </div>
              )}
              {isExcluded && excludedReason && (
                <div className="mt-1 text-xs text-red-400">
                  제외 사유: {excludedReason}
                </div>
              )}
            </div>
            <div className="rounded-lg border border-gray-800 bg-gray-950/60 p-1">
              {RANGE_OPTIONS.map((option) => (
                <button
                  key={option.label}
                  type="button"
                  onClick={() => setDays(option.value)}
                  className={cn(
                    "rounded-md px-3 py-1.5 text-[11px] font-semibold tracking-[0.12em] transition",
                    days === option.value ? "bg-sky-500/20 text-sky-300" : "text-gray-500 hover:text-gray-200"
                  )}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          {isLoading ? (
            <div className="rounded-xl border border-gray-800 bg-gray-900 p-10 text-center text-sm text-gray-600">
              성과 데이터 로딩 중...
            </div>
          ) : !summary || summary.totalTrades === 0 ? (
            <div className="rounded-xl border border-gray-800 bg-gray-900 p-10 text-center text-sm text-gray-600">
              선택한 기간에 종료 거래가 없습니다.
            </div>
          ) : (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                <SummaryCard label="순손익" value={formatCurrency(summary.netPnl)} positive={summary.netPnl >= 0} icon={summary.netPnl >= 0 ? TrendingUp : TrendingDown} />
                <SummaryCard label="승률" value={formatPct(summary.winRate)} positive={summary.winRate >= 0.5} icon={BarChart3} />
                <SummaryCard label="Profit Factor" value={Number.isFinite(summary.profitFactor) ? summary.profitFactor.toFixed(2) : "∞"} positive={summary.profitFactor >= 1} icon={BarChart3} />
                <SummaryCard label="최대 낙폭" value={formatCurrency(-summary.maxDrawdown)} positive={false} icon={ShieldAlert} />
              </div>

              <div className="grid gap-4 lg:grid-cols-[0.8fr_1.2fr]">
                <div className="space-y-4">
                  <CurrentPositionCard position={currentPosition} />
                  <ExclusionHistoryCard
                    isExcluded={isExcluded}
                    excludedReason={excludedReason}
                    excludedUpdatedAt={excludedUpdatedAt}
                    events={operationEvents}
                    recommendation={recommendation}
                    transitionQuality={transitionQuality}
                  />
                  <RecentSignalCard position={currentPosition} signals={signals} />
                  <SignalTimelineCard signals={signals} />
                  <EquityCurveRangeCard market={market} points={equityCurve} latest={equityLatest} />
                  <BreakdownCard rows={byExitReason} />
                </div>
                <TradesTable trades={trades} />
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
