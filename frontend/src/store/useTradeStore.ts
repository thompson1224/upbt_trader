import { create } from "zustand";
import { EquityCurvePoint, Position } from "@/types/market";

interface TradeState {
  positions: Position[];
  equityCurve: EquityCurvePoint[];
  totalEquity: number;
  availableKrw: number;
  dailyPnl: number;
  isAutoTrading: boolean;

  setPositions: (positions: Position[]) => void;
  setEquityCurve: (points: EquityCurvePoint[]) => void;
  addEquityPoint: (point: EquityCurvePoint) => void;
  setEquity: (equity: number, available: number) => void;
  setDailyPnl: (pnl: number) => void;
  setAutoTrading: (enabled: boolean) => void;
}

export const useTradeStore = create<TradeState>((set) => ({
  positions: [],
  equityCurve: [],
  totalEquity: 0,
  availableKrw: 0,
  dailyPnl: 0,
  isAutoTrading: false,

  setPositions: (positions) => set({ positions }),
  setEquityCurve: (points) => set({ equityCurve: points.slice(-500) }),
  addEquityPoint: (point) =>
    set((state) => {
      const lastPoint = state.equityCurve[state.equityCurve.length - 1];
      if (lastPoint?.ts === point.ts) {
        return {
          equityCurve: [...state.equityCurve.slice(0, -1), point].slice(-500),
        };
      }
      return {
        equityCurve: [...state.equityCurve, point].slice(-500),
      };
    }),
  setEquity: (equity, available) =>
    set({ totalEquity: equity, availableKrw: available }),
  setDailyPnl: (pnl) => set({ dailyPnl: pnl }),
  setAutoTrading: (enabled) => set({ isAutoTrading: enabled }),
}));
