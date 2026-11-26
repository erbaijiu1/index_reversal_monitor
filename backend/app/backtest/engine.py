from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from math import floor, sqrt
from statistics import mean, stdev
from typing import Any


@dataclass(frozen=True)
class Bar:
    trade_date: date
    open: float
    high: float
    low: float
    close: float

    def __post_init__(self):
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError(f"invalid non-positive price on {self.trade_date}")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError(f"invalid OHLC relationship on {self.trade_date}")


@dataclass(frozen=True)
class SignalPoint:
    signal_id: int
    week_start: date
    week_last_date: date
    week_low: float


@dataclass
class SimOrder:
    side: str
    order_type: str
    trade_date: date
    trigger_price: float
    fill_price: float
    quantity: float
    notional: float
    fee: float
    slippage: float
    reason: str
    signal_id: int


@dataclass
class SimTrade:
    signal_id: int
    entry_date: date
    entry_price: float
    quantity: float
    initial_stop: float
    entry_fee: float
    entry_slippage: float
    remaining_quantity: float
    exit_date: date | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    gross_pnl: float | None = None
    net_pnl: float | None = None
    total_fee: float = 0.0
    total_slippage: float = 0.0
    _exit_notional: float = field(default=0.0, repr=False)
    _exit_quantity: float = field(default=0.0, repr=False)
    _realized_gross: float = field(default=0.0, repr=False)


def _slipped(price: float, ratio: float, side: str) -> float:
    return price * (1 + ratio) if side == "BUY" else price * (1 - ratio)


def _annualized_return(total_return: float, first: date, last: date) -> float:
    years = max((last - first).days / 365.25, 1 / 365.25)
    return (1 + total_return) ** (1 / years) - 1 if total_return > -1 else -1.0


def _metrics(equity: list[dict[str, Any]], trades: list[SimTrade], initial_capital: float, benchmark: float) -> dict[str, Any]:
    final_capital = equity[-1]["total_equity"]
    total_return = final_capital / initial_capital - 1
    max_drawdown = min((row["drawdown"] for row in equity), default=0.0)
    closed = [trade for trade in trades if trade.exit_date is not None]
    wins = [trade for trade in closed if (trade.net_pnl or 0) > 0]
    gains = sum(max(trade.net_pnl or 0, 0) for trade in closed)
    losses = abs(sum(min(trade.net_pnl or 0, 0) for trade in closed))
    daily_returns = [equity[i]["total_equity"] / equity[i - 1]["total_equity"] - 1 for i in range(1, len(equity)) if equity[i - 1]["total_equity"]]
    volatility = stdev(daily_returns) * sqrt(252) if len(daily_returns) > 1 else 0.0
    sharpe = mean(daily_returns) / stdev(daily_returns) * sqrt(252) if len(daily_returns) > 1 and stdev(daily_returns) else 0.0
    annualized = _annualized_return(total_return, equity[0]["trade_date"], equity[-1]["trade_date"])
    return {
        "initial_capital": initial_capital, "final_capital": final_capital,
        "total_return": total_return, "annualized_return": annualized,
        "benchmark_return": benchmark, "max_drawdown": max_drawdown,
        "calmar": annualized / abs(max_drawdown) if max_drawdown else None,
        "annualized_volatility": volatility, "sharpe": sharpe,
        "trade_count": len(closed), "win_count": len(wins),
        "win_rate": len(wins) / len(closed) if closed else 0.0,
        "profit_factor": gains / losses if losses else (None if not gains else 999.0),
        "total_fees": sum(trade.total_fee for trade in closed),
        "total_slippage": sum(trade.total_slippage for trade in closed),
    }


