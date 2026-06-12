<p align="center">
  <img src="lumina-app/public/lumina-logo.svg" alt="Lumina" width="72" />
</p>

# Lumina V2

> Real-time whale tracking, smart-money analytics, and AI-powered crypto market intelligence.

Lumina V2 is a full-stack crypto intelligence platform. A **Next.js** frontend renders live dashboards while a **FastAPI** backend aggregates data from 8 exchanges (via CCXT), on-chain sources, and AI models to surface whale trades, market structure, and wallet-level insights.

<p align="center">
  <img src="https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white" />
  <img src="https://img.shields.io/badge/Next.js-16-black?logo=next.js" />
  <img src="https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white" />
  <img src="https://img.shields.io/badge/TailwindCSS-4-06B6D4?logo=tailwindcss&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white" />
</p>

## Features

- **Live market dashboard** — tickers, sentiment, top movers, and exchange-volume comparison streamed from 8 exchanges via CCXT.
- **Market insights** — funding rates, open interest, liquidation map, order flow, support/resistance, and a strategy scanner.
- **Token analyzer** — multi-source price charts (TradingView Lightweight Charts) with on-chain metadata and AI-driven risk analysis (Claude).
- **Wallet analyzer** — multi-chain holdings, per-token PnL, trade drill-downs, and AI behavioral profiling (Grok).
- **AI copilot & investigate** — conversational market Q&A plus wallet-cluster and fund-flow tracing.
- **Real-time whale stream** — large trades pushed over WebSocket.

## Getting Started

**Prerequisites:** Node.js ≥ 20, Python ≥ 3.11, and Docker (for PostgreSQL + Redis).

### Backend (`lumina-backend`)

```bash
cd lumina-backend
docker compose up -d                 # PostgreSQL + Redis
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                 # add your API keys
uvicorn app.main:app --reload --port 8000
```

### Frontend (`lumina-app`)

```bash
cd lumina-app
npm install
npm run dev                          # http://localhost:3000
```

Set `NEXT_PUBLIC_API_URL` (defaults to `http://localhost:8000/api/v1`) to point the app at your backend. Other scripts: `npm run build`, `npm start`, `npm run lint`.

## Project Structure

```
LuminaV2/
├── lumina-app/        # Next.js 16 frontend (React 19, TailwindCSS 4, Lightweight Charts)
│   └── src/app/       # App Router pages: dashboard, insight, token/wallet analyzer, ai-copilot...
└── lumina-backend/    # FastAPI backend (Python 3.11+)
    └── app/           # api/ services/ (CCXT exchanges, token resolver, AI) db/ models/ schemas/
```

## Tech Stack

- **Frontend:** Next.js 16, React 19, TypeScript, TailwindCSS 4, Lightweight Charts
- **Backend:** FastAPI, Uvicorn, SQLAlchemy (async) + asyncpg, Redis, CCXT, httpx/aiohttp
- **AI:** Claude (Anthropic) for token analysis, Grok (xAI) for wallet analysis
