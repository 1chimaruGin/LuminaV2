from datetime import datetime
from typing import Optional

from pydantic import BaseModel


# ── Ticker ──
class TickerResponse(BaseModel):
    symbol: str
    base: str
    quote: str
    price: float
    price_change_24h: float
    volume_24h: float
    high_24h: float
    low_24h: float
    market_cap: Optional[float] = None
    exchange: str
    timestamp: datetime

    model_config = {"from_attributes": True}


class TickerListResponse(BaseModel):
    data: list[TickerResponse]
    total: int
    exchange: Optional[str] = None


# ── Funding Rate ──
class FundingRateResponse(BaseModel):
    symbol: str
    exchange: str
    rate: float
    predicted_rate: Optional[float] = None
    next_funding_time: Optional[datetime] = None
    annualized: Optional[float] = None
    timestamp: datetime

    model_config = {"from_attributes": True}


class FundingRateListResponse(BaseModel):
    data: list[FundingRateResponse]
    total: int


# ── Open Interest ──
class OpenInterestResponse(BaseModel):
    symbol: str
    exchange: str
    open_interest: float
    open_interest_usd: Optional[float] = None
    long_short_ratio: Optional[float] = None
    timestamp: datetime

    model_config = {"from_attributes": True}


class OpenInterestListResponse(BaseModel):
    data: list[OpenInterestResponse]
    total: int


# ── Liquidation ──
class LiquidationResponse(BaseModel):
    symbol: str
    exchange: str
    side: str
    quantity: float
    price: float
    usd_value: float
    timestamp: datetime

    model_config = {"from_attributes": True}


class LiquidationListResponse(BaseModel):
    data: list[LiquidationResponse]
    total: int
    total_long_usd: float
    total_short_usd: float


# ── Order Flow ──
class OrderFlowResponse(BaseModel):
    symbol: str
    exchange: str
    buy_volume: float
    sell_volume: float
    net_flow: float
    large_buy_count: int
    large_sell_count: int
    interval: str
    timestamp: datetime

    model_config = {"from_attributes": True}


class OrderFlowListResponse(BaseModel):
    data: list[OrderFlowResponse]
    total: int


# ── Whale Transactions ──
class WhaleTransactionResponse(BaseModel):
    symbol: str
    exchange: Optional[str] = None
    chain: Optional[str] = None
    tx_hash: Optional[str] = None
    from_address: Optional[str] = None
    to_address: Optional[str] = None
    amount: float
    usd_value: float
    tx_type: str
    is_smart_money: bool
    label: Optional[str] = None
    timestamp: datetime

    model_config = {"from_attributes": True}


class WhaleTransactionListResponse(BaseModel):
    data: list[WhaleTransactionResponse]
    total: int


# ── Market Overview ──
class MarketOverviewResponse(BaseModel):
    total_market_cap: float
    total_volume_24h: float
    btc_dominance: float
    eth_dominance: float
    fear_greed_index: int
    fear_greed_label: str
    active_pairs: int
    exchanges_count: int
    chains_count: int
    top_gainers: list[TickerResponse]
    top_losers: list[TickerResponse]


# ── Support/Resistance ──
class SupportResistanceResponse(BaseModel):
    symbol: str
    level_type: str
    price: float
    strength: float
    touches: int
    timeframe: str

    model_config = {"from_attributes": True}


# ── Heatmap ──
class HeatmapDataResponse(BaseModel):
    symbol: str
    price_level: float
    liquidation_volume: float
    side: str
    exchange: Optional[str] = None

    model_config = {"from_attributes": True}
