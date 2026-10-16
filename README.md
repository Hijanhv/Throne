# Throne

Write a strategy. Watch it trade.

Throne turns a trading strategy written in plain English into deterministic JSON rules, backtests those rules on historical NSE data, and runs them live (paper or real money through Dhan). You never write code.

```
"Buy NIFTY when RSI(14) crosses below 30 and volume spikes 2x.
 Sell when RSI crosses above 70 or stop loss hits 2%."

        IF RSI(14) CROSSES BELOW 30          -> BUY   (all must hold)
        IF VOLUME GREATER THAN 2x AVG VOLUME -> BUY
        IF RSI(14) CROSSES ABOVE 70          -> SELL
        STOP LOSS 2%
```

## Architecture

```
 ┌──────────────────────────┐
 │  Next.js 14 dashboard     │   StrategyInput -> RuleViewer -> Backtest | Live
 │  (Vercel)                 │
 └────────────┬─────────────┘
              │ axios, NEXT_PUBLIC_API_URL
              ▼
 ┌──────────────────────────────────────────────────────────────────┐
 │  FastAPI backend                                                  │
 │                                                                    │
 │  POST /parse ──► parser.py ──► Ollama tinyllama (localhost:11434)  │
 │                     │            │ JSON, validated + sanity checked │
 │                     │            ▼                                  │
 │                     └──► regex parser (offline, always runs)        │
 │                              │                                      │
 │                              ▼  ParsedStrategy (StrategyRule[])     │
 │  POST /backtest ──► backtester.py ◄── yfinance OHLCV                │
 │                       ta indicators + numpy signals                 │
 │                              │  BacktestResult (equity, stats)      │
 │  POST /deploy ───► executor.py (asyncio task, 60s loop)             │
 │                       same signal code as the backtest              │
 │                       ├── paper: fills simulated in memory          │
 │                       └── live:  dhan_client.py ──► Dhan API        │
 │  GET  /status/{id} ◄── frontend polls every 5s for live P&L         │
 └──────────────────────────────────────────────────────────────────┘
```

| Layer | Tech |
| --- | --- |
| Frontend | Next.js 14 (App Router), TypeScript (strict, no `any`), Tailwind, shadcn/ui style components on Radix, TradingView Lightweight Charts v4, Axios, Sonner toasts |
| Backend | Python 3.11+, FastAPI, Pydantic v2, yfinance, pandas, numpy, `ta`, httpx, asyncio, dhanhq v2 |
| LLM | Ollama running locally with `tinyllama`. No cloud LLM APIs anywhere. |

## How each piece works

**Parser.** The strategy text goes to Ollama with `format: "json"` and temperature 0. Small local models make things up, so every AI rule is checked before it is accepted:

- it must pass Pydantic validation
- every indicator it names must appear in your text
- every number it uses must appear in your text
- the direction must match your wording ("below 30" cannot become `CROSSES_ABOVE 30`)
- it must find at least as many conditions as the regex parser did

If any check fails, or Ollama is offline, the regex parser's result is used and the reason shows up in the UI. The badge says **AI** or **REGEX FALLBACK** with a confidence score. For regex, the score is the share of your clauses it understood, and anything it skipped is listed as "Could not understand: ...". In testing, tinyllama often flipped "below" into "above" and copied numbers from its prompt. The checks catch that, so expect the regex parser to handle most strategies.

**Backtester.** Indicators (RSI, MACD 12/26/9, EMA, SMA, Bollinger 20/2, volume vs 20 bar average) and the signal column (+1 buy, -1 sell, 0 hold) are computed vectorized over the full series. Execution rules:

- A signal on bar *t*'s close fills at bar *t+1*'s open, so there is no lookahead.
- Stop loss and take profit are checked intrabar against the low and high. A gap through the level fills at the open. If both levels sit inside one bar, the stop is assumed to hit first.
- Long only, fully invested, compounding, 5 bps fee per side.
- Sharpe uses per-bar returns annualized by `sqrt(252 x bars per day)`. Max drawdown is peak to trough of the equity curve.
- The curve starts at 100 and the stats include a buy-and-hold benchmark.

