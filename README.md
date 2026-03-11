<p align="center">
  <img src="lumina-app/public/lumina-logo.svg" alt="Lumina" width="80" />
</p>

<h1 align="center">Lumina V2</h1>
<p align="center"><strong>Real-time whale activity tracking, smart money analytics, and AI-powered crypto market intelligence.</strong></p>

<p align="center">
  <img src="https://img.shields.io/badge/Next.js-16-black?logo=next.js" />
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi" />
  <img src="https://img.shields.io/badge/React-19-61DAFB?logo=react" />
  <img src="https://img.shields.io/badge/TailwindCSS-4-06B6D4?logo=tailwindcss" />
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python" />
</p>

---

## Overview

Lumina V2 is a full-stack crypto intelligence platform that aggregates data from 8+ exchanges, on-chain sources (Moralis, CoinGecko, DexScreener), and AI models to provide actionable market insights. It combines institutional-grade whale tracking with wallet-level trade analysis — built for traders who want to see what smart money is doing and replicate it.

## Architecture

```
LuminaV2/
├── lumina-app/          # Next.js 16 frontend (React 19 + TailwindCSS 4)
│   ├── src/app/         # App Router pages
│   ├── src/components/  # Shared UI components
│   ├── src/context/     # React context providers (Wallet, etc.)
│   └── src/lib/         # API client, utilities
├── lumina-backend/      # FastAPI backend (Python 3.11+)
│   ├── app/api/routes/  # REST + WebSocket endpoints
│   ├── app/services/    # Exchange connectors, token resolver
│   ├── app/db/          # PostgreSQL + Redis (async)
│   └── app/models/      # SQLAlchemy models
└── docker-compose.yml   # PostgreSQL 16 + Redis 7
```

**Frontend** → `localhost:3000` · **Backend API** → `localhost:8000/api/v1`

## Features

### Dashboard — Market Intelligence
- **Real-time tickers** from Binance, Bybit, OKX, Bitget, Coinbase, Kraken, HTX, Gate.io
- **Market sentiment hero** — aggregated Fear & Greed, BTC dominance, total market cap
- **Top movers** — biggest gainers/losers across all exchanges
- **Whale movement tracker** — large trades detected in real-time via WebSocket
- **Exchange volume comparison** — cross-exchange volume analysis
- **Actionable alerts** — anomaly detection for unusual activity

### Market Insights (`/insight`)
- **Funding rates** — perpetual swap funding across exchanges with heatmap
- **Open interest** — aggregated OI changes with historical charts
- **Liquidation map** — real-time liquidation events and clustering
- **Order flow** — buy/sell pressure analysis, CVD, large order detection
- **Support & resistance** — auto-detected key price levels
- **Heatmap** — correlation matrix and sector rotation visualization
- **Strategy scanner** — volume spike detection, momentum signals

### Token Analyzer (`/token-analyzer`)
- **Multi-source price charts** using TradingView Lightweight Charts
- **Wallet trade overlay** — track a specific wallet's buys/sells on the chart
- **On-chain metadata** — token info from Moralis, CoinGecko, DexScreener
- **AI-powered analysis** — Grok-based token risk and opportunity assessment

### Wallet Analyzer (`/wallet-analyzer`)
- **Portfolio view** — multi-chain holdings with token logos, balances, and allocation %
- **Trader PnL mode** — per-token realized/unrealized PnL, win rate, hold duration, buy/sell counts
- **Clickable token drill-down** — expand any token to see individual entry/exit trades with timestamps, amounts, USD values, and block explorer TX links
- **Action buttons** — "Analyze Token" navigation, address copy, share to Twitter
- **AI wallet analysis** — Grok-powered behavioral profiling and risk assessment
- **Counterparty map** — visualize who the wallet trades with most
- **Transfers feed** — recent on-chain transfers with pagination
- **Multi-chain** — Ethereum, BSC, Base, Arbitrum, Optimism, Polygon, Solana

### Investigate (`/investigate`)
- **Entity investigation** — deep analysis of wallet clusters and relationships
- **Flow tracing** — follow funds across multiple hops

### AI Copilot (`/ai-copilot`)
- **Conversational AI** — ask questions about markets, tokens, wallets
- **Context-aware** — uses live market data in responses

### Spot & Derivatives Markets (`/markets`)
- **Spot orderbook** — real-time bid/ask depth
- **Derivatives dashboard** — funding, OI, and liquidation data side-by-side

### Trading Bots (`/bots/trading`)
- **Bot management UI** — configure and monitor automated strategies

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 16, React 19, TailwindCSS 4, Lightweight Charts |
| Backend | FastAPI, Uvicorn, Python 3.11+ |
| Database | PostgreSQL 16 (async via SQLAlchemy + asyncpg) |
| Cache | Redis 7 (hiredis) |
| Exchange Data | CCXT (8 exchanges) |
| On-chain | Moralis API, CoinGecko, DexScreener, TrustWallet CDN |
| AI | Grok API (xAI) |
| HTTP | httpx, aiohttp (async) |
| Fonts | Space Grotesk, IBM Plex Mono, Material Symbols |

## Quick Start

### Prerequisites
- **Node.js** ≥ 20
- **Python** ≥ 3.11
- **Docker** (for PostgreSQL + Redis) or local installations

### 1. Clone & Infrastructure

```bash
git clone https://github.com/1chimaruGin/LuminaV2.git
cd LuminaV2

# Start PostgreSQL & Redis
docker compose up -d
```

### 2. Backend

```bash
cd lumina-backend

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env — add your API keys (Moralis, Grok, exchange keys)

# Run
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Frontend

```bash
cd lumina-app

# Install dependencies
npm install

# Configure environment
echo "NEXT_PUBLIC_API=http://localhost:8000" > .env

# Run
npm run dev
```

Open **http://localhost:3000** — the dashboard auto-connects to the backend and begins streaming live data.

## Environment Variables

### Backend (`lumina-backend/.env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `REDIS_URL` | Yes | Redis connection string |
| `GROK_API_KEY` | No | xAI Grok API key for AI features |
| `GROK_API_URL` | No | Grok API base URL (default: `https://api.x.ai/v1`) |
| `BINANCE_API_KEY` | No | Binance API key (public endpoints work without) |
| `BYBIT_API_KEY` | No | Bybit API key |
| `OKX_API_KEY` | No | OKX API key |
| `CACHE_TTL_SECONDS` | No | Redis cache TTL (default: 30) |
| `DEBUG` | No | Enable debug logging |

### Frontend (`lumina-app/.env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `NEXT_PUBLIC_API` | Yes | Backend API URL |

## API Endpoints

All endpoints are prefixed with `/api/v1`.

| Route | Description |
|-------|-------------|
| `GET /market/overview` | Aggregated market stats |
| `GET /market/tickers` | All exchange tickers |
| `GET /market/funding-rates` | Perpetual funding rates |
| `GET /market/whale-trades` | Recent large trades |
| `POST /wallet/analyze` | Wallet portfolio analysis |
| `POST /wallet/ai-analyze` | AI-powered wallet profiling |
| `POST /wallet/trader-profile` | Per-token PnL breakdown |
| `POST /wallet/wallet-token-trades` | Individual token trade history |
| `POST /token/analyze` | Token metadata + price data |
| `POST /chat/message` | AI copilot conversation |
| `WS /ws/trades` | Real-time whale trade stream |
| `GET /strategy/scanner` | Volume spike & momentum scan |

## Development

```bash
# Frontend build check
cd lumina-app && npm run build

# Backend tests
cd lumina-backend && pytest

# Lint frontend
cd lumina-app && npm run lint
```

## License

Private — All rights reserved.
