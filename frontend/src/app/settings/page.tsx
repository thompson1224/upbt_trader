"use client";
import { useEffect, useState } from "react";
import { api } from "@/services/api";
import { Key, Zap, Eye, EyeOff, CheckCircle, AlertCircle, ShieldAlert } from "lucide-react";
import Sidebar from "@/components/layout/Sidebar";
import GlobalHeader from "@/components/layout/GlobalHeader";

export default function SettingsPage() {
  const [upbitAccess, setUpbitAccess] = useState("");
  const [upbitSecret, setUpbitSecret] = useState("");
  const [groqKey, setGroqKey] = useState("");
  const [showSecrets, setShowSecrets] = useState(false);
  const [status, setStatus] = useState<"idle" | "saving" | "success" | "error">("idle");
  const [externalStopLossEnabled, setExternalStopLossEnabled] = useState(false);
  const [loadingProtection, setLoadingProtection] = useState(true);

  useEffect(() => {
    api.settings
      .getExternalPositionStopLoss()
      .then(({ enabled }) => setExternalStopLossEnabled(enabled))
      .finally(() => setLoadingProtection(false));
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
      setStatus("success");
      setTimeout(() => setStatus("idle"), 3000);
    } catch {
      setStatus("error");
      setTimeout(() => setStatus("idle"), 3000);
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
