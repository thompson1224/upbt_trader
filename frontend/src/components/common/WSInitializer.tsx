"use client";
import { usePortfolioWS, useSignalWS, useTradeEventWS, useUpbitMarketWS } from "@/hooks/useUpbitWS";

const DEFAULT_CODES = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-ADA"];

export default function WSInitializer() {
  useUpbitMarketWS(DEFAULT_CODES);
  useSignalWS();
  useTradeEventWS();
  usePortfolioWS();
  return null;
}
