"""
WebSocket endpoints for real-time data streaming.
Provides live ticker updates, whale alerts, and order flow.
"""

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.exchange import fetch_tickers, fetch_recent_trades

logger = logging.getLogger(__name__)
router = APIRouter(tags=["WebSocket"])


class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, message: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


@router.websocket("/ws/tickers")
async def ws_tickers(websocket: WebSocket, exchange: str = "binance"):
    await manager.connect(websocket)
    try:
        while True:
            tickers = await fetch_tickers(exchange)
            # Send top 20 by volume
            top = tickers[:20]
            await websocket.send_json({
                "type": "tickers",
                "exchange": exchange,
                "data": top,
            })
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WS tickers error: {e}")
        manager.disconnect(websocket)


@router.websocket("/ws/whale-alerts")
async def ws_whale_alerts(
    websocket: WebSocket,
    exchange: str = "binance",
    symbol: str = "BTC/USDT",
    min_usd: float = 100_000,
):
    await manager.connect(websocket)
    seen_timestamps: set[str] = set()
    try:
        while True:
            trades = await fetch_recent_trades(exchange, symbol, limit=200, min_usd=min_usd)
            new_trades = []
            for t in trades:
                ts = t.get("timestamp", "")
                if ts and ts not in seen_timestamps:
                    seen_timestamps.add(ts)
                    new_trades.append(t)

            if new_trades:
                await websocket.send_json({
                    "type": "whale_alert",
                    "data": new_trades,
                })

            # Keep set bounded
            if len(seen_timestamps) > 1000:
                seen_timestamps.clear()

            await asyncio.sleep(3)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WS whale alerts error: {e}")
        manager.disconnect(websocket)


@router.websocket("/ws/orderflow")
async def ws_orderflow(
    websocket: WebSocket,
    exchange: str = "binance",
    symbol: str = "BTC/USDT",
):
    from app.services.exchange import fetch_order_book

    await manager.connect(websocket)
    try:
        while True:
            ob = await fetch_order_book(exchange, symbol)
            if ob:
                await websocket.send_json({
                    "type": "orderflow",
                    "data": ob,
                })
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WS orderflow error: {e}")
        manager.disconnect(websocket)
