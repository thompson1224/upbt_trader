from typing import Optional
from pydantic import BaseModel
from datetime import datetime


class CoinResponse(BaseModel):
    id: int
    market: str
    base_currency: str
    quote_currency: str
    is_active: bool
    market_warning: Optional[str]

    model_config = {"from_attributes": True}


class CandleResponse(BaseModel):
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    value: float

    model_config = {"from_attributes": True}
