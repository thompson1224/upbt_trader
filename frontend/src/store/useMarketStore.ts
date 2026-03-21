import { create } from "zustand";
import { TickerData, SignalData } from "@/types/market";

interface MarketState {
  tickers: Record<string, TickerData>;
  selectedMarket: string;
  signals: SignalData[];
  isConnected: boolean;

  updateTicker: (data: TickerData) => void;
  setSelectedMarket: (market: string) => void;
  addSignal: (signal: SignalData) => void;
  setConnected: (connected: boolean) => void;
}

export const useMarketStore = create<MarketState>((set) => ({
  tickers: {},
  selectedMarket: "KRW-BTC",
  signals: [],
  isConnected: false,

  updateTicker: (data) =>
    set((state) => ({
      tickers: { ...state.tickers, [data.code]: data },
    })),

  setSelectedMarket: (market) => set({ selectedMarket: market }),

  addSignal: (signal) =>
    set((state) => ({
      signals: [signal, ...state.signals].slice(0, 100), // 최대 100개 유지
    })),

  setConnected: (connected) => set({ isConnected: connected }),
}));
