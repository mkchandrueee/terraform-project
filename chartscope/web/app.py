"""FastAPI server: serves the dashboard and a JSON analysis endpoint."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import threading
import time

from .. import data
from ..analyze import analyze
from ..options import contracts, engine
from ..options.monitor import Store

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="ChartScope", version="0.1.0")


@app.get("/api/analyze")
def api_analyze(
    symbol: str = Query(..., min_length=1, max_length=24, pattern=r"^[A-Za-z0-9.^&=\-]+$"),
    interval: str = "15m",
    capital: float = Query(100_000, gt=0, le=1e10),
    risk_pct: float = Query(1.0, gt=0, le=10),
):
    if interval not in data.INTERVALS:
        raise HTTPException(400, f"interval must be one of {list(data.INTERVALS)}")
    try:
        return analyze(symbol, interval, capital, risk_pct)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except Exception as e:  # upstream data hiccups shouldn't 500 the UI silently
        raise HTTPException(502, f"Analysis failed: {e}")


_STORE = Store()
_LOCK = threading.Lock()
_BT: dict[tuple, tuple[float, dict]] = {}


def _und(u: str) -> str:
    u = u.upper()
    if u not in contracts.SPECS:
        raise HTTPException(400, f"underlying must be one of {sorted(contracts.SPECS)}")
    return u


@app.get("/api/options/live")
def api_options_live(underlying: str = "NIFTY", capital: float = Query(300_000, gt=0, le=1e9), risk_pct: float = Query(1.0, gt=0, le=5)):
    u = _und(underlying)
    try:
        with _LOCK:  # calls are stateful: one refresh at a time
            return engine.refresh(u, _STORE, capital, risk_pct)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(502, f"Options refresh failed: {e}")


@app.get("/api/options/backtest")
def api_options_backtest(underlying: str = "NIFTY", days: int = Query(45, ge=5, le=60), capital: float = Query(300_000, gt=0, le=1e9),
                         risk_pct: float = Query(1.0, gt=0, le=5)):
    u = _und(underlying)
    key = (u, days, capital, risk_pct)
    hit = _BT.get(key)
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    try:
        res = engine.backtest(u, days, capital, risk_pct)
    except Exception as e:
        raise HTTPException(502, f"Backtest failed: {e}")
    _BT[key] = (time.time(), res)
    return res


@app.get("/options")
def options_page():
    return FileResponse(STATIC / "options.html")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
