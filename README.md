# Throne

Write a strategy. Watch it trade.

Throne runs entirely on your own machine: the dashboard, the API and the local LLM. See [Run it locally](#run-it-locally) to start it in two commands.

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
 │  localhost:3000           │
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
- where it reads the same condition as the regex parser, the operator must match ("is below" is `LESS_THAN`, not a cross)
- it must find at least as many conditions as the regex parser did

If any check fails, or Ollama is offline, the regex parser's result is used and the reason shows up in the UI. The badge says **AI** or **REGEX FALLBACK** with a confidence score. For regex, the score is the share of your clauses it understood, and anything it skipped is listed as "Could not understand: ...". In testing, tinyllama often flipped "below" into "above" and copied numbers from its prompt, and none of its answers passed. `qwen2.5:1.5b` (about 1 GB) does better: it got crossover strategies right and was rejected only for real mistakes, such as treating the MACD signal period 9 as a threshold. Expect the regex parser to handle most strategies either way.

**Backtester.** Indicators (RSI, MACD 12/26/9, EMA, SMA, Bollinger 20/2, volume vs 20 bar average) and the signal column (+1 buy, -1 sell, 0 hold) are computed vectorized over the full series. Execution rules:

- A signal on bar *t*'s close fills at bar *t+1*'s open, so there is no lookahead.
- Stop loss and take profit are checked intrabar against the low and high. A gap through the level fills at the open. If both levels sit inside one bar, the stop is assumed to hit first.
- Long only, fully invested, compounding, 5 bps fee per side.
- Extra history is downloaded before the window so slow indicators (SMA 200, MACD) are ready on the first bar. A 1 year test of "price above 200 SMA" trades the whole year.
- Sharpe uses per-bar returns annualized by `sqrt(252 x bars per day)`. Max drawdown is peak to trough of the equity curve.
- The curve starts at 100 and the stats include a buy-and-hold benchmark.

**Executor.** Every 60 seconds it pulls recent candles and computes signals with the same function the backtester uses, so live and backtest logic cannot drift. It decides on the last *completed* bar, which mirrors the backtest's close-then-next-open rule. Stops and targets are checked on every tick against the latest price. Paper mode never calls the broker. In live mode, a rejected order puts the executor into `error` and stops it, so it never keeps trading blind.

## Run it locally

You need **Python 3.11+**, **Node 18.17+** and **git**. [Ollama](https://ollama.com) is optional; without it Throne uses its offline parser.

**1. Get the code**

```bash
git clone https://github.com/Hijanhv/Throne.git
cd Throne
```

**2. (Optional) start the local LLM** in a separate terminal

```bash
ollama serve                  # skip if the Ollama app is already running
ollama pull tinyllama         # one time download, about 640 MB
```

**3. Start Throne**

```bash
./start.sh
```

The first run creates `.env` from `.env.example`, sets up a Python virtual environment, and installs the backend and frontend dependencies, which takes a few minutes. Later runs start in seconds. When you see

```
Backend:  http://localhost:8000  (docs at /docs)
Frontend: http://localhost:3000
```

**4. Open http://localhost:3000** in your browser. The top bar shows `OLLAMA: ONLINE` if the LLM is reachable.

**5. Try it:** click an example chip (for example *RSI mean reversion*), press **PARSE STRATEGY**, then **BACKTEST**. Open the **LIVE** tab and press **DEPLOY PAPER** to watch the paper executor.

**6. Stop** with `Ctrl+C` in the terminal running `start.sh`. This shuts down both servers.

### Running the two halves by hand

If `start.sh` does not suit your setup (for example on Windows without a bash shell), use two terminals:

```bash
# terminal 1: backend
cd backend
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn main:app --reload --port 8000

# terminal 2: frontend
cd frontend
npm install
npm run dev
```

API docs are at http://localhost:8000/docs.

### Tests and checks

```bash
cd backend && .venv/bin/python -m pytest       # 38 tests: parser, backtester, executor, API
cd frontend && npm run typecheck && npm run lint
```

### Troubleshooting

| Problem | Fix |
| --- | --- |
| `API OFFLINE` in the top bar | The backend is not running. Check the `start.sh` terminal for errors. |
| `Ollama: offline` | Run `ollama serve`. Throne still works, using the regex parser. |
| `address already in use` on 8000 or 3000 | Something else is using the port: `lsof -ti :8000 \| xargs kill` (same for 3000). |
| `No data from yfinance` | Check the symbol. NSE stocks need no suffix (`TCS`), indices are `NIFTY50`, `BANKNIFTY`, `SENSEX`. Yahoo also rate limits; wait a minute and retry. |
| `./start.sh: Permission denied` | `chmod +x start.sh` |

### Ollama

```bash
brew install ollama           # or the installer from ollama.com
ollama serve                  # listens on http://localhost:11434
ollama pull tinyllama
```

The top bar shows `OLLAMA: ONLINE` once the backend can reach it. Any model works: `ollama pull qwen2.5:1.5b` and set `OLLAMA_MODEL=qwen2.5:1.5b` for better JSON than tinyllama at a similar speed (1 to 3 seconds per parse on a laptop). Everything still works with Ollama switched off.

### Dhan API credentials (live mode only)

1. Open a Dhan account and log in at [web.dhan.co](https://web.dhan.co).
2. Go to **My Profile → Access DhanHQ APIs** and generate an access token. Copy your **Client ID** and the **Access Token**.
3. Put them in `.env` as `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN`. They are read from the environment only and never sent to the frontend.
4. Dhan identifies instruments by **security ID**, not ticker. Look one up in the scrip master at `https://images.dhan.co/api-data/api-scrip-master.csv` (NSE equity examples: RELIANCE `2885`, HDFCBANK `1333`, INFY `1594`, NIFTYBEES `10576`). Indices like NIFTY 50 cannot be bought directly, so to trade a NIFTY signal live, backtest on `NIFTY50` and deploy with an ETF such as NIFTYBEES.
5. In the LIVE tab, flip the toggle, enter the security ID and tick the confirmation box. The API refuses live deploys without credentials, a security ID, and `confirm_live: true`.

Access tokens expire. If live orders start failing with an auth error, generate a new token.

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
