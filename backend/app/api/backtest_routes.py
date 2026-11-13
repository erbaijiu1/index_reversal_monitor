from datetime import date, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..backtest.models import BacktestEquity, BacktestOrder, BacktestRun, BacktestTrade
from ..core.config import settings
from ..core.db import get_db
from ..core.models import Daily, Index, Signal, Weekly
from ..jobs.backtest_runner import execute_backtest

router = APIRouter(prefix="/index-reversal/api/v1/backtest", tags=["backtest"])


def auth(x_admin_token: str | None = Header(None)):
    if settings.admin_token == "CHANGE_ME" or x_admin_token != settings.admin_token:
        raise HTTPException(status_code=403, detail="Invalid admin token")


class BacktestRequest(BaseModel):
    index_id: int
    strategy: str = Field("A", pattern="^[ABC]$")
    start_date: date
    end_date: date
    initial_capital: float = Field(100000, gt=0)
    risk_ratio: float = Field(0.01, gt=0, le=1)
    max_position_ratio: float = Field(0.20, gt=0, le=1)
    max_stop_ratio: float = Field(0.08, gt=0, le=1)
    fee_ratio: float = Field(0.0003, ge=0, le=0.1)
    slippage_ratio: float = Field(0.0005, ge=0, le=0.1)
    take_profit_r: float = Field(2.0, gt=0, le=20)
    lot_size: int = Field(1, ge=1)


def _json(value):
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def _run_dict(run: BacktestRun):
    return {
        "id": run.id, "index_id": run.index_id, "strategy": run.strategy,
        "execution_mode": run.execution_mode, "start_date": run.start_date,
        "end_date": run.end_date, "initial_capital": float(run.initial_capital),
        "parameters": run.parameters, "signal_algorithm_version": run.signal_algorithm_version,
        "data_version": run.data_version, "status": run.status, "summary": run.summary,
        "error_message": run.error_message, "created_at": run.created_at,
        "finished_at": run.finished_at,
    }


def _require_run(db: Session, run_id: int) -> BacktestRun:
    run = db.get(BacktestRun, run_id)
    if not run:
        raise HTTPException(404, "backtest run not found")
    return run


@router.get("/instruments")
def instruments(db: Session = Depends(get_db)):
    """V1 validates the signal on theoretical indices; ETF execution can be added later."""
    return [{
        "index_id": x.id, "index_code": x.index_code, "index_name": x.index_name,
        "execution_mode": "INDEX_THEORETICAL", "enabled": x.enabled,
        "data_status": x.data_status,
    } for x in db.scalars(select(Index).where(Index.enabled.is_(True)).order_by(Index.id))]


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(auth)])
def create_run(p: BacktestRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    if not db.get(Index, p.index_id):
        raise HTTPException(404, "index not found")
    if p.end_date <= p.start_date:
        raise HTTPException(400, "end_date must be after start_date")
    parameters = {key: _json(value) for key, value in p.model_dump().items()}
    run = BacktestRun(
        index_id=p.index_id, strategy=p.strategy, execution_mode="INDEX_THEORETICAL",
        start_date=p.start_date, end_date=p.end_date, initial_capital=p.initial_capital,
        parameters=parameters, status="QUEUED",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    background_tasks.add_task(execute_backtest, run.id)
    return _run_dict(run)


@router.get("/runs")
def list_runs(db: Session = Depends(get_db)):
    return [_run_dict(x) for x in db.scalars(select(BacktestRun).order_by(BacktestRun.id.desc()).limit(100))]


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)):
    return _run_dict(_require_run(db, run_id))


@router.get("/runs/{run_id}/equity")
def get_equity(run_id: int, db: Session = Depends(get_db)):
    _require_run(db, run_id)
    return [{
        "trade_date": x.trade_date, "cash": float(x.cash),
        "position_value": float(x.position_value), "total_equity": float(x.total_equity),
        "net_value": float(x.net_value), "benchmark_net_value": float(x.benchmark_net_value),
        "drawdown": float(x.drawdown),
    } for x in db.scalars(select(BacktestEquity).where(BacktestEquity.run_id == run_id).order_by(BacktestEquity.trade_date))]


@router.get("/runs/{run_id}/candles")
def get_candles(run_id: int, period: str = "1d", db: Session = Depends(get_db)):
    """Return daily or weekly OHLC aggregated from the exact bars used by a run."""
    if period not in ("1d", "1w"):
        raise HTTPException(400, "period must be 1d or 1w")
    run = _require_run(db, run_id)
    rows = db.scalars(
        select(Daily).where(
            Daily.index_id == run.index_id,
            Daily.trade_date >= run.start_date,
            Daily.trade_date <= run.end_date,
            Daily.session_complete.is_(True),
        ).order_by(Daily.trade_date)
    ).all()
    if period == "1d":
        return [{
            "trade_date": x.trade_date, "first_trade_date": x.trade_date, "last_trade_date": x.trade_date,
            "open_price": float(x.open_price), "close_price": float(x.close_price),
            "low_price": float(x.low_price), "high_price": float(x.high_price),
        } for x in rows]

    weeks = []
    for row in rows:
        week_start = row.trade_date - timedelta(days=row.trade_date.weekday())
        if not weeks or weeks[-1]["trade_date"] != week_start:
            weeks.append({
                "trade_date": week_start, "first_trade_date": row.trade_date, "last_trade_date": row.trade_date,
                "open_price": float(row.open_price), "close_price": float(row.close_price),
                "low_price": float(row.low_price), "high_price": float(row.high_price),
            })
            continue
        week = weeks[-1]
        week["last_trade_date"] = row.trade_date
        week["close_price"] = float(row.close_price)
        week["low_price"] = min(week["low_price"], float(row.low_price))
        week["high_price"] = max(week["high_price"], float(row.high_price))
    return weeks


