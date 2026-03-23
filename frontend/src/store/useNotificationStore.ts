import { create } from "zustand";

export type NotificationType =
  | "order_placed"
  | "order_filled"
  | "sl_triggered"
  | "tp_triggered"
  | "risk_rejected"
  | "error";

export interface Toast {
  id: string;
  type: NotificationType;
  title: string;
  message: string;
  ts: number;
}

interface NotificationState {
  toasts: Toast[];
  push: (n: Omit<Toast, "id" | "ts">) => void;
  dismiss: (id: string) => void;
}

export const useNotificationStore = create<NotificationState>((set) => ({
  toasts: [],
  push: (n) =>
    set((state) => ({
      toasts: [
        ...state.toasts,
        { ...n, id: crypto.randomUUID(), ts: Date.now() },
      ].slice(-5),
    })),
  dismiss: (id) =>
    set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),
}));
