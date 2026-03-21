"use client";
import { useState } from "react";
import { api } from "@/services/api";
import { Key, Eye, EyeOff, CheckCircle, AlertCircle } from "lucide-react";
import Sidebar from "@/components/layout/Sidebar";
import GlobalHeader from "@/components/layout/GlobalHeader";

export default function SettingsPage() {
  const [upbitAccess, setUpbitAccess] = useState("");
  const [upbitSecret, setUpbitSecret] = useState("");
  const [claudeKey, setClaudeKey] = useState("");
  const [showSecrets, setShowSecrets] = useState(false);
  const [status, setStatus] = useState<"idle" | "saving" | "success" | "error">("idle");

  const handleSave = async () => {
    setStatus("saving");
    try {
      if (upbitAccess && upbitSecret) {
        await api.settings.setUpbitKeys(upbitAccess, upbitSecret);
      }
      if (claudeKey) {
        await api.settings.setClaudeKey(claudeKey);
      }
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
                <div className="relative">
                  <input
                    type={showSecrets ? "text" : "password"}
                    value={upbitAccess}
                    onChange={(e) => setUpbitAccess(e.target.value)}
                    placeholder="업비트 Access Key"
                    className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-emerald-500 font-mono"
                  />
                </div>
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
              <Key className="w-4 h-4 text-purple-400" />
              <h2 className="font-semibold text-sm">Claude API 키</h2>
            </div>
            <input
              type={showSecrets ? "text" : "password"}
              value={claudeKey}
              onChange={(e) => setClaudeKey(e.target.value)}
              placeholder="sk-ant-..."
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-purple-500 font-mono"
            />
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
