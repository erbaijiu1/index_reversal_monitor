from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.mysql import BIGINT
from ..core.db import Base


class BacktestRun(Base):
    __tablename__ = "t_backtest_run"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    index_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey("t_index_info.id"))
    strategy: Mapped[str] = mapped_column(String(8))
    execution_mode: Mapped[str] = mapped_column(String(24), default="INDEX_THEORETICAL")
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    initial_capital: Mapped[float] = mapped_column(Numeric(20, 6))
    parameters: Mapped[dict] = mapped_column(JSON)
    signal_algorithm_version: Mapped[str] = mapped_column(String(32), default="1.0")
    data_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="QUEUED")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class BacktestOrder(Base):
    __tablename__ = "t_backtest_order"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("t_backtest_run.id"))
    trade_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    signal_id: Mapped[int] = mapped_column(BIGINT(unsigned=True))
    side: Mapped[str] = mapped_column(String(8))
    order_type: Mapped[str] = mapped_column(String(24))
    trade_date: Mapped[date] = mapped_column(Date)
    trigger_price: Mapped[float] = mapped_column(Numeric(20, 6))
    fill_price: Mapped[float] = mapped_column(Numeric(20, 6))
    quantity: Mapped[float] = mapped_column(Numeric(28, 8))
    notional: Mapped[float] = mapped_column(Numeric(20, 6))
    fee: Mapped[float] = mapped_column(Numeric(20, 6), default=0)
    slippage: Mapped[float] = mapped_column(Numeric(20, 6), default=0)
    reason: Mapped[str] = mapped_column(String(64))


class BacktestTrade(Base):
    __tablename__ = "t_backtest_trade"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("t_backtest_run.id"))
    signal_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey("t_index_reversal_signal.id"))
    entry_date: Mapped[date] = mapped_column(Date)
    exit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    entry_price: Mapped[float] = mapped_column(Numeric(20, 6))
    exit_price: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    quantity: Mapped[float] = mapped_column(Numeric(28, 8))
    initial_stop: Mapped[float] = mapped_column(Numeric(20, 6))
    exit_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gross_pnl: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    net_pnl: Mapped[float | None] = mapped_column(Numeric(20, 6), nullable=True)
    total_fee: Mapped[float] = mapped_column(Numeric(20, 6), default=0)
    total_slippage: Mapped[float] = mapped_column(Numeric(20, 6), default=0)
    return_ratio: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="OPEN")


class BacktestEquity(Base):
    __tablename__ = "t_backtest_equity"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("t_backtest_run.id"))
    trade_date: Mapped[date] = mapped_column(Date)
    cash: Mapped[float] = mapped_column(Numeric(20, 6))
    position_value: Mapped[float] = mapped_column(Numeric(20, 6))
    total_equity: Mapped[float] = mapped_column(Numeric(20, 6))
    net_value: Mapped[float] = mapped_column(Numeric(20, 8))
    benchmark_net_value: Mapped[float] = mapped_column(Numeric(20, 8))
    drawdown: Mapped[float] = mapped_column(Numeric(12, 8))
    __table_args__ = (UniqueConstraint("run_id", "trade_date"),)
