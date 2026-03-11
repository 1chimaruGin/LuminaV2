# Lumina Backend

FastAPI backend for the Lumina crypto analytics platform. Provides real-time market data, wallet analysis, and trading bot management.

## Architecture

```
lumina-backend/
├── app/
│   ├── api/
│   │   ├── routes/
│   │   │   ├── market.py      # Tickers, funding, OI, liquidations, order flow, OHLCV
│   │   │   ├── wallet.py      # Wallet analysis, starred wallets
│   │   │   ├── bots.py        # Trading bot CRUD + toggle
│   │   │   └── ws.py          # WebSocket: live tickers, whale alerts, order flow
│   │   └── router.py          # API router aggregation
│   ├── core/
│   │   └── config.py          # Pydantic settings (env-based)
│   ├── db/
│   │   ├── database.py        # SQLAlchemy async engine + session
│   │   └── redis.py           # Redis cache helpers
│   ├── models/
│   │   ├── market.py          # Ticker, FundingRate, OpenInterest, Liquidation, etc.
│   │   ├── wallet.py          # WalletProfile, WalletTransaction, StarredWallet
│   │   └── bot.py             # TradingBot
│   ├── schemas/
│   │   ├── market.py          # Pydantic response models
│   │   ├── wallet.py          # Wallet request/response schemas
│   │   └── bot.py             # Bot CRUD schemas
│   ├── services/
│   │   └── exchange.py        # ccxt multi-exchange data fetching + Redis caching
│   └── main.py                # FastAPI app entry point
├── docker-compose.yml          # PostgreSQL 16 + Redis 7
├── requirements.txt
├── .env.example
└── README.md
```

## Quick Start

### 1. Start infrastructure

```bash
docker compose up -d
```

This starts PostgreSQL (port 5432) and Redis (port 6379).

### 2. Create virtual environment

```bash
cd lumina-backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env with your API keys (optional — public endpoints work without keys)
```

### 4. Run the server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 5. Explore the API

- **Swagger docs**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health check**: http://localhost:8000/health

## API Endpoints

### Market Data (`/api/v1/market`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/tickers` | All tickers (multi-exchange) |
| GET | `/tickers/{symbol}` | Single ticker lookup |
| GET | `/overview` | Market overview (cap, volume, fear/greed, gainers/losers) |
| GET | `/funding` | Funding rates (all exchanges) |
| GET | `/funding/{symbol}` | Funding rate for symbol |
| GET | `/open-interest` | Open interest batch |
| GET | `/order-flow/{symbol}` | Order book / flow data |
| GET | `/whale-trades/{symbol}` | Large trades (>$100K default) |
| GET | `/ohlcv/{symbol}` | OHLCV candles |

### Wallet (`/api/v1/wallet`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/analyze` | Analyze a wallet address |
| GET | `/starred` | List starred wallets |
| POST | `/starred` | Add starred wallet |
| DELETE | `/starred/{id}` | Remove starred wallet |

### Bots (`/api/v1/bots`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List all bots |
| POST | `/` | Create a bot |
| GET | `/{id}` | Get bot details |
| PATCH | `/{id}` | Update bot |
| POST | `/{id}/toggle` | Toggle pause/run |
| DELETE | `/{id}` | Delete bot |

### WebSocket

| Endpoint | Description |
|----------|-------------|
| `ws://localhost:8000/api/v1/ws/tickers` | Live ticker stream (5s interval) |
| `ws://localhost:8000/api/v1/ws/whale-alerts` | Real-time whale trade alerts |
| `ws://localhost:8000/api/v1/ws/orderflow` | Live order flow updates |

## Tech Stack

- **FastAPI** — async Python web framework
- **SQLAlchemy 2.0** — async ORM with PostgreSQL
- **Redis** — caching layer (15-60s TTL per data type)
- **ccxt** — unified exchange API (Binance, Bybit, OKX)
- **WebSocket** — real-time data streaming
- **Pydantic v2** — request/response validation
- **Docker Compose** — PostgreSQL 16 + Redis 7

## Exchange Support

Currently fetching from:
- **Binance** (spot + futures)
- **Bybit** (derivatives)
- **OKX** (derivatives)

API keys are optional — all public endpoints work without authentication. Add keys in `.env` for higher rate limits and private endpoints.
