from datetime import date
from math import isclose

from app.backtest.engine import Bar, SignalPoint, run_backtest


def d(day: int) -> date:
    return date(2024, 1, day)


def test_stop_wins_when_stop_and_target_are_both_touched():
    bars = [
        Bar(d(8), 100, 101, 99, 100),
        Bar(d(9), 100, 112, 94, 108),
    ]
    result = run_backtest(bars, [SignalPoint(1, d(1), d(5), 95)], "A", 100_000, fee_ratio=0, slippage_ratio=0)
    trade = result["trades"][0]
    assert trade.exit_reason == "STOP_LOSS"
    assert trade.exit_price == 95
    assert result["summary"]["final_capital"] == 99_000


def test_strategy_b_keeps_initial_quantity_and_accounts_for_both_sides_costs():
    bars = [
        Bar(d(8), 100, 101, 99, 100),
        Bar(d(9), 101, 111, 100.5, 109),
        Bar(d(10), 101, 102, 99, 100),
    ]
    result = run_backtest(bars, [SignalPoint(2, d(1), d(5), 95)], "B", 100_000, fee_ratio=0.001, slippage_ratio=0)
    trade = result["trades"][0]
    assert trade.quantity == 200
    assert trade.remaining_quantity == 0
    assert [order.order_type for order in result["orders"]] == ["ENTRY", "PARTIAL_TAKE_PROFIT", "EXIT"]
    expected_fees = 200 * 100 * 0.001 + 100 * 110 * 0.001 + 100 * 100 * 0.001
    assert isclose(trade.total_fee, expected_fees)
    assert isclose(trade.net_pnl, 100 * 10 - expected_fees)
    assert result["equity"][-1]["position_value"] == 0
    assert isclose(result["summary"]["final_capital"], result["equity"][-1]["cash"])


def test_future_weekly_lows_do_not_change_current_trailing_stop():
    bars = [
        Bar(d(8), 100, 101, 99, 100),
        Bar(d(9), 100, 102, 96, 101),
        Bar(d(10), 101, 103, 96, 102),
    ]
    result = run_backtest(
        bars, [SignalPoint(3, d(1), d(5), 95)], "C", 100_000,
        fee_ratio=0, slippage_ratio=0,
        completed_week_lows=[(d(12), 99), (d(19), 100)],
    )
    assert result["trades"][0].exit_reason == "END_OF_RANGE"


def test_gap_stop_uses_open_and_lot_rounding():
    bars = [Bar(d(8), 101, 102, 100, 101), Bar(d(9), 90, 92, 88, 91)]
    result = run_backtest(
        bars, [SignalPoint(4, d(1), d(5), 95)], "A", 100_000,
        fee_ratio=0, slippage_ratio=0, lot_size=100,
    )
    trade = result["trades"][0]
    assert trade.quantity == 100
    assert trade.exit_price == 90
    assert trade.exit_reason == "STOP_GAP"


def test_invalid_ohlc_is_rejected():
    try:
        Bar(d(8), 100, 99, 98, 100)
    except ValueError as error:
        assert "OHLC" in str(error)
    else:
        raise AssertionError("invalid OHLC was accepted")


def test_signal_close_entry_uses_close_and_buffered_signal_low():
    bars = [
        Bar(d(8), 98, 101, 97, 100),
        Bar(d(9), 101, 103, 100, 102),
    ]
    result = run_backtest(
        bars, [SignalPoint(5, d(8), d(8), 95)], "A", 100_000,
        fee_ratio=0, slippage_ratio=0, max_position_ratio=1,
        entry_timing="SIGNAL_CLOSE", stop_buffer_ratio=0.01,
    )

    trade = result["trades"][0]
    assert trade.entry_date == d(8)
    assert trade.entry_price == 100
    assert isclose(trade.initial_stop, 94.05)
    assert result["orders"][0].reason == "SIGNAL_CLOSE"


def test_stop_buffer_is_included_in_max_stop_filter():
    bars = [Bar(d(8), 98, 101, 97, 100), Bar(d(9), 100, 101, 99, 100)]
    result = run_backtest(
        bars, [SignalPoint(6, d(8), d(8), 95)], "A", 100_000,
        fee_ratio=0, slippage_ratio=0, entry_timing="SIGNAL_CLOSE",
        stop_buffer_ratio=0.10, max_stop_ratio=0.08,
    )

    assert result["trades"] == []
    assert result["skipped"][0]["reason"] == "STOP_DISTANCE_EXCEEDED"


def test_strategy_d_exits_next_open_after_signal_close_invalidation():
    bars = [
        Bar(d(8), 100, 101, 99, 100),
        Bar(d(9), 100, 101, 94, 94.5),
        Bar(d(10), 94, 96, 93, 95),
    ]
    result = run_backtest(
        bars, [SignalPoint(7, d(1), d(5), 95)], "D", 100_000,
        fee_ratio=0, slippage_ratio=0, stop_buffer_ratio=0.05,
        max_stop_ratio=0.12, signal_period="1d",
    )

    trade = result["trades"][0]
    assert trade.exit_date == d(10)
    assert trade.exit_price == 94
    assert trade.exit_reason == "SIGNAL_INVALIDATED_CLOSE"


def test_strategy_d_takes_quarter_at_2r_then_uses_weekly_close_exit():
    jan = lambda day: date(2024, 1, day)
    feb = lambda day: date(2024, 2, day)
    bars = [
        Bar(jan(8), 100, 101, 99, 100),
        Bar(jan(9), 101, 111, 100.5, 109),
        Bar(jan(12), 109, 110, 102, 108),
        Bar(jan(19), 108, 112, 105, 110),
        Bar(jan(26), 110, 113, 108, 111),
        Bar(feb(2), 110, 111, 101, 101),
        Bar(feb(5), 100.5, 102, 100.2, 101),
    ]
    result = run_backtest(
        bars, [SignalPoint(8, jan(1), jan(5), 95)], "D", 100_000,
        fee_ratio=0, slippage_ratio=0, signal_period="1w",
        completed_week_lows=[
            (jan(12), 102), (jan(19), 105), (jan(26), 108), (feb(2), 101),
        ],
    )

    assert [order.reason for order in result["orders"]] == [
        "SIGNAL_NEXT_OPEN", "TAKE_2R_QUARTER", "WEEKLY_TREND_EXIT",
    ]
    assert result["orders"][1].quantity == 50
    assert result["orders"][2].quantity == 150
    assert result["trades"][0].exit_date == feb(5)
