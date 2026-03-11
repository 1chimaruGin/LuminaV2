from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
)

from app.db.database import Base


class Ticker(Base):
    __tablename__ = "tickers"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    exchange = Column(String(32), nullable=False, index=True)
    symbol = Column(String(32), nullable=False, index=True)
    base = Column(String(16), nullable=False)
    quote = Column(String(16), nullable=False)
    price = Column(Float, nullable=False)
    price_change_24h = Column(Float, default=0.0)
    volume_24h = Column(Float, default=0.0)
    high_24h = Column(Float, default=0.0)
    low_24h = Column(Float, default=0.0)
    market_cap = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_tickers_exchange_symbol", "exchange", "symbol"),
    )


class FundingRate(Base):
    __tablename__ = "funding_rates"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    exchange = Column(String(32), nullable=False, index=True)
    symbol = Column(String(32), nullable=False, index=True)
    rate = Column(Float, nullable=False)
    predicted_rate = Column(Float, nullable=True)
    next_funding_time = Column(DateTime, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_funding_exchange_symbol", "exchange", "symbol"),
    )


class OpenInterest(Base):
    __tablename__ = "open_interest"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    exchange = Column(String(32), nullable=False, index=True)
    symbol = Column(String(32), nullable=False, index=True)
    open_interest = Column(Float, nullable=False)
    open_interest_usd = Column(Float, nullable=True)
    long_short_ratio = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_oi_exchange_symbol", "exchange", "symbol"),
    )


class Liquidation(Base):
    __tablename__ = "liquidations"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    exchange = Column(String(32), nullable=False, index=True)
    symbol = Column(String(32), nullable=False, index=True)
    side = Column(String(8), nullable=False)  # "long" or "short"
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    usd_value = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_liq_exchange_symbol", "exchange", "symbol"),
    )


class OrderFlowSnapshot(Base):
    __tablename__ = "order_flow"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    exchange = Column(String(32), nullable=False, index=True)
    symbol = Column(String(32), nullable=False, index=True)
    buy_volume = Column(Float, nullable=False)
    sell_volume = Column(Float, nullable=False)
    net_flow = Column(Float, nullable=False)
    large_buy_count = Column(Integer, default=0)
    large_sell_count = Column(Integer, default=0)
    interval = Column(String(8), default="5m")
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_of_exchange_symbol", "exchange", "symbol"),
    )


class WhaleTransaction(Base):
    __tablename__ = "whale_transactions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    exchange = Column(String(32), nullable=True)
    chain = Column(String(16), nullable=True)
    symbol = Column(String(32), nullable=False, index=True)
    tx_hash = Column(String(128), nullable=True, unique=True)
    from_address = Column(String(128), nullable=True)
    to_address = Column(String(128), nullable=True)
    amount = Column(Float, nullable=False)
    usd_value = Column(Float, nullable=False)
    tx_type = Column(String(16), nullable=False)  # "buy", "sell", "transfer"
    is_smart_money = Column(Boolean, default=False)
    label = Column(String(64), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)


class SupportResistance(Base):
    __tablename__ = "support_resistance"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False, index=True)
    level_type = Column(String(16), nullable=False)  # "support" or "resistance"
    price = Column(Float, nullable=False)
    strength = Column(Float, default=0.0)  # 0-1 strength score
    touches = Column(Integer, default=0)
    timeframe = Column(String(8), default="4h")
    timestamp = Column(DateTime, default=datetime.utcnow)


class HeatmapData(Base):
    __tablename__ = "heatmap_data"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False, index=True)
    price_level = Column(Float, nullable=False)
    liquidation_volume = Column(Float, nullable=False)
    side = Column(String(8), nullable=False)  # "long" or "short"
    exchange = Column(String(32), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
