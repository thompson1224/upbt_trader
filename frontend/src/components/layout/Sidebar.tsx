"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  BarChart2,
  BrainCircuit,
  TrendingUp,
  Settings,
  Activity,
  ClipboardList,
  ShieldCheck,
} from "lucide-react";
import { useMarketStore } from "@/store/useMarketStore";
import { cn } from "@/utils/cn";

const NAV_ITEMS = [
  { href: "/", icon: LayoutDashboard, label: "대시보드" },
  { href: "/market", icon: TrendingUp, label: "마켓" },
  { href: "/orders", icon: ClipboardList, label: "주문내역" },
  { href: "/audit", icon: ShieldCheck, label: "감사로그" },
  { href: "/backtest", icon: BarChart2, label: "백테스팅" },
  { href: "/ai-analysis", icon: BrainCircuit, label: "AI 분석" },
  { href: "/settings", icon: Settings, label: "설정" },
];

export default function Sidebar() {
  const pathname = usePathname();
  const isConnected = useMarketStore((s) => s.isConnected);

  return (
    <aside className="w-16 md:w-56 bg-gray-900 border-r border-gray-800 flex flex-col h-full shrink-0">
      {/* 로고 */}
      <div className="h-14 flex items-center px-4 border-b border-gray-800">
        <span className="hidden md:block text-sm font-bold text-emerald-400">
          Upbit AI Trader
        </span>
        <Activity className="w-5 h-5 text-emerald-400 md:hidden" />
      </div>

      {/* 네비게이션 */}
      <nav className="flex-1 py-4 space-y-1 px-2">
        {NAV_ITEMS.map(({ href, icon: Icon, label }) => (
          <Link
            key={href}
            href={href}
            className={cn(
              "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors",
              pathname === href
                ? "bg-emerald-500/10 text-emerald-400"
                : "text-gray-400 hover:text-gray-200 hover:bg-gray-800"
            )}
          >
            <Icon className="w-5 h-5 shrink-0" />
            <span className="hidden md:block">{label}</span>
          </Link>
        ))}
      </nav>

      {/* 연결 상태 */}
      <div className="p-4 border-t border-gray-800">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "w-2 h-2 rounded-full",
              isConnected ? "bg-emerald-400 animate-pulse" : "bg-red-500"
            )}
          />
          <span className="hidden md:block text-xs text-gray-500">
            {isConnected ? "실시간 연결됨" : "연결 끊김"}
          </span>
        </div>
      </div>
    </aside>
  );
}
