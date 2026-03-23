export interface TickerData {
  code: string;          // KRW-BTC
  tradePrice: number;    // 현재가
  change: "RISE" | "FALL" | "EVEN";
  changeRate: number;    // 변동률
  changePrice: number;   // 변동가
  accTradeVolume24h: number;
  accTradePrice24h: number;
  high52WeekPrice: number;
  low52WeekPrice: number;
  timestamp: number;
}

export interface CandleData {
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  value: number;
}

export interface SignalData {
  id: number;
  strategyId: string;
  coinId: number;
  market: string;
  timeframe: string;
  ts: string;
  taScore: number;
  sentimentScore: number | null;
  finalScore: number;
  confidence: number;
  side: "buy" | "sell" | "hold";
  status: string;
  suggestedStopLoss: number | null;
  suggestedTakeProfit: number | null;
}

export interface Position {
  id: number;
  market: string;
  qty: number;
  avgEntryPrice: number;
  unrealizedPnl: number;
  realizedPnl: number;
  stopLoss: number | null;
  takeProfit: number | null;
}

export interface Order {
  id: number;
  market: string;
  side: "buy" | "sell";
  status: string;
  ordType: string;
  price: number | null;
  volume: number;
  ts: string | null;
}

export interface BacktestMetrics {
  cagr: number;
  sharpe: number;
  maxDrawdown: number;
  winRate: number;
  profitFactor: number;
  totalTrades: number;
}
