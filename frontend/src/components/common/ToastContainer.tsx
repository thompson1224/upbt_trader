"use client";
import { useEffect } from "react";
import { useNotificationStore, Toast, NotificationType } from "@/store/useNotificationStore";
import { cn } from "@/utils/cn";
import { CheckCircle, XCircle, AlertTriangle, X } from "lucide-react";

const TYPE_STYLES: Record<NotificationType, string> = {
  order_filled: "border-emerald-500/40 bg-emerald-500/10",
  order_placed: "border-blue-500/40 bg-blue-500/10",
  sl_triggered: "border-amber-500/40 bg-amber-500/10",
  tp_triggered: "border-emerald-500/40 bg-emerald-500/10",
  risk_rejected: "border-red-500/40 bg-red-500/10",
  error: "border-red-500/40 bg-red-500/10",
};

function ToastIcon({ type }: { type: NotificationType }) {
  if (type === "order_filled" || type === "tp_triggered") {
    return <CheckCircle className="w-4 h-4 text-emerald-400 shrink-0" />;
  }
  if (type === "risk_rejected" || type === "error") {
    return <XCircle className="w-4 h-4 text-red-400 shrink-0" />;
  }
  return <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />;
}

function ToastItem({ toast }: { toast: Toast }) {
  const dismiss = useNotificationStore((s) => s.dismiss);

  useEffect(() => {
    const timer = setTimeout(() => dismiss(toast.id), 5000);
    return () => clearTimeout(timer);
  }, [toast.id, dismiss]);

  return (
    <div
      className={cn(
        "flex items-start gap-3 px-4 py-3 rounded-xl border shadow-lg w-72",
        TYPE_STYLES[toast.type]
      )}
    >
      <ToastIcon type={toast.type} />
      <div className="flex-1 min-w-0">
        <p className="text-xs font-semibold text-gray-200">{toast.title}</p>
        <p className="text-xs text-gray-400 mt-0.5 truncate">{toast.message}</p>
      </div>
      <button
        onClick={() => dismiss(toast.id)}
        className="text-gray-600 hover:text-gray-400 transition-colors shrink-0"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}

export default function ToastContainer() {
  const toasts = useNotificationStore((s) => s.toasts);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-2">
      {toasts.map((toast) => (
        <ToastItem key={toast.id} toast={toast} />
      ))}
    </div>
  );
}
