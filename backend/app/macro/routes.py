"""Macro dataset synchronization, indicator calculation and independent backtests."""
from datetime import date
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.db import get_db
from ..core.models import Daily, Index
from .backtest import IndicatorPoint, MarketBar, run_allocation_backtest
from .indicator import AllocationConfig
from .models import MacroBacktestDaily, MacroBacktestRun, MacroBacktestTrade, MacroIndicatorDaily, MacroRawDaily
from .sync import sync_native, calculate_indicators

router = APIRouter(prefix="/index-reversal/api/v1/macro", tags=["macro-cap-gdp"])

def admin(x_admin_token: str | None = Header(None)):
    if settings.admin_token == "CHANGE_ME" or x_admin_token != settings.admin_token:
        raise HTTPException(403, "Invalid admin token")

class SyncRequest(BaseModel):
    start_date: date
    end_date: date
    market: str = "CN-A"
    calendar_index_id: int = Field(..., gt=0, description="本项目已同步日线的指数ID，作为交易日历")

class BacktestRequest(BaseModel):
    index_id: int
    start_date: date
    end_date: date
    initial_capital: float = Field(1_000_000, gt=0)
    fee_ratio: float = Field(0.0003, ge=0, lt=0.1)
    slippage_ratio: float = Field(0.0005, ge=0, lt=0.1)
    cash_rate: float = Field(0.0, ge=0, le=0.5)
    rebalance_min_difference: float = Field(0.001, ge=0, le=0.5)
    floor: float = Field(0.20, ge=0, le=1)
    neutral: float = Field(0.40, ge=0, le=1)
    ceiling: float = Field(1.0, ge=0, le=1)
    buy_ratio: float = Field(2.0, gt=0)
    market: str = "CN-A"
    allow_unverified_history: bool = False

@router.post("/sync", dependencies=[Depends(admin)])
def synchronize(p: SyncRequest, db: Session = Depends(get_db)):
    if p.end_date < p.start_date:
        raise HTTPException(400, "end_date must be >= start_date")
    if not db.get(Index, p.calendar_index_id):
        raise HTTPException(404, "calendar index not found")
    try:
        stats = sync_native(db, p.start_date, p.end_date, p.calendar_index_id, p.market)
        db.commit()
        return {**stats, "market": p.market, "provenance": "RETROSPECTIVE_GDP",
                "next_step": "POST /macro/indicators/recalculate"}
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(502, f"native market data sync failed: {exc}") from exc

@router.post("/indicators/recalculate", dependencies=[Depends(admin)])
def recalculate(market: str = "CN-A", db: Session = Depends(get_db)):
    count = calculate_indicators(db, market)
    db.commit()
    return {"market": market, "calculated": count, "version": "v1"}

@router.get("/indicators")
def indicators(market: str = "CN-A", start: date | None = None, end: date | None = None, db: Session = Depends(get_db)):
    stmt = select(MacroIndicatorDaily).where(MacroIndicatorDaily.market == market, MacroIndicatorDaily.version == "v1")
    if start: stmt = stmt.where(MacroIndicatorDaily.trade_date >= start)
    if end: stmt = stmt.where(MacroIndicatorDaily.trade_date <= end)
    rows = db.scalars(stmt.order_by(MacroIndicatorDaily.trade_date.desc()).limit(5000)).all()
    cfg = AllocationConfig()
    from .indicator import target_weight
    return [{"date": r.trade_date, "x": float(r.cap_to_gdp), "target_weight": target_weight(float(r.cap_to_gdp), cfg),
             "provenance": r.provenance} for r in reversed(rows)]

