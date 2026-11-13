from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.models import Daily, Signal, Weekly
from .engine import Bar, SignalPoint
from .models import BacktestRun


def load_theoretical_data(db: Session, run: BacktestRun):
    daily = db.scalars(
        select(Daily).where(
            Daily.index_id == run.index_id,
            Daily.trade_date >= run.start_date,
            Daily.trade_date <= run.end_date,
            Daily.session_complete.is_(True),
        ).order_by(Daily.trade_date)
    ).all()
    weekly = db.scalars(
        select(Weekly).where(
            Weekly.index_id == run.index_id,
            Weekly.is_complete.is_(True),
            Weekly.last_trade_date <= run.end_date,
        ).order_by(Weekly.week_start)
    ).all()
    signals = db.scalars(
        select(Signal).where(
            Signal.index_id == run.index_id,
            Signal.status == "CONFIRMED",
            Signal.week_start >= run.start_date,
            Signal.week_start <= run.end_date,
        ).order_by(Signal.week_start)
    ).all()
    if not daily:
        raise ValueError("所选区间没有完整的指数日线行情")

    week_by_start = {row.week_start: row for row in weekly}
    points = []
    for signal in signals:
        week = week_by_start.get(signal.week_start)
        if week is None:
            continue
        points.append(SignalPoint(signal.id, signal.week_start, week.last_trade_date, float(week.low_price)))
    bars = [Bar(row.trade_date, float(row.open_price), float(row.high_price), float(row.low_price), float(row.close_price)) for row in daily]
    completed_week_lows = [(row.last_trade_date, float(row.low_price)) for row in weekly]
    fingerprint = "|".join(f"{row.trade_date}:{row.open_price}:{row.high_price}:{row.low_price}:{row.close_price}" for row in daily)
    data_version = sha256(fingerprint.encode()).hexdigest()[:16]
    algorithm_versions = sorted({signal.algorithm_version for signal in signals})
    return bars, points, completed_week_lows, data_version, ",".join(algorithm_versions) or "1.0"
