from fastapi import APIRouter

from app.api.routes import market, wallet, bots, ws, token, investigate, chat, strategy

api_router = APIRouter()

api_router.include_router(market.router)
api_router.include_router(wallet.router)
api_router.include_router(bots.router)
api_router.include_router(ws.router)
api_router.include_router(token.router)
api_router.include_router(investigate.router)
api_router.include_router(chat.router)
api_router.include_router(strategy.router)
