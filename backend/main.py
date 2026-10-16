"""Throne API: natural language strategy -> rules -> backtest -> live or paper execution."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / ".env")

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from backtester import DataError, run_backtest  # noqa: E402
from dhan_client import DhanClient  # noqa: E402
from executor import StrategyExecutor  # noqa: E402
from models import (  # noqa: E402
    BacktestRequest,
    BacktestResult,
    DeployRequest,
    ExecutorStatus,
    ParsedStrategy,
    ParseRequest,
)
from parser import ollama_model, ollama_online, parse_strategy  # noqa: E402

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("throne")


@dataclass
class Entry:
    strategy: ParsedStrategy
    backtest: BacktestResult | None = None
    executor: StrategyExecutor | None = None
    task: asyncio.Task[None] | None = None


store: dict[str, Entry] = {}
dhan = DhanClient()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    for entry in store.values():
        if entry.executor:
            await entry.executor.stop()
        if entry.task:
            entry.task.cancel()


app = FastAPI(title="Throne", version="1.0.0", lifespan=lifespan)

_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    # lets a deployed https frontend call a backend on localhost under Chrome's private network rules
    allow_private_network=True,
)


def _get(strategy_id: str) -> Entry:
    entry = store.get(strategy_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown strategy {strategy_id}")
    return entry


class HealthResponse(BaseModel):
    status: str
    ollama: bool
    ollama_model: str
    dhan_configured: bool
    dhan_sandbox: bool
    strategies: int
    running: int


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        ollama=await ollama_online(),
        ollama_model=ollama_model(),
        dhan_configured=dhan.configured,
        dhan_sandbox=dhan.is_sandbox,
        strategies=len(store),
        running=sum(1 for e in store.values() if e.executor and e.executor.running),
    )


@app.post("/parse", response_model=ParsedStrategy)
async def parse(req: ParseRequest) -> ParsedStrategy:
    strategy = await parse_strategy(req.text, req.symbol, req.timeframe)
    store[strategy.id] = Entry(strategy=strategy)
    return strategy


@app.post("/backtest", response_model=BacktestResult)
async def backtest(req: BacktestRequest) -> BacktestResult:
    entry = _get(req.strategy_id)
    if not entry.strategy.rules:
        raise HTTPException(status_code=422, detail="Strategy has no rules to backtest")
    try:
        result = await asyncio.to_thread(
            run_backtest, entry.strategy, req.period, req.interval, req.initial_capital, req.fee_bps
        )
    except DataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    entry.backtest = result
    return result


class DeployResponse(BaseModel):
    status: str
    strategy_id: str
    mode: str


@app.post("/deploy", response_model=DeployResponse)
async def deploy(req: DeployRequest) -> DeployResponse:
    entry = _get(req.strategy_id)
    if entry.executor and entry.executor.running:
        raise HTTPException(status_code=409, detail="Strategy is already running")
    if not entry.strategy.rules:
        raise HTTPException(status_code=422, detail="Strategy has no rules")
    if req.mode == "live":
        if not dhan.configured:
            raise HTTPException(status_code=400, detail="Live mode needs DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in .env")
        if not req.security_id:
            raise HTTPException(status_code=400, detail="Live mode needs the Dhan security_id of the instrument")
        if not req.confirm_live:
            raise HTTPException(status_code=400, detail="Live mode places real orders; set confirm_live to true")

    executor = StrategyExecutor(
        entry.strategy,
        req.mode,
        req.capital,
        dhan,
        security_id=req.security_id,
        exchange_segment=req.exchange_segment,
        poll_seconds=req.poll_seconds,
    )
    entry.executor = executor
    entry.task = asyncio.create_task(executor.start(), name=f"executor-{req.strategy_id}")
    log.info("deployed %s in %s mode with capital %.2f", req.strategy_id, req.mode, req.capital)
    return DeployResponse(status="deployed", strategy_id=req.strategy_id, mode=req.mode)


@app.get("/status/{strategy_id}", response_model=ExecutorStatus)
async def status(strategy_id: str) -> ExecutorStatus:
    entry = _get(strategy_id)
    if entry.executor is None:
        raise HTTPException(status_code=404, detail="Strategy has not been deployed")
    return await entry.executor.get_status()


@app.post("/stop/{strategy_id}", response_model=ExecutorStatus)
async def stop(strategy_id: str) -> ExecutorStatus:
    entry = _get(strategy_id)
    if entry.executor is None:
        raise HTTPException(status_code=404, detail="Strategy has not been deployed")
    await entry.executor.stop()
    return await entry.executor.get_status()


@app.delete("/strategy/{strategy_id}")
async def delete_strategy(strategy_id: str) -> dict[str, str]:
    entry = _get(strategy_id)
    if entry.executor:
        await entry.executor.stop()
    if entry.task:
        entry.task.cancel()
    del store[strategy_id]
    return {"status": "deleted", "strategy_id": strategy_id}
