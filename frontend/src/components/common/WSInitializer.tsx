"use client";
import { useUpbitMarketWS, useSignalWS } from "@/hooks/useUpbitWS";

const DEFAULT_CODES = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-ADA"];

export default function WSInitializer() {
  useUpbitMarketWS(DEFAULT_CODES);
  useSignalWS();
  return null;
}
