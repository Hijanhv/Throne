import pytest
from fastapi.testclient import TestClient

import backtester
import executor
import main


@pytest.fixture
def client(monkeypatch, frame):
    import numpy as np

    rng = np.random.default_rng(3)
    closes = list(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 300))))
    fake = lambda symbol, period, interval, **kw: frame(closes)  # noqa: E731
    monkeypatch.setattr(backtester, "fetch_ohlcv", fake)
    monkeypatch.setattr(executor, "fetch_ohlcv", fake)
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(main.dhan, "client_id", "")
    main.store.clear()
    with TestClient(main.app) as c:
        yield c


def test_full_flow(client):
    assert client.get("/health").json()["ollama"] is False

    s = client.post(
        "/parse",
        json={"text": "Buy when RSI drops below 35. Sell when RSI exceeds 65. 3% stop loss", "symbol": "RELIANCE"},
    ).json()
    assert s["parser"] == "regex" and len(s["rules"]) == 2 and s["stop_loss_pct"] == 3

    bt = client.post("/backtest", json={"strategy_id": s["id"]}).json()
    assert bt["total_trades"] > 0 and 250 <= len(bt["equity_curve"]) < 300  # last year only, rest is warmup

    r = client.post("/deploy", json={"strategy_id": s["id"], "mode": "paper", "capital": 50000})
    assert r.status_code == 200 and r.json()["status"] == "deployed"
    assert client.post("/deploy", json={"strategy_id": s["id"], "mode": "paper", "capital": 50000}).status_code == 409

    st = client.get(f"/status/{s['id']}").json()
    assert st["mode"] == "paper" and st["status"] in ("running", "stopped")

    assert client.post(f"/stop/{s['id']}").json()["status"] == "stopped"
    assert client.delete(f"/strategy/{s['id']}").status_code == 200
    assert client.get(f"/status/{s['id']}").status_code == 404


def test_live_requires_credentials(client):
    s = client.post("/parse", json={"text": "Buy when RSI is below 30. Sell when RSI is above 70"}).json()
    r = client.post(
        "/deploy",
        json={"strategy_id": s["id"], "mode": "live", "capital": 1000, "security_id": "1333", "confirm_live": True},
    )
    assert r.status_code == 400 and "DHAN" in r.json()["detail"]


def test_validation_errors(client):
    assert client.post("/parse", json={"text": ""}).status_code == 422
    assert client.post("/backtest", json={"strategy_id": "nope"}).status_code == 404
    assert client.post("/deploy", json={"strategy_id": "x", "mode": "paper", "capital": -5}).status_code == 422


def test_private_network_preflight(client):
    r = client.options(
        "/health",
        headers={
            "Origin": "https://throne.vercel.app",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Private-Network": "true",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-private-network"] == "true"
    assert r.headers["access-control-allow-origin"] == "*"
