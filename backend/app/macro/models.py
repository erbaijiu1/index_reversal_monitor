"""Isolated storage for market-cap/GDP inputs, derived metrics and macro backtests."""
from datetime import date, datetime
from sqlalchemy import Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ..core.db import Base

class MacroRawDaily(Base):
    __tablename__ = "t_macro_cap_gdp_raw"
    __table_args__ = (UniqueConstraint("market", "trade_date", name="uq_macro_raw_market_day"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(20), default="CN-A")
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_market_cap: Mapped[float] = mapped_column(Numeric(24, 4), nullable=False)
    reference_gdp: Mapped[float] = mapped_column(Numeric(24, 4), nullable=False)
    gdp_reference_year: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(120), nullable=False)
    provenance: Mapped[str] = mapped_column(String(30), default="UPSTREAM_SNAPSHOT")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class MacroIndicatorDaily(Base):
    __tablename__ = "t_macro_cap_gdp_indicator"
    __table_args__ = (UniqueConstraint("market", "trade_date", "version", name="uq_macro_indicator_day_version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(20), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    cap_to_gdp: Mapped[float] = mapped_column(Numeric(16, 8), nullable=False)
    version: Mapped[str] = mapped_column(String(24), default="v1")
    provenance: Mapped[str] = mapped_column(String(30), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class MacroBacktestRun(Base):
    __tablename__ = "t_macro_backtest_run"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    index_id: Mapped[int] = mapped_column(ForeignKey("t_index_info.id"))
    market: Mapped[str] = mapped_column(String(20), default="CN-A")
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    parameters: Mapped[dict] = mapped_column(JSON)
    provenance: Mapped[str] = mapped_column(String(30), nullable=False)
    summary: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class MacroBacktestDaily(Base):
    __tablename__ = "t_macro_backtest_daily"
    __table_args__ = (UniqueConstraint("run_id", "trade_date", name="uq_macro_bt_run_day"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("t_macro_backtest_run.id"))
    trade_date: Mapped[date] = mapped_column(Date)
    x: Mapped[float | None] = mapped_column(Numeric(16, 8), nullable=True)
    target_weight: Mapped[float] = mapped_column(Numeric(12, 8))
    actual_weight: Mapped[float] = mapped_column(Numeric(12, 8))
    cash: Mapped[float] = mapped_column(Numeric(22, 6))
    holding: Mapped[float] = mapped_column(Numeric(22, 6))
    nav: Mapped[float] = mapped_column(Numeric(22, 6))
    benchmark_nav: Mapped[float] = mapped_column(Numeric(22, 6))
    fee: Mapped[float] = mapped_column(Numeric(20, 6), default=0)
    action: Mapped[str] = mapped_column(String(20), default="HOLD")

class MacroBacktestTrade(Base):
    __tablename__ = "t_macro_backtest_trade"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("t_macro_backtest_run.id"))
    signal_date: Mapped[date] = mapped_column(Date)
    trade_date: Mapped[date] = mapped_column(Date)
    x: Mapped[float] = mapped_column(Numeric(16, 8))
    side: Mapped[str] = mapped_column(String(8))
    target_weight: Mapped[float] = mapped_column(Numeric(12, 8))
    price: Mapped[float] = mapped_column(Numeric(20, 6))
    quantity: Mapped[float] = mapped_column(Numeric(24, 8))
    fee: Mapped[float] = mapped_column(Numeric(20, 6))
