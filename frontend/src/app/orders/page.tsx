"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/services/api";
import Sidebar from "@/components/layout/Sidebar";
import GlobalHeader from "@/components/layout/GlobalHeader";
import { cn } from "@/utils/cn";
import type { Order } from "@/types/market";

const STATES = ["전체", "done", "wait", "cancel"];
const SIDES = ["전체", "buy", "sell"];

export default function OrdersPage() {
  const [stateFilter, setStateFilter] = useState("전체");
  const [sideFilter, setSideFilter] = useState("전체");

  const { data: orders = [] } = useQuery<Order[]>({
    queryKey: ["orders", stateFilter],
    queryFn: () => api.orders.list(stateFilter === "전체" ? undefined : stateFilter),
    refetchInterval: 10_000,
  });

  const filtered = orders.filter(
    (o) => sideFilter === "전체" || o.side === sideFilter
  );

  return (
    <div className="h-screen flex overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <GlobalHeader />
        <main className="flex-1 overflow-auto p-6">
          <h1 className="text-lg font-bold mb-4">주문 내역</h1>

          <div className="flex gap-4 mb-4">
            <div className="flex gap-1">
              {STATES.map((s) => (
                <button
                  key={s}
                  onClick={() => setStateFilter(s)}
                  className={cn(
                    "px-3 py-1 text-xs rounded-lg border transition-colors",
                    stateFilter === s
                      ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/40"
                      : "bg-gray-800 text-gray-400 border-gray-700 hover:border-gray-600"
                  )}
                >
                  {s}
                </button>
              ))}
            </div>
            <div className="flex gap-1">
              {SIDES.map((s) => (
                <button
                  key={s}
                  onClick={() => setSideFilter(s)}
                  className={cn(
                    "px-3 py-1 text-xs rounded-lg border transition-colors",
                    sideFilter === s
                      ? "bg-blue-500/20 text-blue-400 border-blue-500/40"
                      : "bg-gray-800 text-gray-400 border-gray-700 hover:border-gray-600"
                  )}
                >
                  {s === "buy" ? "매수" : s === "sell" ? "매도" : s}
                </button>
              ))}
            </div>
          </div>

          <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-800 text-gray-500">
                  <th className="px-4 py-2.5 text-left font-medium">시간</th>
                  <th className="px-4 py-2.5 text-left font-medium">마켓</th>
                  <th className="px-4 py-2.5 text-left font-medium">방향</th>
                  <th className="px-4 py-2.5 text-left font-medium">상태</th>
                  <th className="px-4 py-2.5 text-left font-medium">유형</th>
                  <th className="px-4 py-2.5 text-right font-medium">가격</th>
                  <th className="px-4 py-2.5 text-right font-medium">수량</th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-gray-600">
                      주문 내역 없음
                    </td>
                  </tr>
                ) : (
                  filtered.map((order) => (
                    <tr
                      key={order.id}
                      className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors"
                    >
                      <td className="px-4 py-2.5 text-gray-500 font-mono">
                        {order.ts
                          ? new Date(order.ts).toLocaleString("ko-KR", {
                              month: "2-digit",
                              day: "2-digit",
                              hour: "2-digit",
                              minute: "2-digit",
                            })
                          : "—"}
                      </td>
                      <td className="px-4 py-2.5 font-mono text-gray-300">{order.market}</td>
                      <td className="px-4 py-2.5">
                        <span
                          className={cn(
                            "px-1.5 py-0.5 rounded font-medium",
                            order.side === "buy"
                              ? "bg-emerald-500/20 text-emerald-400"
                              : "bg-red-500/20 text-red-400"
                          )}
                        >
                          {order.side === "buy" ? "매수" : "매도"}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-gray-500">{order.status}</td>
                      <td className="px-4 py-2.5 text-gray-500">{order.ordType}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-gray-300">
                        {order.price != null ? order.price.toLocaleString("ko-KR") : "시장가"}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-gray-300">
                        {order.volume.toFixed(6)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </main>
      </div>
    </div>
  );
}
