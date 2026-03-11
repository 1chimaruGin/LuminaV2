from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class BotCreate(BaseModel):
    name: str
    bot_type: str  # "trading", "grid", "dca", "sniper", "arbitrage", "algo"
    pair: str
    exchange: str = "binance"
    investment: float = 0.0
    config: dict = {}


class BotUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None  # "running", "paused", "stopped"
    config: Optional[dict] = None


class BotResponse(BaseModel):
    id: int
    name: str
    bot_type: str
    pair: str
    exchange: str
    status: str
    investment: float
    profit: float
    profit_pct: float
    trades_count: int
    win_rate: float
    config: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BotListResponse(BaseModel):
    data: list[BotResponse]
    total: int
    running_count: int
    total_profit: float