@router.get("/runs/{run_id}/trades")
def get_trades(run_id: int, db: Session = Depends(get_db)):
    _require_run(db, run_id)
    return [{
        "id": x.id, "signal_id": x.signal_id, "entry_date": x.entry_date,
        "exit_date": x.exit_date, "entry_price": float(x.entry_price),
        "exit_price": float(x.exit_price) if x.exit_price is not None else None,
        "quantity": float(x.quantity), "initial_stop": float(x.initial_stop),
        "exit_reason": x.exit_reason, "gross_pnl": float(x.gross_pnl) if x.gross_pnl is not None else None,
        "net_pnl": float(x.net_pnl) if x.net_pnl is not None else None,
        "total_fee": float(x.total_fee), "total_slippage": float(x.total_slippage),
        "return_ratio": float(x.return_ratio) if x.return_ratio is not None else None,
        "status": x.status,
    } for x in db.scalars(select(BacktestTrade).where(BacktestTrade.run_id == run_id).order_by(BacktestTrade.entry_date))]


@router.get("/runs/{run_id}/orders")
def get_orders(run_id: int, db: Session = Depends(get_db)):
    _require_run(db, run_id)
    orders = db.scalars(
        select(BacktestOrder).where(BacktestOrder.run_id == run_id).order_by(BacktestOrder.trade_date, BacktestOrder.id)
    ).all()
    signal_ids = {x.signal_id for x in orders}
    signal_weeks = dict(db.execute(select(Signal.id, Signal.week_start).where(Signal.id.in_(signal_ids))).all()) if signal_ids else {}
    return [{
        "id": x.id, "trade_id": x.trade_id, "signal_id": x.signal_id,
        "signal_week": signal_weeks.get(x.signal_id),
        "side": x.side, "order_type": x.order_type, "trade_date": x.trade_date,
        "trigger_price": float(x.trigger_price), "fill_price": float(x.fill_price),
        "quantity": float(x.quantity), "notional": float(x.notional),
        "fee": float(x.fee), "slippage": float(x.slippage), "reason": x.reason,
    } for x in orders]


@router.get("/runs/{run_id}/skipped")
def get_skipped(run_id: int, db: Session = Depends(get_db)):
    run = _require_run(db, run_id)
    skipped = (run.summary or {}).get("skipped", [])
    signal_ids = {x.get("signal_id") for x in skipped if x.get("signal_id") is not None}
    trade_dates = {date.fromisoformat(x["trade_date"]) if isinstance(x.get("trade_date"), str) else x.get("trade_date") for x in skipped if x.get("trade_date")}
    signals = {x.id: x for x in db.scalars(select(Signal).where(Signal.id.in_(signal_ids)))} if signal_ids else {}
    signal_weeks = {x.week_start for x in signals.values()}
    weeks = {(x.index_id, x.week_start): x for x in db.scalars(select(Weekly).where(Weekly.index_id == run.index_id, Weekly.week_start.in_(signal_weeks)))} if signal_weeks else {}
    daily = {x.trade_date: x for x in db.scalars(select(Daily).where(Daily.index_id == run.index_id, Daily.trade_date.in_(trade_dates)))} if trade_dates else {}
    slippage_ratio = float((run.parameters or {}).get("slippage_ratio", 0))
    max_stop_ratio = float((run.parameters or {}).get("max_stop_ratio", 0))
    result = []
    for item in skipped:
        trade_date = date.fromisoformat(item["trade_date"]) if isinstance(item.get("trade_date"), str) else item.get("trade_date")
        signal = signals.get(item.get("signal_id"))
        week = weeks.get((run.index_id, signal.week_start)) if signal else None
        bar = daily.get(trade_date)
        planned_entry = float(bar.open_price) * (1 + slippage_ratio) if bar else None
        initial_stop = float(week.low_price) if week else None
        stop_ratio = (planned_entry - initial_stop) / planned_entry if planned_entry and initial_stop and planned_entry > initial_stop else None
        result.append({
            **item, "trade_date": trade_date,
            "signal_week": signal.week_start if signal else None,
            "planned_entry_price": planned_entry, "initial_stop": initial_stop,
            "stop_ratio": stop_ratio, "max_stop_ratio": max_stop_ratio,
        })
    return result


@router.get("/compare")
def compare(run_ids: list[int] = Query(..., min_length=1, max_length=20), db: Session = Depends(get_db)):
    runs = db.scalars(select(BacktestRun).where(BacktestRun.id.in_(run_ids)).order_by(BacktestRun.id)).all()
    found = {run.id for run in runs}
    missing = [run_id for run_id in run_ids if run_id not in found]
    if missing:
        raise HTTPException(404, f"backtest runs not found: {missing}")
    return [_run_dict(run) for run in runs]
