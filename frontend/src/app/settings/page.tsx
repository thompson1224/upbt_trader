"use client";
import { useEffect, useState } from "react";
import { api } from "@/services/api";
import { Key, Zap, Eye, EyeOff, CheckCircle, AlertCircle, ShieldAlert, RotateCcw } from "lucide-react";
import Sidebar from "@/components/layout/Sidebar";
import GlobalHeader from "@/components/layout/GlobalHeader";

export default function SettingsPage() {
  const [upbitAccess, setUpbitAccess] = useState("");
  const [upbitSecret, setUpbitSecret] = useState("");
  const [groqKey, setGroqKey] = useState("");
  const [showSecrets, setShowSecrets] = useState(false);
  const [status, setStatus] = useState<"idle" | "saving" | "success" | "error">("idle");
  const [externalStopLossEnabled, setExternalStopLossEnabled] = useState(false);
  const [minBuyFinalScore, setMinBuyFinalScore] = useState("0.00");
  const [loadingProtection, setLoadingProtection] = useState(true);
  const [resettingLossStreak, setResettingLossStreak] = useState(false);
  const [lossStreakResetStatus, setLossStreakResetStatus] = useState<"idle" | "success" | "error">("idle");

  useEffect(() => {
    api.settings
      .getExternalPositionStopLoss()
      .then(({ enabled }) => setExternalStopLossEnabled(enabled))
      .finally(() => setLoadingProtection(false));
    api.settings
      .getMinBuyFinalScore()
      .then(({ value }) => setMinBuyFinalScore(value.toFixed(2)));
  }, []);

  const handleSave = async () => {
    setStatus("saving");
    try {
      if (upbitAccess && upbitSecret) {
        await api.settings.setUpbitKeys(upbitAccess, upbitSecret);
      }
      if (groqKey) {
        await api.settings.setGroqKey(groqKey);
      }
      await api.settings.setExternalPositionStopLoss(externalStopLossEnabled);
      await api.settings.setMinBuyFinalScore(Number(minBuyFinalScore) || 0);
      setStatus("success");
      setTimeout(() => setStatus("idle"), 3000);
    } catch {
      setStatus("error");
      setTimeout(() => setStatus("idle"), 3000);
    }
  };

  const handleResetLossStreak = async () => {
    setResettingLossStreak(true);
    setLossStreakResetStatus("idle");
    try {
      await api.settings.resetLossStreak();
      setLossStreakResetStatus("success");
      setTimeout(() => setLossStreakResetStatus("idle"), 3000);
    } catch {
      setLossStreakResetStatus("error");
      setTimeout(() => setLossStreakResetStatus("idle"), 3000);
    } finally {
      setResettingLossStreak(false);
    }
  };

  return (
    <div className="h-screen flex overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <GlobalHeader />
        <main className="flex-1 overflow-auto p-6 max-w-2xl">
          <h1 className="text-lg font-bold mb-6">설정</h1>

          <section className="bg-gray-900 rounded-xl border border-gray-800 p-6 mb-4">
            <div className="flex items-center gap-2 mb-4">
              <Key className="w-4 h-4 text-emerald-400" />
              <h2 className="font-semibold text-sm">업비트 API 키</h2>
            </div>

            <div className="space-y-3">
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Access Key</label>
                <input
                  type={showSecrets ? "text" : "password"}
                  value={upbitAccess}
                  onChange={(e) => setUpbitAccess(e.target.value)}
                  placeholder="업비트 Access Key"
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-emerald-500 font-mono"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Secret Key</label>
                <input
                  type={showSecrets ? "text" : "password"}
                  value={upbitSecret}
                  onChange={(e) => setUpbitSecret(e.target.value)}
                  placeholder="업비트 Secret Key"
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-emerald-500 font-mono"
                />
              </div>
            </div>
          </section>

          <section className="bg-gray-900 rounded-xl border border-gray-800 p-6 mb-6">
            <div className="flex items-center gap-2 mb-4">
              <ShieldAlert className="w-4 h-4 text-sky-400" />
              <h2 className="font-semibold text-sm">최소 매수 Final Score</h2>
            </div>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Final Score Threshold</label>
                <input
                  type="number"
                  min="0"
                  max="1"
                  step="0.01"
                  value={minBuyFinalScore}
                  onChange={(e) => setMinBuyFinalScore(e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-sky-500 font-mono"
                />
              </div>
              <p className="text-xs text-gray-600">
                `buy` 신호의 `final score`가 이 값보다 낮으면 주문 전에 거절합니다. `0.00`은 비활성, 시작 추천값은 `0.60`입니다.
              </p>
            </div>
          </section>

          <section className="bg-gray-900 rounded-xl border border-gray-800 p-6 mb-6">
            <div className="flex items-center gap-2 mb-4">
              <Zap className="w-4 h-4 text-orange-400" />
              <h2 className="font-semibold text-sm">Groq API 키</h2>
            </div>
            <input
              type={showSecrets ? "text" : "password"}
              value={groqKey}
              onChange={(e) => setGroqKey(e.target.value)}
              placeholder="gsk_..."
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-orange-500 font-mono"
            />
            <p className="text-xs text-gray-600 mt-2">
              console.groq.com에서 무료 발급 — llama-3.1-8b-instant 모델 (14,400 req/day 무료)
            </p>
          </section>

          <section className="bg-gray-900 rounded-xl border border-gray-800 p-6 mb-6">
            <div className="flex items-center gap-2 mb-4">
              <ShieldAlert className="w-4 h-4 text-amber-400" />
              <h2 className="font-semibold text-sm">외부 보유분 자동 손절</h2>
            </div>
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-sm text-gray-300">
                  전략이 직접 연 포지션이 아닌, 계좌에 이미 있던 코인에 기본 손절을 적용합니다.
                </p>
                <p className="text-xs text-gray-600 mt-2">
                  기본값은 OFF입니다. 외부 보유분에는 자동 익절은 적용하지 않고, ON일 때만 기본 손절만 허용합니다.
                </p>
              </div>
              <button
                type="button"
                disabled={loadingProtection}
                onClick={() => setExternalStopLossEnabled((v) => !v)}
                className={`relative inline-flex h-7 w-12 items-center rounded-full transition-colors ${
                  externalStopLossEnabled ? "bg-amber-500" : "bg-gray-700"
                } ${loadingProtection ? "opacity-50" : ""}`}
              >
                <span
                  className={`inline-block h-5 w-5 transform rounded-full bg-white transition-transform ${
                    externalStopLossEnabled ? "translate-x-6" : "translate-x-1"
                  }`}
                />
              </button>
            </div>
          </section>

          <section className="bg-gray-900 rounded-xl border border-gray-800 p-6 mb-6">
            <div className="flex items-center gap-2 mb-4">
              <RotateCcw className="w-4 h-4 text-sky-400" />
              <h2 className="font-semibold text-sm">연속 손실 복구</h2>
            </div>
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-sm text-gray-300">
                  연속 손실 제한에 걸려 신규 진입이 막힌 상태를 운영자가 즉시 해제합니다.
                </p>
                <p className="text-xs text-gray-600 mt-2">
                  KST 날짜 변경 시 자동으로 초기화되지만, 지금 바로 복구가 필요하면 이 버튼을 사용합니다.
                </p>
              </div>
              <button
                type="button"
                onClick={handleResetLossStreak}
                disabled={resettingLossStreak}
                className="inline-flex items-center gap-2 rounded-lg bg-sky-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-sky-500 disabled:opacity-50"
              >
                <RotateCcw className="h-4 w-4" />
                {resettingLossStreak ? "복구 중..." : "연속 손실 초기화"}
              </button>
            </div>
            {lossStreakResetStatus === "success" && (
              <div className="mt-3 flex items-center gap-1 text-sm text-emerald-400">
                <CheckCircle className="h-4 w-4" />
                연속 손실 카운트가 초기화됐습니다.
              </div>
            )}
            {lossStreakResetStatus === "error" && (
              <div className="mt-3 flex items-center gap-1 text-sm text-red-400">
                <AlertCircle className="h-4 w-4" />
                연속 손실 초기화에 실패했습니다.
              </div>
            )}
          </section>

          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowSecrets((s) => !s)}
              className="flex items-center gap-2 text-sm text-gray-500 hover:text-gray-300 transition-colors"
            >
              {showSecrets ? (
                <EyeOff className="w-4 h-4" />
              ) : (
                <Eye className="w-4 h-4" />
              )}
              {showSecrets ? "숨기기" : "보기"}
            </button>

            <button
              onClick={handleSave}
              disabled={status === "saving"}
              className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
            >
              {status === "saving" ? "저장 중..." : "저장"}
            </button>

            {status === "success" && (
              <div className="flex items-center gap-1 text-emerald-400 text-sm">
                <CheckCircle className="w-4 h-4" />
                저장됨
              </div>
            )}
            {status === "error" && (
              <div className="flex items-center gap-1 text-red-400 text-sm">
                <AlertCircle className="w-4 h-4" />
                저장 실패
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
