from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Float,
    Integer,
    JSON,
    String,
)

from app.db.database import Base


class TradingBot(Base):
    __tablename__ = "trading_bots"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(String(128), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    bot_type = Column(String(16), nullable=False)  # "trading", "grid", "dca", "sniper", "arbitrage", "algo"
    pair = Column(String(32), nullable=False)
    exchange = Column(String(32), default="binance")
    status = Column(String(16), default="paused")  # "running", "paused", "stopped"
    investment = Column(Float, default=0.0)
    profit = Column(Float, default=0.0)
    profit_pct = Column(Float, default=0.0)
    trades_count = Column(Integer, default=0)
    win_rate = Column(Float, default=0.0)
    config = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