**Executor.** Every 60 seconds it pulls recent candles and computes signals with the same function the backtester uses, so live and backtest logic cannot drift. It decides on the last *completed* bar, which mirrors the backtest's close-then-next-open rule. Stops and targets are checked on every tick against the latest price. Paper mode never calls the broker. In live mode, a rejected order puts the executor into `error` and stops it, so it never keeps trading blind.

## Setup

Requirements: Python 3.11+, Node 18.17+, and optionally [Ollama](https://ollama.com).

```bash
git clone https://github.com/Hijanhv/Throne.git
cd Throne
cp .env.example .env          # fill in Dhan keys only if you want LIVE mode
./start.sh                    # API on :8000, dashboard on :3000
```

Or run each side yourself:

```bash
# backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn main:app --reload --port 8000
pytest                        # 34 tests: parser, backtester, executor, API

# frontend
cd frontend
npm install
npm run dev                   # also: npm run typecheck, npm run lint, npm run format
```

API docs are served at http://localhost:8000/docs.

### Ollama

```bash
brew install ollama           # or the installer from ollama.com
ollama serve                  # listens on http://localhost:11434
ollama pull tinyllama
```

The top bar shows `OLLAMA: ONLINE` once the backend can reach it. Any model works, for example `OLLAMA_MODEL=llama3.2:3b`. Larger models pass the sanity checks far more often than tinyllama does. Everything still works with Ollama switched off.

### Dhan API credentials (live mode only)

1. Open a Dhan account and log in at [web.dhan.co](https://web.dhan.co).
2. Go to **My Profile → Access DhanHQ APIs** and generate an access token. Copy your **Client ID** and the **Access Token**.
3. Put them in `.env` as `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN`. They are read from the environment only and never sent to the frontend.
4. Dhan identifies instruments by **security ID**, not ticker. Look one up in the scrip master at `https://images.dhan.co/api-data/api-scrip-master.csv` (NSE equity examples: RELIANCE `2885`, HDFCBANK `1333`, INFY `1594`, NIFTYBEES `10576`). Indices like NIFTY 50 cannot be bought directly, so to trade a NIFTY signal live, backtest on `NIFTY50` and deploy with an ETF such as NIFTYBEES.
5. In the LIVE tab, flip the toggle, enter the security ID and tick the confirmation box. The API refuses live deploys without credentials, a security ID, and `confirm_live: true`.

Access tokens expire. If live orders start failing with an auth error, generate a new token.

## Deploying

### Frontend on Vercel

1. Import the repo in Vercel and set **Root Directory** to `frontend`. Vercel detects Next.js.
2. Add the env var `NEXT_PUBLIC_API_URL` pointing at your backend, for example `https://throne-api.onrender.com`.
3. Deploy. To change the backend later, update the env var and redeploy, because `NEXT_PUBLIC_*` values are baked in at build time.

### Backend on Render or Railway

- **Render:** `render.yaml` is included. Create a Blueprint from the repo, then fill in `DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN`, and `CORS_ORIGINS=https://your-app.vercel.app`.
- **Railway:** create a service with root directory `backend`. The `Procfile` starts uvicorn on `$PORT`. Add the same env vars.

Things to know:

- A hosted backend cannot reach the Ollama on your laptop, so it uses the regex parser. That is fine, since it is the same rule format.
- Strategies and executors live in memory. A restart or redeploy clears them, and free tiers that sleep will pause running executors.
- To use a Vercel frontend with a backend on your own machine, set `NEXT_PUBLIC_API_URL=http://localhost:8000`. Chrome will ask permission for the public site to reach your local network. A tunnel (`cloudflared tunnel --url http://localhost:8000`) avoids that prompt.

## What you can write

| Indicator | Phrases the parser understands |
| --- | --- |
| RSI | `RSI(14) crosses below 30`, `RSI drops below 30`, `RSI exceeds 70`, `RSI is above 60`, `RSI oversold` / `overbought` |
| EMA / SMA crossovers | `20 EMA crosses above 50 EMA`, `EMA(9) crosses below SMA(21)`, `golden cross`, `death cross` |
| Price vs average | `price crosses above 20 EMA`, `price is above 200 SMA`, `close below 50 DMA` |
| MACD | `MACD crosses above signal line`, `MACD crosses below zero`, `bullish MACD crossover` |
| Bollinger | `price touches the lower bollinger band`, `at the upper band` |
| Volume | `volume spikes 2x`, `volume is 1.5x average volume`, `3x average volume`, `high volume` |
| Risk | `stop loss 2%`, `2% stop loss`, `target 5%`, `take profit 4%` |

Entry conditions joined with "and" must all hold on the same bar. Exit conditions joined with "or" trigger on any one. "Crosses" means the cross happened on that bar, so two crossovers joined by "and" rarely line up, and the parser warns you when you write one.

### Examples to try

```
Buy when RSI drops below 35. Sell when RSI exceeds 65 or 2% stop loss hits.            (RELIANCE, 1d)
Buy when 20 EMA crosses above 50 EMA. Sell when 20 EMA crosses below 50 EMA. Stop loss 3%.   (NIFTY50, 1h)
Buy when MACD crosses above signal line and price is above 200 SMA.
  Exit when MACD crosses below signal. Target 6%, stop loss 2%.                         (HDFCBANK, 1d)
Buy when price touches the lower bollinger band. Sell at the upper band or 2.5% stop loss.  (INFY, 1d)
Buy on golden cross, sell on death cross.                                                (NIFTY50, 1d, 5y)
Buy NIFTY when RSI(14) crosses below 30 and volume spikes 2x.
  Sell when RSI crosses above 70 or stop loss hits 2%.                                   (rare entry, few trades)
```

## API

| Method | Path | Body / result |
| --- | --- | --- |
| `POST` | `/parse` | `{text, symbol?, timeframe}` → `ParsedStrategy` |
| `POST` | `/backtest` | `{strategy_id, period, interval?, initial_capital, fee_bps}` → `BacktestResult` |
| `POST` | `/deploy` | `{strategy_id, mode, capital, security_id?, exchange_segment?, confirm_live?}` → `{status: "deployed"}` |
| `GET` | `/status/{id}` | `ExecutorStatus` (P&L, position, fills, last signal) |
| `POST` | `/stop/{id}` | stops the executor and keeps its history |
| `DELETE` | `/strategy/{id}` | stops and forgets the strategy |
| `GET` | `/health` | `{status, ollama, ollama_model, dhan_configured, ...}` |

## Data limits

- yfinance only serves 15 minute bars for the last 60 days and hourly bars for about 2 years. Longer requests are shortened and flagged.
- Index tickers (`^NSEI`, `^NSEBANK`) have daily volume but no intraday volume. Volume rules are skipped with a warning on intraday index backtests.
- Symbols without a suffix are treated as NSE (`TCS` → `TCS.NS`). Pass `^GSPC` or `AAPL` style tickers with a suffix or caret to use other markets.

## Roadmap

- Futures support (`NSE_FNO`) with expiry handling. SEBI is consulting on settling expiring F&O at the VWAP of the last 30 minutes instead of the closing auction price. A futures backtest would need to settle at that price, and the executor would need an option to square off before the final 30 minutes on expiry day.
- Persistent storage for strategies and executor state.
- Order fill reconciliation from Dhan's order book. Live fills are currently marked at the last traded price.
- Short selling and position sizing rules.

## Disclaimer

Throne is a research and education tool. Backtests are not predictions. Live mode sends real orders to a real brokerage account. Paper trade first and use money you can afford to lose.