def run_backtest(
    bars: list[Bar], signals: list[SignalPoint], strategy: str, initial_capital: float,
    risk_ratio: float = 0.01, max_position_ratio: float = 0.20,
    max_stop_ratio: float = 0.08, fee_ratio: float = 0.0003,
    slippage_ratio: float = 0.0005, completed_week_lows: list[tuple[date, float]] | None = None,
    take_profit_r: float = 2.0, lot_size: int = 1,
    entry_timing: str = "NEXT_OPEN", stop_buffer_ratio: float = 0.0,
    signal_period: str = "1w",
) -> dict[str, Any]:
    """Run one-index account simulation without using future weekly data."""
    if strategy not in {"A", "B", "C", "D"}:
        raise ValueError("strategy must be A, B, C or D")
    if initial_capital <= 0 or not 0 < risk_ratio <= 1 or not 0 < max_position_ratio <= 1:
        raise ValueError("invalid capital or position parameters")
    if not 0 < max_stop_ratio <= 1 or min(fee_ratio, slippage_ratio) < 0 or lot_size < 1:
        raise ValueError("invalid execution parameters")
    if entry_timing not in {"NEXT_OPEN", "SIGNAL_CLOSE"}:
        raise ValueError("entry_timing must be NEXT_OPEN or SIGNAL_CLOSE")
    if not 0 <= stop_buffer_ratio <= 0.5:
        raise ValueError("stop_buffer_ratio must be between 0 and 0.5")
    if signal_period not in {"1d", "1w"}:
        raise ValueError("signal_period must be 1d or 1w")

    bars = sorted(bars, key=lambda x: x.trade_date)
    signals = sorted(signals, key=lambda x: (x.week_last_date, x.signal_id))
    weekly_lows = sorted(completed_week_lows or [], key=lambda item: item[0])
    if not bars:
        raise ValueError("no daily bars in selected range")
    if len({bar.trade_date for bar in bars}) != len(bars):
        raise ValueError("duplicate daily bars")

    cash = float(initial_capital)
    peak = float(initial_capital)
    equity_rows: list[dict[str, Any]] = []
    orders: list[SimOrder] = []
    trades: list[SimTrade] = []
    skipped: list[dict[str, Any]] = []
    position: SimTrade | None = None
    stop = 0.0
    target: float | None = None
    signal_index = 0
    raw_signal_low = 0.0
    trend_active = False
    pending_exit_reason: str | None = None
    completed_week_dates = {week_end for week_end, _ in weekly_lows}

    def sell(bar: Bar, trigger: float, qty: float, order_type: str, reason: str) -> None:
        nonlocal cash, position
        assert position is not None
        fill = _slipped(trigger, slippage_ratio, "SELL")
        notional = qty * fill
        fee = notional * fee_ratio
        slippage = qty * max(trigger - fill, 0)
        cash += notional - fee
        position.remaining_quantity -= qty
        position._exit_notional += notional
        position._exit_quantity += qty
        position._realized_gross += (fill - position.entry_price) * qty
        position.total_fee += fee
        position.total_slippage += slippage
        orders.append(SimOrder("SELL", order_type, bar.trade_date, trigger, fill, qty, notional, fee, slippage, reason, position.signal_id))
        if position.remaining_quantity <= 1e-10:
            position.remaining_quantity = 0.0
            position.exit_date = bar.trade_date
            position.exit_price = position._exit_notional / position._exit_quantity
            position.exit_reason = reason
            position.gross_pnl = position._realized_gross
            position.net_pnl = position.gross_pnl - position.total_fee
            position = None

    for bar_index, bar in enumerate(bars):
        if position is not None and pending_exit_reason is not None:
            sell(bar, bar.open, position.remaining_quantity, "EXIT", pending_exit_reason)
            pending_exit_reason = None

        if position is not None and strategy in {"B", "C"}:
            eligible = [low for week_end, low in weekly_lows if week_end < bar.trade_date]
            if len(eligible) >= 2:
                stop = max(stop, min(eligible[-2:]))

        # Stop is deliberately evaluated before a same-day profit target.
        if position is not None and bar.trade_date > position.entry_date:
            if bar.open <= stop:
                sell(bar, bar.open, position.remaining_quantity, "EXIT", "STOP_GAP" if stop == position.initial_stop else "TRAILING_STOP_GAP")
            elif bar.low <= stop:
                sell(bar, stop, position.remaining_quantity, "EXIT", "STOP_LOSS" if stop == position.initial_stop else "TRAILING_STOP")
            elif strategy == "A" and target is not None and bar.open >= target:
                sell(bar, bar.open, position.remaining_quantity, "EXIT", "TAKE_PROFIT_GAP")
            elif strategy == "A" and target is not None and bar.high >= target:
                sell(bar, target, position.remaining_quantity, "EXIT", "TAKE_PROFIT")
            elif strategy == "B" and target is not None and bar.open >= target:
                sell(bar, bar.open, position.remaining_quantity / 2, "PARTIAL_TAKE_PROFIT", "TAKE_2R_HALF_GAP")
                target = None
                stop = max(stop, position.entry_price) if position else stop
            elif strategy == "B" and target is not None and bar.high >= target:
                sell(bar, target, position.remaining_quantity / 2, "PARTIAL_TAKE_PROFIT", "TAKE_2R_HALF")
                target = None
                stop = max(stop, position.entry_price) if position else stop
            elif strategy == "D" and target is not None and bar.open >= target:
                sell(bar, bar.open, position.remaining_quantity / 4, "PARTIAL_TAKE_PROFIT", "TAKE_2R_QUARTER_GAP")
                target = None
                trend_active = position is not None
                stop = max(stop, position.entry_price) if position else stop
            elif strategy == "D" and target is not None and bar.high >= target:
                sell(bar, target, position.remaining_quantity / 4, "PARTIAL_TAKE_PROFIT", "TAKE_2R_QUARTER")
                target = None
                trend_active = position is not None
                stop = max(stop, position.entry_price) if position else stop

        signal_due = lambda point: (
            point.week_last_date <= bar.trade_date
            if entry_timing == "SIGNAL_CLOSE"
            else point.week_last_date < bar.trade_date
        )
        while signal_index < len(signals) and signal_due(signals[signal_index]):
            point = signals[signal_index]
            signal_index += 1
            # A signal-close entry is due on its confirmation bar; next-open is
            # due only on the first available bar after confirmation.
            if entry_timing == "SIGNAL_CLOSE" and point.week_last_date < bar.trade_date:
                continue
            if entry_timing == "NEXT_OPEN" and bar_index and bars[bar_index - 1].trade_date > point.week_last_date:
                continue
            if position is not None:
                skipped.append({"signal_id": point.signal_id, "reason": "POSITION_ALREADY_OPEN", "trade_date": bar.trade_date})
                continue
            entry_trigger = bar.close if entry_timing == "SIGNAL_CLOSE" else bar.open
            entry_fill = _slipped(entry_trigger, slippage_ratio, "BUY")
            initial_stop = float(point.week_low) * (1 - stop_buffer_ratio)
            if initial_stop <= 0 or entry_fill <= initial_stop:
                skipped.append({"signal_id": point.signal_id, "reason": "INVALID_STOP", "trade_date": bar.trade_date})
                continue
            stop_ratio = (entry_fill - initial_stop) / entry_fill
            if stop_ratio > max_stop_ratio:
                skipped.append({"signal_id": point.signal_id, "reason": "STOP_DISTANCE_EXCEEDED", "trade_date": bar.trade_date})
                continue
            account_equity = cash
            raw_quantity = min(account_equity * risk_ratio / (entry_fill - initial_stop), account_equity * max_position_ratio / entry_fill, cash / (entry_fill * (1 + fee_ratio)))
            quantity = floor(raw_quantity / lot_size) * lot_size
            if quantity <= 0:
                skipped.append({"signal_id": point.signal_id, "reason": "INSUFFICIENT_CASH_OR_LOT", "trade_date": bar.trade_date})
                continue
            notional = quantity * entry_fill
            fee = notional * fee_ratio
            slippage = quantity * max(entry_fill - entry_trigger, 0)
            cash -= notional + fee
            position = SimTrade(point.signal_id, bar.trade_date, entry_fill, quantity, initial_stop, fee, slippage, quantity, total_fee=fee, total_slippage=slippage)
            trades.append(position)
            stop = initial_stop
            raw_signal_low = float(point.week_low)
            trend_active = False
            pending_exit_reason = None
            target = entry_fill + take_profit_r * (entry_fill - initial_stop)
            entry_reason = "SIGNAL_CLOSE" if entry_timing == "SIGNAL_CLOSE" else "SIGNAL_NEXT_OPEN"
            orders.append(SimOrder("BUY", "ENTRY", bar.trade_date, entry_trigger, entry_fill, quantity, notional, fee, slippage, entry_reason, point.signal_id))
            break

        if position is not None and strategy == "D" and bar.trade_date > position.entry_date:
            signal_period_closed = signal_period == "1d" or bar.trade_date in completed_week_dates
            if not trend_active and signal_period_closed and bar.close < raw_signal_low:
                pending_exit_reason = "SIGNAL_INVALIDATED_CLOSE"
            elif trend_active and bar.trade_date in completed_week_dates:
                prior_lows = [low for week_end, low in weekly_lows if week_end < bar.trade_date]
                if len(prior_lows) >= 3 and bar.close < min(prior_lows[-3:]):
                    pending_exit_reason = "WEEKLY_TREND_EXIT"

        if position is not None and bar_index == len(bars) - 1:
            sell(bar, bar.close, position.remaining_quantity, "EXIT", "END_OF_RANGE")

        position_value = position.remaining_quantity * bar.close if position else 0.0
        total = cash + position_value
        peak = max(peak, total)
        equity_rows.append({"trade_date": bar.trade_date, "cash": cash, "position_value": position_value, "total_equity": total, "net_value": total / initial_capital, "drawdown": total / peak - 1, "benchmark_close": bar.close})

    for point in signals[signal_index:]:
        skipped.append({"signal_id": point.signal_id, "reason": "NO_NEXT_TRADING_BAR", "trade_date": None})
    benchmark = bars[-1].close / bars[0].open - 1
    summary = _metrics(equity_rows, trades, initial_capital, benchmark)
    summary["skipped_count"] = len(skipped)
    return {"orders": orders, "trades": trades, "equity": equity_rows, "skipped": skipped, "summary": summary, "benchmark_start_price": bars[0].open}
