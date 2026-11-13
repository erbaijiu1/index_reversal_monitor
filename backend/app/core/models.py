from sqlalchemy import BigInteger, Integer, String, Date, DateTime, Numeric, Boolean, Text, ForeignKey, UniqueConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column
from datetime import date, datetime
from .db import Base

class Index(Base):
    __tablename__='t_index_info'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    index_code: Mapped[str] = mapped_column(String(40),unique=True)
    index_name: Mapped[str] = mapped_column(String(100))
    market: Mapped[str] = mapped_column(String(8))
    instrument_type: Mapped[str] = mapped_column(String(20),default='THEME')
    provider: Mapped[str] = mapped_column(String(40))
    provider_symbol: Mapped[str] = mapped_column(String(80))
    data_status: Mapped[str] = mapped_column(String(24),default='PENDING_SOURCE')
    volume_basis: Mapped[str] = mapped_column(String(12),default='NONE')
    volume_unit: Mapped[str|None] = mapped_column(String(30),nullable=True)
    amount_unit: Mapped[str|None] = mapped_column(String(30),nullable=True)
    price_precision: Mapped[int] = mapped_column(Integer,default=4)
    enabled: Mapped[bool] = mapped_column(Boolean,default=False)
    last_success_date: Mapped[date|None] = mapped_column(Date,nullable=True)
    last_error: Mapped[str|None] = mapped_column(String(500),nullable=True)

class Daily(Base):
    __tablename__='t_index_daily'
    __table_args__=(UniqueConstraint('index_id','trade_date'),)
    id: Mapped[int] = mapped_column(Integer,primary_key=True)
    index_id: Mapped[int] = mapped_column(ForeignKey('t_index_info.id'))
    trade_date: Mapped[date] = mapped_column(Date)
    open_price: Mapped[float] = mapped_column(Numeric(20,6))
    high_price: Mapped[float] = mapped_column(Numeric(20,6))
    low_price: Mapped[float] = mapped_column(Numeric(20,6))
    close_price: Mapped[float] = mapped_column(Numeric(20,6))
    volume: Mapped[float|None] = mapped_column(Numeric(28,6),nullable=True)
    amount: Mapped[float|None] = mapped_column(Numeric(28,6),nullable=True)
    session_complete: Mapped[bool] = mapped_column(Boolean,default=True)
    data_source: Mapped[str] = mapped_column(String(40))
    fetched_at: Mapped[datetime] = mapped_column(DateTime,default=datetime.utcnow)

class Weekly(Base):
    __tablename__='t_index_weekly'
    __table_args__=(UniqueConstraint('index_id','week_start'),)
    id: Mapped[int] = mapped_column(Integer,primary_key=True)
    index_id: Mapped[int] = mapped_column(ForeignKey('t_index_info.id'))
    week_start: Mapped[date] = mapped_column(Date)
    first_trade_date: Mapped[date] = mapped_column(Date)
    last_trade_date: Mapped[date] = mapped_column(Date)
    open_price: Mapped[float] = mapped_column(Numeric(20,6))
    high_price: Mapped[float] = mapped_column(Numeric(20,6))
    low_price: Mapped[float] = mapped_column(Numeric(20,6))
    close_price: Mapped[float] = mapped_column(Numeric(20,6))
    volume: Mapped[float|None] = mapped_column(Numeric(28,6),nullable=True)
    amount: Mapped[float|None] = mapped_column(Numeric(28,6),nullable=True)
    actual_sessions: Mapped[int] = mapped_column(Integer)
    expected_sessions: Mapped[int] = mapped_column(Integer)
    is_complete: Mapped[bool] = mapped_column(Boolean,default=False)
    data_revision: Mapped[int] = mapped_column(Integer,default=1)

class MonitorConfig(Base):
    __tablename__='t_index_monitor_config'
    id: Mapped[int] = mapped_column(Integer,primary_key=True)
    config_name: Mapped[str] = mapped_column(String(80),unique=True,default='default')
    enabled: Mapped[bool] = mapped_column(Boolean,default=True)
    timeframe: Mapped[str] = mapped_column(String(12),default='1w')
    min_engulfed_count: Mapped[int] = mapped_column(Integer,default=2)
    min_bearish_count: Mapped[int] = mapped_column(Integer,default=2)
    max_lookback_weeks: Mapped[int] = mapped_column(Integer,default=26)
    volume_lookback_weeks: Mapped[int] = mapped_column(Integer,default=5)
    volume_warm_ratio: Mapped[float] = mapped_column(Numeric(8,4),default=1.2)
    volume_strong_ratio: Mapped[float] = mapped_column(Numeric(8,4),default=1.5)
    enable_forming_alert: Mapped[bool] = mapped_column(Boolean,default=True)
    enable_confirmed_alert: Mapped[bool] = mapped_column(Boolean,default=True)
    config_version: Mapped[int] = mapped_column(Integer,default=1)

