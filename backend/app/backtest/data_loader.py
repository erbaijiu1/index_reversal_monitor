from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.models import Daily, Signal, Weekly
from ..services.pattern import Rule, identify
from .engine import Bar, SignalPoint
from .models import BacktestRun


@dataclass(frozen=True)
class BreakoutPullbackRule:
    breakout_lookback: int = 20
    bottom_lookback: int = 60
    bottom_max_distance: float = 0.05
    breakout_level_tolerance: float = 0.005
    min_volume_ratio: float = 1.8
    min_body_ratio: float = 0.03
    min_body_to_range: float = 0.60
    min_close_location: float = 0.80
    max_pullback_days: int = 5
    pullback_level_tolerance: float = 0.01
    pullback_max_above_breakout_close: float = 0.03
    pullback_max_body_ratio: float = 0.01


def _daily_candle(row: Daily) -> dict:
    return {
        "open": row.open_price, "high": row.high_price,
        "low": row.low_price, "close": row.close_price,
        "volume": row.volume, "amount": row.amount,
        "is_complete": row.session_complete, "actual_sessions": 1,
    }


def detect_daily_signal_points(daily: list[Daily], rule: Rule, start_date, end_date) -> list[SignalPoint]:
    """Detect confirmed daily engulfment signals without writing monitor tables."""
    points = []
    window_size = max(rule.max_lookback, rule.volume_lookback) + 1
    for pos, row in enumerate(daily):
        if row.trade_date < start_date or row.trade_date > end_date:
            continue
        window = daily[max(0, pos - window_size + 1):pos + 1]
        outcome = identify([_daily_candle(item) for item in window], rule)
        if outcome and outcome["status"] == "CONFIRMED":
            points.append(SignalPoint(row.id, row.trade_date, row.trade_date, float(row.low_price)))
    return points


def detect_breakout_pullback_points(
    daily: list[Daily], rule: BreakoutPullbackRule, start_date, end_date,
) -> list[SignalPoint]:
    """Find rare bottom breakouts whose first shallow pullback holds the breakout level.

    A point is confirmed only at the pullback day's close. The engine therefore
    enters no earlier than the next session and does not use future information.
    """
    points: list[SignalPoint] = []
    pos = rule.bottom_lookback
    while pos < len(daily) - 1:
        breakout = daily[pos]
        prior_bottom = daily[pos - rule.bottom_lookback:pos]
        prior_breakout = daily[pos - rule.breakout_lookback:pos]
        if breakout.trade_date > end_date:
            break

        o, h, low, close = map(float, (
            breakout.open_price, breakout.high_price, breakout.low_price, breakout.close_price,
        ))
        price_range = h - low
        prior_volumes = [float(row.volume) for row in prior_breakout if row.volume is not None]
        average_volume = sum(prior_volumes) / len(prior_volumes) if len(prior_volumes) == len(prior_breakout) else 0
        breakout_level = max(float(row.high_price) for row in prior_breakout)
        bottom_low = min(float(row.low_price) for row in prior_bottom)
        previous_close = float(daily[pos - 1].close_price)
        is_breakout = (
            close > o
            and previous_close <= bottom_low * (1 + rule.bottom_max_distance)
            and close >= breakout_level * (1 - rule.breakout_level_tolerance)
            and average_volume > 0
            and breakout.volume is not None
            and float(breakout.volume) / average_volume >= rule.min_volume_ratio
            and (close - o) / o >= rule.min_body_ratio
            and price_range > 0
            and (close - o) / price_range >= rule.min_body_to_range
            and (close - low) / price_range >= rule.min_close_location
        )
        if not is_breakout:
            pos += 1
            continue

        pullback_pos = None
        last_pos = min(pos + rule.max_pullback_days, len(daily) - 1)
        for candidate_pos in range(pos + 1, last_pos + 1):
            candidate = daily[candidate_pos]
            candidate_open = float(candidate.open_price)
            candidate_close = float(candidate.close_price)
            candidate_low = float(candidate.low_price)
            if candidate_close < breakout_level * (1 - rule.pullback_level_tolerance):
                break
            if (
                candidate_low <= close * (1 + rule.pullback_max_above_breakout_close)
                and candidate_close <= close * (1 + rule.pullback_max_above_breakout_close)
                and abs(candidate_close - candidate_open) / candidate_open <= rule.pullback_max_body_ratio
            ):
                pullback_pos = candidate_pos
                break

        if pullback_pos is None:
            pos += 1
            continue

        pullback = daily[pullback_pos]
        if start_date <= pullback.trade_date <= end_date:
            structural_low = min(float(pullback.low_price), breakout_level)
            points.append(SignalPoint(
                pullback.id, pullback.trade_date, pullback.trade_date, structural_low,
            ))
        pos = pullback_pos + 1
    return points


