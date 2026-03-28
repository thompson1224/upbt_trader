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

export interface MarketInfo {
  id: number;
  market: string;
  base_currency: string;
  quote_currency: string;
  is_active: boolean;
  market_warning: string | null;
  excluded: boolean;
  excluded_reason: string | null;
}

export interface ExcludedMarketItem {
  market: string;
  reason: string;
  updated_at: string;
}

export interface ExcludedMarketState {
  markets: string[];
  items: ExcludedMarketItem[];
}

export interface TransitionRecommendationSettings {
  min_hold_origin_count: number;
  exclude_max_hold_to_sell_rate: number;
  exclude_min_hold_to_hold_rate: number;
  restore_min_hold_to_sell_rate: number;
  restore_max_hold_to_hold_rate: number;
}

export type KstHourBlock = "00-04" | "04-08" | "08-12" | "12-16" | "16-20" | "20-24";

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
  rejectionReason: string | null;
  displayReason: string | null;
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
  currentPrice: number | null;
  distanceToStopLossPct: number | null;
  distanceToTakeProfitPct: number | null;
  autoTradeManaged: boolean;
  latestSignal: {
    id: number;
    strategyId: string;
    ts: string;
    side: "buy" | "sell" | "hold";
    status: string;
    finalScore: number;
    confidence: number;
    rejectionReason: string | null;
    displayReason: string | null;
  } | null;
  latestSellSignal: {
    id: number;
    strategyId: string;
    ts: string;
    side: "sell";
    status: string;
    finalScore: number;
    confidence: number;
    rejectionReason: string | null;
    displayReason: string | null;
  } | null;
  sellWaitReasonCode: string;
  sellWaitReason: string;
  consecutiveHoldCount: number;
  holdDurationMinutes: number | null;
  holdStale: boolean;
  holdWarning: string | null;
  holdStaleThresholdMinutes: number;
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
  cagr: number | null;
  sharpe: number | null;
  maxDrawdown: number | null;
  winRate: number | null;
  profitFactor: number | null;
  totalTrades: number | null;
}

export interface BacktestRunSummary {
  id: number;
  market: string | null;
  strategyId: string;
  mode: "single" | "walk_forward" | string;
  status: "pending" | "running" | "completed" | "failed" | string;
  trainFrom: string;
  trainTo: string;
  testFrom: string;
  testTo: string;
  startedAt: string | null;
  finishedAt: string | null;
  errorMessage: string | null;
  initialEquity: number | null;
  stopLossPct: number | null;
  takeProfitPct: number | null;
  testWindowDays: number | null;
  stepDays: number | null;
}

export interface BacktestTradeRow {
  id: number;
  market: string;
  entryTs: string;
  exitTs: string | null;
  entryPrice: number;
  exitPrice: number | null;
  qty: number;
  pnl: number;
  fee: number;
  returnPct: number;
  holdMinutes: number;
}

export interface BacktestWindowRow {
  id: number;
  windowSeq: number;
  trainFrom: string;
  trainTo: string;
  testFrom: string;
  testTo: string;
  startEquity: number;
  endEquity: number;
  netPnl: number;
  cagr: number | null;
  sharpe: number | null;
  maxDrawdown: number | null;
  winRate: number | null;
  profitFactor: number | null;
  totalTrades: number | null;
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

export interface SignalTransitionRow {
  transition: string;
  count: number;
  share: number;
  avgGapMinutes: number;
}

export interface MarketTransitionQualityRow {
  market: string;
  totalTransitions: number;
  holdOriginCount: number;
  holdToSellCount: number;
  holdToHoldCount: number;
  holdToBuyCount: number;
  holdToSellRate: number;
  holdToHoldRate: number;
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
  byTransition: SignalTransitionRow[];
  byMarketTransitionQuality: MarketTransitionQualityRow[];
  trades: PerformanceTrade[];
}

export interface DailyReportPosition {
  market: string;
  source: "strategy" | "external";
  qty: number;
  avgEntryPrice: number;
  unrealizedPnl: number;
  realizedPnl: number;
  excluded: boolean;
  excludedReason: string;
}

export interface DailyReportSummary {
  dailyPnl: number;
  lossStreak: number;
  closedTrades: number;
  wins: number;
  losses: number;
  netPnl: number;
  openPositions: number;
  excludedMarkets: number;
  riskRejectedCount: number;
  orderFailedCount: number;
  excludedOpsCount: number;
}

export interface DailyReportResponse {
  date: string;
  summary: DailyReportSummary;
  byExitReason: PerformanceBreakdownRow[];
  analysis: {
    byFinalScoreBand: PerformanceBreakdownRow[];
    byHourBlock: PerformanceBreakdownRow[];
    weakMarkets: PerformanceBreakdownRow[];
    riskRejectedReasons: Array<{
      reason: string;
      count: number;
    }>;
  };
  positions: DailyReportPosition[];
  recentAuditCounts: {
    riskRejected: number;
    orderFailed: number;
    excludedOps: number;
  };
}
