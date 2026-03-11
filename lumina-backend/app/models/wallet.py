from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    JSON,
    String,
    Text,
)

from app.db.database import Base


class WalletProfile(Base):
    __tablename__ = "wallet_profiles"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    address = Column(String(128), nullable=False, unique=True, index=True)
    chain = Column(String(16), nullable=False, default="SOL")
    label = Column(String(64), nullable=True)
    entity = Column(String(64), nullable=True)
    role = Column(String(32), nullable=True)  # "Whale", "Market Maker", "Retail"
    risk_level = Column(String(16), default="Unknown")
    risk_note = Column(Text, nullable=True)
    portfolio_value = Column(Float, nullable=True)
    tags = Column(JSON, default=list)
    is_smart_money = Column(Boolean, default=False)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    wallet_address = Column(String(128), nullable=False, index=True)
    tx_hash = Column(String(128), nullable=True)
    tx_type = Column(String(16), nullable=False)  # "Buy", "Sell", "Transfer", "Burn"
    action = Column(Text, nullable=True)
    amount = Column(Float, nullable=True)
    usd_value = Column(Float, nullable=True)
    token = Column(String(32), nullable=True)
    counterparty = Column(String(128), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)


class StarredWallet(Base):
    __tablename__ = "starred_wallets"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(String(128), nullable=False, index=True)
    wallet_address = Column(String(128), nullable=False)
    label = Column(String(64), nullable=True)
    chain = Column(String(16), default="SOL")
    tags = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)