def _daily_rule(parameters: dict) -> Rule:
    values = parameters.get("signal_rule") or {}
    return Rule(
        min_engulfed=int(values.get("min_engulfed", 2)),
        min_bearish=int(values.get("min_bearish", 2)),
        max_lookback=int(values.get("max_lookback", 26)),
        volume_lookback=int(values.get("volume_lookback", 5)),
        volume_warm=Decimal(str(values.get("volume_warm", 1.2))),
        volume_strong=Decimal(str(values.get("volume_strong", 1.5))),
    )


def _breakout_pullback_rule(parameters: dict) -> BreakoutPullbackRule:
    values = parameters.get("breakout_pullback_rule") or {}
    return BreakoutPullbackRule(**{
        key: values.get(key, field.default)
        for key, field in BreakoutPullbackRule.__dataclass_fields__.items()
    })


def load_theoretical_data(db: Session, run: BacktestRun):
    all_daily = db.scalars(
        select(Daily).where(
            Daily.index_id == run.index_id,
            Daily.trade_date <= run.end_date,
            Daily.session_complete.is_(True),
        ).order_by(Daily.trade_date)
    ).all()
    daily = [row for row in all_daily if row.trade_date >= run.start_date]
    weekly = db.scalars(
        select(Weekly).where(
            Weekly.index_id == run.index_id,
            Weekly.is_complete.is_(True),
            Weekly.last_trade_date <= run.end_date,
        ).order_by(Weekly.week_start)
    ).all()
    if not daily:
        raise ValueError("所选区间没有完整的指数日线行情")

    parameters = run.parameters or {}
    signal_period = parameters.get("signal_period", "1w")
    signal_mode = parameters.get("signal_mode", "ENGULFING")
    if signal_mode == "BREAKOUT_PULLBACK":
        points = detect_breakout_pullback_points(
            all_daily, _breakout_pullback_rule(parameters), run.start_date, run.end_date,
        )
        algorithm_version = "breakout-pullback-1.0"
    elif signal_period == "1d":
        points = detect_daily_signal_points(all_daily, _daily_rule(run.parameters or {}), run.start_date, run.end_date)
        algorithm_version = "daily-1.0"
    else:
        signals = db.scalars(
            select(Signal).where(
                Signal.index_id == run.index_id,
                Signal.status == "CONFIRMED",
                Signal.week_start >= run.start_date,
                Signal.week_start <= run.end_date,
            ).order_by(Signal.week_start)
        ).all()
        week_by_start = {row.week_start: row for row in weekly}
        points = []
        for signal in signals:
            week = week_by_start.get(signal.week_start)
            if week is not None:
                points.append(SignalPoint(signal.id, signal.week_start, week.last_trade_date, float(week.low_price)))
        versions = sorted({signal.algorithm_version for signal in signals})
        algorithm_version = ",".join(versions) or "1.0"

    bars = [Bar(row.trade_date, float(row.open_price), float(row.high_price), float(row.low_price), float(row.close_price)) for row in daily]
    # B/C remain weekly trailing-stop strategies even when entries use daily signals.
    completed_week_lows = [(row.last_trade_date, float(row.low_price)) for row in weekly]
    fingerprint = "|".join(f"{row.trade_date}:{row.open_price}:{row.high_price}:{row.low_price}:{row.close_price}" for row in daily)
    data_version = sha256(fingerprint.encode()).hexdigest()[:16]
    return bars, points, completed_week_lows, data_version, algorithm_version
