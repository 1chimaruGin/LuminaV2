"""
Trading bot management API routes.
In-memory store for now; swap to DB later.
"""

from fastapi import APIRouter, HTTPException, Query

from app.schemas.bot import BotCreate, BotUpdate

router = APIRouter(prefix="/bots", tags=["Bots"])

# In-memory bot store
_bots: list[dict] = []
_next_id = 1


@router.get("/")
async def list_bots(
    user_id: str = Query("default"),
    bot_type: str = Query(None),
    status: str = Query(None),
):
    filtered = [b for b in _bots if b["user_id"] == user_id]
    if bot_type:
        filtered = [b for b in filtered if b["bot_type"] == bot_type]
    if status:
        filtered = [b for b in filtered if b["status"] == status]

    running = sum(1 for b in filtered if b["status"] == "running")
    total_profit = sum(b.get("profit", 0) for b in filtered)

    return {
        "data": filtered,
        "total": len(filtered),
        "running_count": running,
        "total_profit": total_profit,
    }


@router.post("/")
async def create_bot(bot: BotCreate, user_id: str = Query("default")):
    global _next_id
    entry = {
        "id": _next_id,
        "user_id": user_id,
        "name": bot.name,
        "bot_type": bot.bot_type,
        "pair": bot.pair,
        "exchange": bot.exchange,
        "status": "paused",
        "investment": bot.investment,
        "profit": 0.0,
        "profit_pct": 0.0,
        "trades_count": 0,
        "win_rate": 0.0,
        "config": bot.config,
    }
    _bots.append(entry)
    _next_id += 1
    return entry


@router.get("/{bot_id}")
async def get_bot(bot_id: int):
    bot = next((b for b in _bots if b["id"] == bot_id), None)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    return bot


@router.patch("/{bot_id}")
async def update_bot(bot_id: int, update: BotUpdate):
    bot = next((b for b in _bots if b["id"] == bot_id), None)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    if update.name is not None:
        bot["name"] = update.name
    if update.status is not None:
        bot["status"] = update.status
    if update.config is not None:
        bot["config"] = update.config

    return bot


@router.post("/{bot_id}/toggle")
async def toggle_bot(bot_id: int):
    bot = next((b for b in _bots if b["id"] == bot_id), None)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    bot["status"] = "paused" if bot["status"] == "running" else "running"
    return bot


@router.delete("/{bot_id}")
async def delete_bot(bot_id: int):
    global _bots
    _bots = [b for b in _bots if b["id"] != bot_id]
    return {"ok": True}
