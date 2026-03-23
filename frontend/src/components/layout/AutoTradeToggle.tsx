"use client";
import { useState } from "react";
import { Power, AlertTriangle } from "lucide-react";
import { useTradeStore } from "@/store/useTradeStore";
import { api } from "@/services/api";
import { cn } from "@/utils/cn";

export default function AutoTradeToggle() {
  const { isAutoTrading, setAutoTrading } = useTradeStore();
  const [showConfirm, setShowConfirm] = useState(false);
  const [pending, setPending] = useState(false);

  const commit = async (enabled: boolean) => {
    setPending(true);
    setAutoTrading(enabled);
    try {
      await api.settings.setAutoTrade(enabled);
    } catch {
      setAutoTrading(!enabled);
    } finally {
      setPending(false);
      setShowConfirm(false);
    }
  };

  const handleClick = () => {
    if (isAutoTrading) {
      commit(false);
    } else {
      setShowConfirm(true);
    }
  };

  return (
    <>
      <button
        onClick={handleClick}
        disabled={pending}
        className={cn(
          "flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors disabled:opacity-50",
          isAutoTrading
            ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/30"
            : "bg-gray-800 text-gray-400 border-gray-700"
        )}
      >
        <Power className="w-3.5 h-3.5" />
        {isAutoTrading ? "자동매매 ON" : "자동매매 OFF"}
      </button>

      {showConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 w-80 shadow-xl">
            <div className="flex items-center gap-2 mb-3 text-amber-400">
              <AlertTriangle className="w-5 h-5" />
              <span className="font-semibold text-sm">자동매매 활성화</span>
            </div>
            <p className="text-sm text-gray-300 mb-5">
              자동매매를 활성화하면 AI 신호에 따라 실제 거래가 자동으로 실행됩니다.
              계속하시겠습니까?
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowConfirm(false)}
                className="px-4 py-2 text-sm text-gray-400 hover:text-gray-200 transition-colors"
              >
                취소
              </button>
              <button
                onClick={() => commit(true)}
                className="px-4 py-2 text-sm bg-emerald-600 hover:bg-emerald-500 rounded-lg font-medium transition-colors"
              >
                활성화
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
