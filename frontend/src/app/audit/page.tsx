"use client";

import { useMemo, useState } from "react";
import { Fragment } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/services/api";
import Sidebar from "@/components/layout/Sidebar";
import GlobalHeader from "@/components/layout/GlobalHeader";
import { cn } from "@/utils/cn";
import type { AuditEvent } from "@/types/market";

const LEVELS = ["전체", "info", "warning", "error"];
const SOURCES = ["전체", "settings", "execution"];

export default function AuditPage() {
  const [levelFilter, setLevelFilter] = useState("전체");
  const [sourceFilter, setSourceFilter] = useState("전체");
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const { data: events = [] } = useQuery<AuditEvent[]>({
    queryKey: ["audit-events", sourceFilter],
    queryFn: () =>
      api.audit.list({
        source: sourceFilter === "전체" ? undefined : sourceFilter,
        limit: 100,
      }),
    refetchInterval: 10_000,
  });

  const filtered = useMemo(
    () => events.filter((event) => levelFilter === "전체" || event.level === levelFilter),
    [events, levelFilter]
  );

  return (
    <div className="h-screen flex overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <GlobalHeader />
        <main className="flex-1 overflow-auto p-6">
          <div className="flex items-center justify-between mb-4 gap-4">
            <div>
              <h1 className="text-lg font-bold">감사 로그</h1>
              <p className="text-xs text-gray-500 mt-1">
                설정 변경, 주문 체결, 리스크 거절 같은 운영 이벤트를 시간순으로 확인합니다.
              </p>
            </div>
            <div className="text-xs text-gray-500">
              최근 {filtered.length}건
            </div>
          </div>

          <div className="flex gap-4 mb-4 flex-wrap">
            <div className="flex gap-1">
              {SOURCES.map((source) => (
                <button
                  key={source}
                  onClick={() => setSourceFilter(source)}
                  className={cn(
                    "px-3 py-1 text-xs rounded-lg border transition-colors",
                    sourceFilter === source
                      ? "bg-blue-500/20 text-blue-400 border-blue-500/40"
                      : "bg-gray-800 text-gray-400 border-gray-700 hover:border-gray-600"
                  )}
                >
                  {source}
                </button>
              ))}
            </div>
            <div className="flex gap-1">
              {LEVELS.map((level) => (
                <button
                  key={level}
                  onClick={() => setLevelFilter(level)}
                  className={cn(
                    "px-3 py-1 text-xs rounded-lg border transition-colors",
                    levelFilter === level
                      ? "bg-amber-500/20 text-amber-400 border-amber-500/40"
                      : "bg-gray-800 text-gray-400 border-gray-700 hover:border-gray-600"
                  )}
                >
                  {level}
                </button>
              ))}
            </div>
          </div>

          <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-800 text-gray-500">
                  <th className="px-4 py-2.5 text-left font-medium">시간</th>
                  <th className="px-4 py-2.5 text-left font-medium">레벨</th>
                  <th className="px-4 py-2.5 text-left font-medium">소스</th>
                  <th className="px-4 py-2.5 text-left font-medium">이벤트</th>
                  <th className="px-4 py-2.5 text-left font-medium">마켓</th>
                  <th className="px-4 py-2.5 text-left font-medium">메시지</th>
                  <th className="px-4 py-2.5 text-right font-medium">상세</th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-gray-600">
                      감사 로그 없음
                    </td>
                  </tr>
                ) : (
                  filtered.map((event) => {
                    const expanded = expandedId === event.id;
                    return (
                      <Fragment key={event.id}>
                        <tr
                          className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors"
                        >
                          <td className="px-4 py-2.5 text-gray-500 font-mono">
                            {new Date(event.ts).toLocaleString("ko-KR", {
                              month: "2-digit",
                              day: "2-digit",
                              hour: "2-digit",
                              minute: "2-digit",
                              second: "2-digit",
                            })}
                          </td>
                          <td className="px-4 py-2.5">
                            <span
                              className={cn(
                                "px-1.5 py-0.5 rounded font-medium uppercase",
                                event.level === "error" && "bg-red-500/20 text-red-400",
                                event.level === "warning" && "bg-amber-500/20 text-amber-400",
                                event.level === "info" && "bg-blue-500/20 text-blue-400",
                                !["error", "warning", "info"].includes(event.level) &&
                                  "bg-gray-700 text-gray-300"
                              )}
                            >
                              {event.level}
                            </span>
                          </td>
                          <td className="px-4 py-2.5 text-gray-400">{event.source}</td>
                          <td className="px-4 py-2.5 font-mono text-gray-300">{event.eventType}</td>
                          <td className="px-4 py-2.5 font-mono text-gray-400">{event.market ?? "—"}</td>
                          <td className="px-4 py-2.5 text-gray-300">{event.message}</td>
                          <td className="px-4 py-2.5 text-right">
                            <button
                              onClick={() => setExpandedId(expanded ? null : event.id)}
                              className="text-gray-400 hover:text-gray-200 transition-colors"
                            >
                              {expanded ? "닫기" : "보기"}
                            </button>
                          </td>
                        </tr>
                        {expanded && (
                          <tr className="border-b border-gray-800/50 bg-gray-950/60">
                            <td colSpan={7} className="px-4 py-3">
                              <pre className="text-[11px] leading-5 text-gray-300 overflow-x-auto whitespace-pre-wrap break-all">
                                {event.payload ? JSON.stringify(event.payload, null, 2) : "payload 없음"}
                              </pre>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </main>
      </div>
    </div>
  );
}
