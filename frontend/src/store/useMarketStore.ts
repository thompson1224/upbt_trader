import { create } from "zustand";
import { TickerData, SignalData } from "@/types/market";

interface MarketState {
  tickers: Record<string, TickerData>;
  selectedMarket: string;
  signals: SignalData[];
  isConnected: boolean | null;
  minConfidence: number;

  updateTicker: (data: TickerData) => void;
  setSelectedMarket: (market: string) => void;
  addSignal: (signal: SignalData) => void;
  setSignals: (signals: SignalData[]) => void;
  setConnected: (connected: boolean) => void;
  setMinConfidence: (value: number) => void;
}

export const useMarketStore = create<MarketState>((set) => ({
  tickers: {},
  selectedMarket: "KRW-BTC",
  signals: [],
  isConnected: null,
  minConfidence: 0.5,

  updateTicker: (data) =>
    set((state) => {
      const prev = state.tickers[data.code];
      // 가격·변화율이 동일하면 객체 참조를 유지해 불필요한 리렌더링 방지
      if (
        prev &&
        prev.tradePrice === data.tradePrice &&
        prev.changeRate === data.changeRate &&
        prev.change === data.change
      ) {
        return state;
      }
      return { tickers: { ...state.tickers, [data.code]: data } };
    }),

  setSelectedMarket: (market) => set({ selectedMarket: market }),

  addSignal: (signal) =>
    set((state) => ({
      signals: [signal, ...state.signals].slice(0, 100),
    })),

  setSignals: (signals) => set({ signals }),

  setConnected: (connected) => set({ isConnected: connected }),
  setMinConfidence: (value) => set({ minConfidence: value }),
}));
