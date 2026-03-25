from typing import Optional
from pydantic import BaseModel
from datetime import datetime


class SignalResponse(BaseModel):
    id: int
    strategy_id: str
    coin_id: int
    market: Optional[str] = None
    timeframe: str
    ts: datetime
    ta_score: float
    sentiment_score: Optional[float]
    final_score: float
    confidence: float
    side: str
    status: str
    suggested_stop_loss: Optional[float]
    suggested_take_profit: Optional[float]
    rejection_reason: Optional[str] = None

    model_config = {"from_attributes": True}
