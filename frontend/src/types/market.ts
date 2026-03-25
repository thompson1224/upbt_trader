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
  source: "strategy" | "external";
  stopLoss: number | null;
  takeProfit: number | null;
}

export interface EquityCurvePoint {
  ts: string;
  equity: number;
  availableKrw?: number;
  positionValue?: number;
  dailyPnl?: number;
  openPositions?: number;
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

export interface AuditEvent {
  id: number;
  eventType: string;
  source: string;
  level: "info" | "warning" | "error" | string;
  market: string | null;
  message: string;
  payload: Record<string, unknown> | null;
  ts: string;
}

export interface BacktestMetrics {
  cagr: number;
  sharpe: number;
  maxDrawdown: number;
  winRate: number;
  profitFactor: number;
  totalTrades: number;
}

export interface PerformanceSummary {
  totalTrades: number;
  winRate: number;
  grossPnl: number;
  netPnl: number;
  avgNetPnl: number;
  avgWin: number;
  avgLoss: number;
  profitFactor: number;
  maxDrawdown: number;
  bestTrade: number;
  worstTrade: number;
}

export interface PerformanceBreakdownRow {
  market?: string;
  exitReason?: string;
  scoreBand?: string;
  sentimentBand?: string;
  hourBlock?: string;
  trades: number;
  winRate: number;
  netPnl: number;
}

export interface PerformanceTrade {
  market: string;
  entryTs: string;
  exitTs: string;
  entryPrice: number;
  exitPrice: number;
  qty: number;
  entryFee: number;
  exitFee: number;
  grossPnl: number;
  netPnl: number;
  returnPct: number;
  holdMinutes: number;
  exitReason: string;
  strategyId: string | null;
  taScore: number | null;
  sentimentScore: number | null;
  finalScore: number | null;
  confidence: number | null;
}

export interface PerformanceResponse {
  summary: PerformanceSummary;
  byMarket: PerformanceBreakdownRow[];
  byExitReason: PerformanceBreakdownRow[];
  byFinalScoreBand: PerformanceBreakdownRow[];
  bySentimentBand: PerformanceBreakdownRow[];
  byHourBlock: PerformanceBreakdownRow[];
  trades: PerformanceTrade[];
}
