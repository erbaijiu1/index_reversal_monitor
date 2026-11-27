"""Portfolio backtest with next-session fills and explicit execution assumptions."""
from dataclasses import dataclass
from datetime import date
from math import sqrt
from .indicator import AllocationConfig, target_weight

@dataclass(frozen=True)
class MarketBar:
    trade_date: date
    open: float
    close: float

@dataclass(frozen=True)
class IndicatorPoint:
    trade_date: date
    value: float

def _metrics(equity: list[dict], initial_capital: float) -> dict:
    if not equity:
        raise ValueError("empty equity")
    navs = [row["nav"] for row in equity]
    peak = navs[0]
    mdd = 0.
    for value in navs:
        peak = max(peak, value)
        mdd = min(mdd, value / peak - 1)
    days = (equity[-1]["trade_date"] - equity[0]["trade_date"]).days
    years = days / 365.25
    cagr = (navs[-1] / initial_capital) ** (1 / years) - 1 if years > 0 else 0.
    return {"initial_capital": initial_capital, "final_capital": navs[-1],
            "cagr": cagr, "max_drawdown": mdd,
            "trading_days": len(equity), "start_date": equity[0]["trade_date"].isoformat(),
            "end_date": equity[-1]["trade_date"].isoformat()}

def run_allocation_backtest(
    bars: list[MarketBar], indicators: list[IndicatorPoint], initial_capital: float = 1_000_000,
    config: AllocationConfig = AllocationConfig(), fee_ratio: float = 0.0003,
    slippage_ratio: float = 0.0005, cash_rate: float = 0.0,
    rebalance_min_difference: float = 0.001,
) -> dict:
    """Signals observed at T close, orders filled at T+1 open (index-theoretical).

    Historical market-cap snapshots may not be point-in-time available at T close;
    the data provenance and this execution assumption are explicitly disclosed.
    """
    if initial_capital <= 0 or not 0 <= fee_ratio < 1 or not 0 <= slippage_ratio < 1 or cash_rate < 0:
        raise ValueError("invalid portfolio assumptions")
    config.validate()
    bars = sorted(bars, key=lambda x: x.trade_date)
    indicators = sorted(indicators, key=lambda x: x.trade_date)
    if len(bars) < 2 or not indicators:
        raise ValueError("at least two market bars and indicator data are required")
    if len({b.trade_date for b in bars}) != len(bars):
        raise ValueError("duplicate bar dates")
    if any(b.open <= 0 or b.close <= 0 for b in bars):
        raise ValueError("nonpositive price")
    values = {item.trade_date: item.value for item in indicators}
    # Important: no unbounded forward filling on missing indicator days.
    available = {day for day in values}
    cash = float(initial_capital)
    quantity = 0.0
    bench_quantity = 0.0
    benchmark_cash = float(initial_capital)
    pending = None
    equity = []
    trades = []
    previous_day = None
    for i, bar in enumerate(bars):
        day = bar.trade_date
        elapsed = (day - previous_day).days if previous_day else 0
        if elapsed > 0 and cash_rate:
            cash *= (1 + cash_rate) ** (elapsed / 365.25)
            benchmark_cash *= (1 + cash_rate) ** (elapsed / 365.25)
        previous_day = day
        fee = 0.0
        action = "HOLD"
        if i == 0:
            bench_execution = bar.open * (1 + slippage_ratio)
            bench_quantity = benchmark_cash / (bench_execution * (1 + fee_ratio))
            benchmark_cash -= bench_quantity * bench_execution * (1 + fee_ratio)
        if pending is not None:
            requested, signal_date, signal_x = pending
            price = bar.open
            nav_open = cash + quantity * price
            held_weight = quantity * price / nav_open if nav_open > 0 else 0
            if abs(requested - held_weight) >= rebalance_min_difference:
                target_value = requested * nav_open
                difference = target_value - quantity * price
                if difference > 0:
                    execution_price = price * (1 + slippage_ratio)
                    amount = min(difference, cash / (1 + fee_ratio))
                    purchase_qty = max(0, amount / execution_price)
                    cost = purchase_qty * execution_price
                    fee = cost * fee_ratio
                    cash -= cost + fee
                    quantity += purchase_qty
                    action = "BUY"
                elif difference < 0:
                    execution_price = price * (1 - slippage_ratio)
                    sale_qty = min(quantity, -difference / price)
                    proceeds = sale_qty * execution_price
                    fee = proceeds * fee_ratio
                    cash += proceeds - fee
                    quantity -= sale_qty
                    action = "SELL"
                if action != "HOLD":
                    trades.append({"signal_date": signal_date, "trade_date": day,
                                   "x": signal_x, "side": action, "target_weight": requested,
                                   "price": execution_price, "quantity": purchase_qty if action == "BUY" else sale_qty,
                                   "fee": fee})
            pending = None
        nav = cash + quantity * bar.close
        bench_nav = benchmark_cash + bench_quantity * bar.close
        actual_weight = quantity * bar.close / nav if nav > 0 else 0
        x = values.get(day)
        # Schedule at the close; never buy with this day's closing price.
        if x is not None:
            target = target_weight(x, config)
            pending = (target, day, x)
        equity.append({"trade_date": day, "x": x, "target_weight": pending[0] if pending else actual_weight,
                       "actual_weight": actual_weight, "cash": cash, "holding": quantity * bar.close,
                       "nav": nav, "benchmark_nav": bench_nav, "fee": fee, "action": action})
    summary = _metrics(equity, float(initial_capital))
    bench_metrics = _metrics([{"trade_date": row["trade_date"], "nav": row["benchmark_nav"]} for row in equity], float(initial_capital))
    summary.update({"benchmark_cagr": bench_metrics["cagr"], "benchmark_max_drawdown": bench_metrics["max_drawdown"],
                    "trade_count": len(trades), "fee_total": sum(t["fee"] for t in trades),
                    "execution_mode": "INDEX_THEORETICAL", "signal_timing": "T_CLOSE_NEXT_OPEN",
                    "indicator_provenance": "REQUIRES_POINT_IN_TIME_VALIDATION"})
    return {"summary": summary, "equity": equity, "trades": trades}
