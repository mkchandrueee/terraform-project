"""FastAPI server: serves the dashboard and a JSON analysis endpoint."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .. import data
from ..analyze import analyze

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


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
