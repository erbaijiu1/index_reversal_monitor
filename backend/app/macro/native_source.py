"""Independent source adapters: SSE, SZSE, and annual GDP. No stock_monitor dependency.

Exchange series are in 100 million RMB (亿元). GDP data from AKShare
is retrospective and may include revised historical values; not a PIT feed.
"""
import json
import math
from datetime import date
import httpx
import akshare as ak

def _positive(v):
    try:
        x = float(v)
        return x if math.isfinite(x) and x > 0 else None
    except (TypeError, ValueError):
        return None

def _pick_row(frame, name_columns, expected="股票"):
    for field in name_columns:
        if field in frame.columns:
            rows = frame[frame[field].astype(str).str.strip() == expected]
            if not rows.empty:
                return rows.iloc[0]
    raise ValueError("missing exact 股票 market overview row (no fallback to A股 or combined securities)")

def _value(row, fields, source):
    for name in fields:
        if name not in row.index:
            continue
        value = _positive(row[name])
        if value is None:
            continue
        if "亿元" in name:
            return value
        if "万元" in name:
            return value / 10000
        if "元" in name:
            return value / 100000000
        if source == "SSE":
            # SSE historically returns hundred-million RMB for TOTAL_VALUE
            return value
        # SZSE unlabelled fields are not safe to infer
        raise ValueError(f"unknown amount units for {source}.{name}")
    raise ValueError(f"no positive market capitalization from {source}")

def fetch_sse_cap(day: date) -> float:
    params = {"isPagination": "false", "sqlId": "COMMON_SSE_SJ_SCGM_C", "TRADE_DATE": day.isoformat()}
    headers = {"Referer": "https://www.sse.com.cn/market/view/", "User-Agent": "Mozilla/5.0"}
    with httpx.Client(timeout=25) as client:
        response = client.get("https://query.sse.com.cn/commonQuery.do", params=params, headers=headers)
        response.raise_for_status()
        raw = response.text.strip()
    if not raw.startswith("{"):
        if "(" not in raw or not raw.endswith(")"):
            raise ValueError("unexpected SSE response shape")
        raw = raw[raw.index("(")+1:-1]
    payload = json.loads(raw)
    import pandas as pd
    frame = pd.DataFrame(payload["result"])
    row = _pick_row(frame, ("PRODUCT_NAME", "产品", "名称", "品种", "PRODUCT"))
    return _value(row, ("市价总值(亿元)", "总市值(亿元)", "TOTAL_VALUE", "TOTAL_MARKET_CAP"), "SSE")

def fetch_szse_cap(day: date) -> float:
    frame = ak.stock_szse_summary(date=day.strftime("%Y%m%d"))
    if frame is None or frame.empty:
        raise ValueError("SZSE returned no rows")
    row = _pick_row(frame, ("证券类别", "PRODUCT_NAME"))
    return _value(row, ("总市值(亿元)", "股票总市值(亿元)", "市价总值(亿元)",
                         "总市值(元)", "市价总值(元)"), "SZSE")

def fetch_annual_gdp() -> dict[int, float]:
    """Annual GDP total (100m RMB), retrospective values, not release-date audited."""
    frame = ak.macro_china_gdp()
    if frame is None or frame.empty:
        raise ValueError("annual GDP source returned no records")
    years = {}
    for _, row in frame.iterrows():
        period = str(row.get("季度", ""))
        if not ("年第1-4季度" in period or "年第4季度" in period):
            continue
        try:
            year = int(period.split("年", 1)[0])
        except ValueError:
            continue
        value = _positive(row.get("国内生产总值-绝对值"))
        if value:
            years[year] = value
    if not years:
        raise ValueError("annual GDP source has no full-year records")
    return years

def reference_gdp_year(day: date) -> int:
    """Return previous calendar year only after conservative March 1 gate.

    Jan/Feb are skipped rather than using year-2 GDP, preserving X's exact
    denominator definition. GDP revisions remain a point-in-time limitation.
    """
    return day.year - 1 if day.month >= 3 else None
