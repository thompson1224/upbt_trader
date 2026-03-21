import { create } from "zustand";
import { Position } from "@/types/market";

interface TradeState {
  positions: Position[];
  totalEquity: number;
  availableKrw: number;
  dailyPnl: number;
  isAutoTrading: boolean;

  setPositions: (positions: Position[]) => void;
  setEquity: (equity: number, available: number) => void;
  setDailyPnl: (pnl: number) => void;
  toggleAutoTrading: () => void;
}

export const useTradeStore = create<TradeState>((set) => ({
  positions: [],
  totalEquity: 0,
  availableKrw: 0,
  dailyPnl: 0,
  isAutoTrading: false,

  setPositions: (positions) => set({ positions }),
  setEquity: (equity, available) =>
    set({ totalEquity: equity, availableKrw: available }),
  setDailyPnl: (pnl) => set({ dailyPnl: pnl }),
  toggleAutoTrading: () =>
    set((state) => ({ isAutoTrading: !state.isAutoTrading })),
}));
