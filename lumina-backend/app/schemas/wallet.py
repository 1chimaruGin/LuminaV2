from datetime import datetime
import re
from typing import Optional

from pydantic import BaseModel, field_validator


class WalletAnalysisRequest(BaseModel):
    address: str
    chain: Optional[str] = None  # auto-detect if not provided

    @field_validator("address")
    @classmethod
    def validate_address(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) < 10 or len(v) > 128:
            raise ValueError("Invalid address length (must be 10-128 characters)")
        if not re.match(r'^[a-zA-Z0-9.]+$', v):
            raise ValueError("Address contains invalid characters")
        return v

    @field_validator("chain")
    @classmethod
    def validate_chain(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        allowed = {"SOL", "ETH", "BSC", "ARB", "OP", "BASE", "AVAX", "MATIC", "solana", "ethereum", "bsc", "base", "arbitrum"}
        if v.upper() not in {x.upper() for x in allowed}:
            raise ValueError(f"Unsupported chain: {v}")
        return v


class WalletProfileResponse(BaseModel):
    address: str
    chain: str
    label: Optional[str] = None
    entity: Optional[str] = None
    role: Optional[str] = None
    risk_level: str
    risk_note: Optional[str] = None
    portfolio_value: Optional[float] = None
    tags: list[str] = []
    is_smart_money: bool = False

    model_config = {"from_attributes": True}


class WalletHolding(BaseModel):
    token: str
    amount: str
    value: str
    pct: float


class WalletActivity(BaseModel):
    tx_type: str
    action: str
    date: str
    usd_value: Optional[float] = None


class WalletCounterparty(BaseModel):
    name: str
    txns: int
    volume: str


class RiskFlag(BaseModel):
    label: str
    value: str
    color: str


class WalletAnalysisResponse(BaseModel):
    profile: WalletProfileResponse
    sol_balance: Optional[str] = None
    sol_value: Optional[str] = None
    token_count: Optional[str] = None
    total_txns: Optional[str] = None
    sends: Optional[str] = None
    receives: Optional[str] = None
    portfolio_value: Optional[str] = None
    portfolio_change: Optional[str] = None
    status: str = "Active"
    funded_by: Optional[str] = None
    top_holdings: list[WalletHolding] = []
    recent_activity: list[WalletActivity] = []
    top_counterparties: list[WalletCounterparty] = []
    risk_flags: list[RiskFlag] = []
    social_mentions: list[str] = []


class StarredWalletCreate(BaseModel):
    wallet_address: str
    label: Optional[str] = None
    chain: str = "SOL"
    tags: list[str] = []


class StarredWalletResponse(BaseModel):
    id: int
    wallet_address: str
    label: Optional[str] = None
    chain: str
    tags: list[str] = []
    value: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
