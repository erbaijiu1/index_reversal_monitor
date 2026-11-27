"""End-to-end pure macro indicator and portfolio invariants."""
from datetime import date, timedelta
import pytest
from app.macro.indicator import AllocationConfig, cap_gdp_ratio, target_weight
from app.macro.backtest import MarketBar, IndicatorPoint, run_allocation_backtest

def test_anchor_and_position_steps():
    assert cap_gdp_ratio(60, 100) == .6
    cfg = AllocationConfig()
    assert target_weight(.65, cfg) == .4
    assert target_weight(.39, cfg) == 1.
    assert target_weight(.91, cfg) == .2
    assert .4 < target_weight(.54, cfg) < target_weight(.44, cfg) < 1.

def test_future_price_cannot_affect_current_decision():
    bars = [MarketBar(date(2025, 1, d), 100, 100) for d in (2, 3, 6)]
    signals = [IndicatorPoint(date(2025,1,2), .39)]
    result = run_allocation_backtest(bars, signals, fee_ratio=0, slippage_ratio=0)
    assert result["equity"][0]["actual_weight"] == 0
    assert result["equity"][1]["actual_weight"] == 1
    assert result["trades"][0]["trade_date"] == date(2025,1,3)

def test_fee_and_falling_price_mark_to_market():
    bars = [MarketBar(date(2025,1,2),100,100),MarketBar(date(2025,1,3),100,90),
            MarketBar(date(2025,1,6),90,80)]
    result = run_allocation_backtest(bars,[IndicatorPoint(date(2025,1,2),.39)],
        initial_capital=1000,fee_ratio=.001,slippage_ratio=0)
    assert result["summary"]["final_capital"] < 1000
    assert result["summary"]["fee_total"] > 0
    assert result["summary"]["trade_count"] == 1

def test_validation():
    with pytest.raises(ValueError):
        cap_gdp_ratio(100,0)
    with pytest.raises(ValueError):
        target_weight(.5,AllocationConfig(floor=.7,neutral=.4))

def test_native_source_gdp_reference_lag():
    from app.macro.native_source import reference_gdp_year
    assert reference_gdp_year(date(2026, 1, 20)) is None
    assert reference_gdp_year(date(2026, 3, 1)) == 2025

def test_native_szse_source_normalizes_units(monkeypatch):
    import pandas as pd
    from app.macro import native_source
    class MockAk:
        @staticmethod
        def stock_szse_summary(date):
            return pd.DataFrame([
                {"证券类别": "债券", "总市值(亿元)": 999},
                {"证券类别": "股票", "总市值(亿元)": 1234.5},
            ])
    monkeypatch.setattr(native_source, "ak", MockAk)
    assert native_source.fetch_szse_cap(date(2026, 11, 20)) == 1234.5

def test_native_szse_rejects_unknown_units(monkeypatch):
    import pandas as pd
    from app.macro import native_source
    class MockAk:
        @staticmethod
        def stock_szse_summary(date):
            return pd.DataFrame([{"证券类别": "股票", "总市值": 1234.5}])
    monkeypatch.setattr(native_source, "ak", MockAk)
    with pytest.raises(ValueError):
        native_source.fetch_szse_cap(date(2026, 11, 20))
