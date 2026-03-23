"use client";
import { useMarketStore } from "@/store/useMarketStore";

export default function ConfidenceFilter() {
  const minConfidence = useMarketStore((s) => s.minConfidence);
  const setMinConfidence = useMarketStore((s) => s.setMinConfidence);

  return (
    <div className="flex items-center gap-2 px-4 py-2 border-b border-gray-800">
      <span className="text-xs text-gray-500 shrink-0">신뢰도 ≥</span>
      <input
        type="range"
        min={0}
        max={100}
        step={5}
        value={Math.round(minConfidence * 100)}
        onChange={(e) => setMinConfidence(Number(e.target.value) / 100)}
        className="flex-1 accent-emerald-500"
      />
      <span className="text-xs font-mono text-gray-300 w-8 text-right shrink-0">
        {Math.round(minConfidence * 100)}%
      </span>
    </div>
  );
}