class Signal(Base):
    __tablename__='t_index_reversal_signal'
    __table_args__=(UniqueConstraint('index_id','week_start','direction','algorithm_version','config_version'),)
    id: Mapped[int] = mapped_column(Integer,primary_key=True)
    index_id: Mapped[int] = mapped_column(ForeignKey('t_index_info.id'))
    week_start: Mapped[date] = mapped_column(Date)
    direction: Mapped[str] = mapped_column(String(8),default='UP')
    algorithm_version: Mapped[str] = mapped_column(String(32),default='1.0')
    config_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    engulfed_count: Mapped[int] = mapped_column(Integer)
    max_engulfable_count: Mapped[int] = mapped_column(Integer)
    bearish_count: Mapped[int] = mapped_column(Integer)
    previous_first_close: Mapped[float] = mapped_column(Numeric(20,6))
    previous_last_close: Mapped[float] = mapped_column(Numeric(20,6))
    breakout_high: Mapped[bool] = mapped_column(Boolean,default=False)
    volume_basis: Mapped[str] = mapped_column(String(12),default='NONE')
    volume_ratio: Mapped[float|None] = mapped_column(Numeric(12,5),nullable=True)
    cumulative_volume_ratio: Mapped[float|None] = mapped_column(Numeric(12,5),nullable=True)
    pace_ratio: Mapped[float|None] = mapped_column(Numeric(12,5),nullable=True)
    volume_level: Mapped[str] = mapped_column(String(20),default='UNAVAILABLE')
    signal_level: Mapped[str] = mapped_column(String(24),default='BASE')
    current_open: Mapped[float] = mapped_column(Numeric(20,6))
    current_close: Mapped[float] = mapped_column(Numeric(20,6))
    quote_asof: Mapped[datetime] = mapped_column(DateTime,default=datetime.utcnow)
    first_detected_at: Mapped[datetime] = mapped_column(DateTime,default=datetime.utcnow)
    confirmed_at: Mapped[datetime|None] = mapped_column(DateTime,nullable=True)
    invalidated_at: Mapped[datetime|None] = mapped_column(DateTime,nullable=True)
    recomputed_at: Mapped[datetime|None] = mapped_column(DateTime,nullable=True)

class SignalEvent(Base):
    __tablename__='t_index_signal_event'
    id: Mapped[int] = mapped_column(Integer,primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey('t_index_reversal_signal.id'))
    old_status: Mapped[str|None] = mapped_column(String(20),nullable=True)
    new_status: Mapped[str] = mapped_column(String(20))
    event_type: Mapped[str] = mapped_column(String(30))
    event_payload: Mapped[dict|None] = mapped_column(JSON,nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime,default=datetime.utcnow)

class Alert(Base):
    __tablename__='t_index_alert_log'
    id: Mapped[int] = mapped_column(Integer,primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey('t_index_reversal_signal.id'))
    alert_phase: Mapped[str] = mapped_column(String(20))
    channel: Mapped[str] = mapped_column(String(24))
    dedupe_key: Mapped[str] = mapped_column(String(180),unique=True)
    delivery_status: Mapped[str] = mapped_column(String(16),default='PENDING')
    attempt_count: Mapped[int] = mapped_column(Integer,default=0)
    last_error: Mapped[str|None] = mapped_column(String(500),nullable=True)
    sent_at: Mapped[datetime|None] = mapped_column(DateTime,nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime,default=datetime.utcnow)

class JobRun(Base):
    __tablename__='t_index_job_run'
    id: Mapped[int] = mapped_column(Integer,primary_key=True)
    job_type: Mapped[str] = mapped_column(String(40))
    run_key: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime,default=datetime.utcnow)
    finished_at: Mapped[datetime|None] = mapped_column(DateTime,nullable=True)
    processed_count: Mapped[int] = mapped_column(Integer,default=0)
    success_count: Mapped[int] = mapped_column(Integer,default=0)
    failure_count: Mapped[int] = mapped_column(Integer,default=0)
    error_summary: Mapped[str|None] = mapped_column(Text,nullable=True)
