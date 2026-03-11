from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Lumina Backend"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True
    API_PREFIX: str = "/api/v1"

    # CORS — restrict to known frontend origins
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:3001", "http://127.0.0.1:3000", "http://127.0.0.1:3001"]

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://lumina:lumina@localhost:5432/lumina"
    DATABASE_ECHO: bool = False

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    CACHE_TTL_SECONDS: int = 30

    # Exchange API keys (optional — ccxt public endpoints work without keys)
    BINANCE_API_KEY: str = ""
    BINANCE_API_SECRET: str = ""
    BYBIT_API_KEY: str = ""
    BYBIT_API_SECRET: str = ""
    OKX_API_KEY: str = ""
    OKX_API_SECRET: str = ""
    OKX_PASSPHRASE: str = ""

    # Solana RPC (Alchemy)
    ALCHEMY_API_KEY: str = ""

    # Grok API (for wallet analysis)
    GROK_API_KEY: str = ""
    GROK_API_URL: str = "https://api.x.ai/v1"

    # Claude API (for token AI analysis)
    CLAUDE_API_KEY: str = ""

    # Moralis API (for token holder count)
    MORALIS_API_KEY: str = ""

    # Block explorer API keys (BscScan, Etherscan, etc.)
    BSCSCAN_API_KEY: str = ""
    ETHERSCAN_API_KEY: str = ""

    # TheGraph API (for investigate)
    THEGRAPH_API_KEY: str = ""

    # WebSocket
    WS_HEARTBEAT_INTERVAL: int = 30

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()
