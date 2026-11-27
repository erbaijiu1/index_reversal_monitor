"""Independent CAP/GDP sync and derived metrics.

Raw data and indicators live solely in the index_reversal_monitor database.
"""
from datetime import date, datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..core.models import Daily
from .models import MacroRawDaily, MacroIndicatorDaily
from .indicator import cap_gdp_ratio
from .native_source import fetch_sse_cap, fetch_szse_cap, fetch_annual_gdp, reference_gdp_year

PROVENANCE = "RETROSPECTIVE_GDP"

def sync_native(db: Session, start: date, end: date, index_id: int, market: str = "CN-A") -> dict:
    """Use already-synchronized local index trading dates as market calendar.

    Acquire each exchange directly; only save a combined value if both succeed.
    GDP values are retrospective, never represented as independently PIT verified.
    """
    days = db.scalars(select(Daily.trade_date).where(
        Daily.index_id == index_id, Daily.trade_date >= start, Daily.trade_date <= end,
        Daily.session_complete.is_(True)).order_by(Daily.trade_date)).all()
    days = sorted(set(days))
    if not days:
        raise ValueError("No local index trading dates. Synchronize the selected index daily quotes first.")
    gdp_by_year = fetch_annual_gdp()
    stats = {"updated": 0, "skipped": 0, "errors": []}
    for day in days:
        year = reference_gdp_year(day)
        gdp = gdp_by_year.get(year)
        if not gdp:
            stats["skipped"] += 1
            stats["errors"].append({"date": day.isoformat(), "reason": f"missing GDP {year}"})
            continue
        try:
            sse = fetch_sse_cap(day)
            szse = fetch_szse_cap(day)
            cap = sse + szse
            if sse <= 0 or szse <= 0 or cap <= 0:
                raise ValueError("nonpositive market cap")
        except Exception as exc:
            stats["skipped"] += 1
            stats["errors"].append({"date": day.isoformat(), "reason": str(exc)[:250]})
            continue
        row = db.scalar(select(MacroRawDaily).where(
            MacroRawDaily.market == market, MacroRawDaily.trade_date == day))
        if row is None:
            row = MacroRawDaily(market=market, trade_date=day)
            db.add(row)
        row.total_market_cap = cap
        row.reference_gdp = gdp
        row.gdp_reference_year = year
        row.source = "SSE_SZSE_OFFICIAL_AKSHARE_GDP"
        row.provenance = PROVENANCE
        row.fetched_at = datetime.utcnow()
        stats["updated"] += 1
    db.flush()
    stats["error_count"] = len(stats["errors"])
    stats["errors"] = stats["errors"][:20]
    return stats

def calculate_indicators(db: Session, market: str = "CN-A", version: str = "v1") -> int:
    raw = db.scalars(select(MacroRawDaily).where(
        MacroRawDaily.market == market).order_by(MacroRawDaily.trade_date)).all()
    count = 0
    for item in raw:
        ratio = cap_gdp_ratio(float(item.total_market_cap), float(item.reference_gdp))
        row = db.scalar(select(MacroIndicatorDaily).where(
            MacroIndicatorDaily.market == market, MacroIndicatorDaily.trade_date == item.trade_date,
            MacroIndicatorDaily.version == version))
        if row is None:
            row = MacroIndicatorDaily(market=market, trade_date=item.trade_date, version=version)
            db.add(row)
        row.cap_to_gdp = ratio
        row.provenance = item.provenance
        row.calculated_at = datetime.utcnow()
        count += 1
    db.flush()
    return count
