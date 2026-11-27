"""Import raw CAP/GDP facts separately from indicator calculations.

The source stock_monitor endpoint is a convenience mirror, not point-in-time
historical GDP vintages. Keep provenance explicit to prevent false claims.
"""
from datetime import date, datetime
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import MacroRawDaily, MacroIndicatorDaily
from .indicator import cap_gdp_ratio

SOURCE_URL = "http://127.0.0.1:8888/stock/api/cap-gdp/series"

def fetch_upstream(start: date, end: date, source_url: str = SOURCE_URL, market: str = "CN-A") -> list[dict]:
    """Production source URL must be reachable from the container (not host localhost)."""
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        response = client.get(source_url, params={"market": market, "from": start.isoformat(), "to": end.isoformat()})
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("points"), list):
        raise ValueError("upstream response must contain a points array")
    return payload["points"]

def sync_raw(db: Session, points: list[dict], market: str = "CN-A", source: str = "stock_monitor", provenance: str = "UPSTREAM_SNAPSHOT") -> dict:
    """Idempotent insert/update; rejects incomplete records instead of filling with guessed values."""
    stats = {"updated": 0, "skipped": 0}
    for point in points:
        try:
            day = date.fromisoformat(str(point["date"])[:10])
            cap = float(point["total_market_cap"])
            gdp = float(point["prev_year_gdp"])
            if cap <= 0 or gdp <= 0:
                raise ValueError("invalid nonpositive input")
        except (KeyError, TypeError, ValueError):
            stats["skipped"] += 1
            continue
        record = db.scalar(select(MacroRawDaily).where(MacroRawDaily.market == market, MacroRawDaily.trade_date == day))
        if record is None:
            record = MacroRawDaily(market=market, trade_date=day)
            db.add(record)
        record.total_market_cap = cap
        record.reference_gdp = gdp
        record.gdp_reference_year = day.year - 1
        record.source = source
        record.provenance = provenance
        record.fetched_at = datetime.utcnow()
        stats["updated"] += 1
    db.flush()
    return stats

def calculate_indicators(db: Session, market: str = "CN-A", version: str = "v1") -> int:
    """Recompute indicators from raw facts; never silently use a quoted upstream ratio."""
    raw = db.scalars(select(MacroRawDaily).where(MacroRawDaily.market == market).order_by(MacroRawDaily.trade_date)).all()
    count = 0
    for item in raw:
        ratio = cap_gdp_ratio(float(item.total_market_cap), float(item.reference_gdp))
        row = db.scalar(select(MacroIndicatorDaily).where(
            MacroIndicatorDaily.market == market, MacroIndicatorDaily.trade_date == item.trade_date,
            MacroIndicatorDaily.version == version,
        ))
        if row is None:
            row = MacroIndicatorDaily(market=market, trade_date=item.trade_date, version=version)
            db.add(row)
        row.cap_to_gdp = ratio
        row.provenance = item.provenance
        row.calculated_at = datetime.utcnow()
        count += 1
    db.flush()
    return count