@router.post("/backtests", dependencies=[Depends(admin)])
def backtest(p: BacktestRequest, db: Session = Depends(get_db)):
    if p.end_date <= p.start_date:
        raise HTTPException(400, "end_date must be after start_date")
    index = db.get(Index, p.index_id)
    if index is None:
        raise HTTPException(404, "index not found")
    cfg = AllocationConfig(floor=p.floor, neutral=p.neutral, ceiling=p.ceiling, buy_ratio=p.buy_ratio)
    try: cfg.validate()
    except ValueError as exc: raise HTTPException(400, str(exc))
    raw_rows = db.scalars(select(MacroRawDaily).where(
        MacroRawDaily.market == p.market, MacroRawDaily.trade_date >= p.start_date,
        MacroRawDaily.trade_date <= p.end_date,
    )).all()
    if not raw_rows:
        raise HTTPException(409, "macro data absent; run /sync before backtesting")
    provenances = sorted({r.provenance for r in raw_rows})
    if not p.allow_unverified_history and any(v != "POINT_IN_TIME_VERIFIED" for v in provenances):
        raise HTTPException(409, "GDP series not point-in-time verified. Pass allow_unverified_history=true for exploratory-only backtest.")
    bars_db = db.scalars(select(Daily).where(Daily.index_id == p.index_id,
        Daily.trade_date >= p.start_date, Daily.trade_date <= p.end_date,
        Daily.session_complete.is_(True)).order_by(Daily.trade_date)).all()
    bars = [MarketBar(r.trade_date, float(r.open_price), float(r.close_price)) for r in bars_db]
    indicators_db = db.scalars(select(MacroIndicatorDaily).where(
        MacroIndicatorDaily.market == p.market, MacroIndicatorDaily.version == "v1",
        MacroIndicatorDaily.trade_date >= p.start_date, MacroIndicatorDaily.trade_date <= p.end_date,
    ).order_by(MacroIndicatorDaily.trade_date)).all()
    indicator_points = [IndicatorPoint(r.trade_date, float(r.cap_to_gdp)) for r in indicators_db]
    try:
        result = run_allocation_backtest(bars, indicator_points, p.initial_capital, cfg,
            p.fee_ratio, p.slippage_ratio, p.cash_rate, p.rebalance_min_difference)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    run = MacroBacktestRun(index_id=p.index_id, market=p.market,
        start_date=p.start_date, end_date=p.end_date, parameters=p.model_dump(mode="json"),
        provenance=",".join(provenances), summary=result["summary"])
    db.add(run)
    db.flush()
    for row in result["equity"]:
        db.add(MacroBacktestDaily(run_id=run.id, **row))
    for trade in result["trades"]:
        db.add(MacroBacktestTrade(run_id=run.id, **trade))
    db.commit()
    return {"id": run.id, "summary": result["summary"], "trades": result["trades"],
            "provenance": provenances, "warning": "Exploratory backtest only: index prices are theoretical fills; history is not point-in-time audited."}

@router.get("/backtests")
def backtests(db: Session = Depends(get_db)):
    return [{"id": r.id, "index_id": r.index_id, "market": r.market, "summary": r.summary,
             "provenance": r.provenance, "start_date": r.start_date, "end_date": r.end_date}
            for r in db.scalars(select(MacroBacktestRun).order_by(MacroBacktestRun.id.desc()).limit(100))]

@router.get("/backtests/{run_id}/equity")
def backtest_equity(run_id: int, db: Session = Depends(get_db)):
    if db.get(MacroBacktestRun, run_id) is None:
        raise HTTPException(404, "backtest not found")
    return [{"date": r.trade_date, "x": float(r.x) if r.x is not None else None, "target_weight": float(r.target_weight),
             "actual_weight": float(r.actual_weight), "nav": float(r.nav),
             "benchmark_nav": float(r.benchmark_nav), "cash": float(r.cash), "holding": float(r.holding),
             "fee": float(r.fee), "action": r.action}
            for r in db.scalars(select(MacroBacktestDaily).where(
                MacroBacktestDaily.run_id == run_id).order_by(MacroBacktestDaily.trade_date))]

@router.get("/backtests/{run_id}/trades")
def backtest_trades(run_id: int, db: Session = Depends(get_db)):
    if db.get(MacroBacktestRun, run_id) is None:
        raise HTTPException(404, "backtest not found")
    return [{"signal_date": r.signal_date, "trade_date": r.trade_date,
             "x": float(r.x), "side": r.side, "target_weight": float(r.target_weight),
             "price": float(r.price), "quantity": float(r.quantity), "fee": float(r.fee)}
            for r in db.scalars(select(MacroBacktestTrade).where(
                MacroBacktestTrade.run_id == run_id).order_by(MacroBacktestTrade.trade_date, MacroBacktestTrade.id))]
