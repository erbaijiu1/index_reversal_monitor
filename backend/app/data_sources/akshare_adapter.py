"""AKShare index data adapters."""
from datetime import date
from decimal import Decimal
import time
import pandas as pd

ALIASES = {'日期': 'date', 'date': 'date', '开盘': 'open', 'open': 'open', '最高': 'high', 'high': 'high', '最低': 'low', 'low': 'low', '收盘': 'close', 'close': 'close', '成交量': 'volume', 'volume': 'volume', '成交额': 'amount', 'amount': 'amount'}

def _fetch_frame(provider: str, symbol: str, start_s: str, end_s: str):
    import akshare as ak

    if provider == "akshare_csindex":
        return ak.stock_zh_index_hist_csindex(symbol=symbol, start_date=start_s, end_date=end_s)
    elif provider == "akshare_em_index":
        return ak.index_zh_a_hist(symbol=symbol, period="daily", start_date=start_s, end_date=end_s)
    elif provider == "akshare_tx_index":
        return ak.stock_zh_index_daily_tx(symbol=symbol)
    elif provider == "akshare_em_concept":
        return ak.stock_board_concept_hist_em(symbol=symbol, period="日k", start_date=start_s, end_date=end_s, adjust="")
    elif provider == "akshare_em_industry":
        return ak.stock_board_industry_hist_em(symbol=symbol, period="日k", start_date=start_s, end_date=end_s, adjust="")
    elif provider == "akshare_hk_em":
        return ak.stock_hk_index_daily_em(symbol=symbol)
    else:
        raise ValueError("Unsupported provider: " + provider)


def fetch(provider: str, symbol: str, start: date, end: date, attempts: int = 3):
    start_s = start.strftime("%Y%m%d")
    end_s = end.strftime("%Y%m%d")
    last_error = None
    for attempt in range(attempts):
        try:
            df = _fetch_frame(provider, symbol, start_s, end_s)
            break
        except Exception as error:
            last_error = error
            if attempt + 1 == attempts:
                raise
            time.sleep(0.5 * (2 ** attempt))
    else:
        raise last_error

    rename = {column: ALIASES[column] for column in df.columns if column in ALIASES}
    df = df.rename(columns=rename)
    required = ["date", "open", "high", "low", "close"]
    if not set(required).issubset(df.columns):
        raise ValueError(f"provider columns missing: {set(required) - set(df.columns)}; actual={list(df.columns)}")

    df["date"] = pd.to_datetime(df["date"]).dt.date
    rows = []
    for _, row_data in df.iterrows():
        if not start <= row_data["date"] <= end:
            continue
        row = {"date": row_data["date"]}
        for key in ("open", "high", "low", "close", "volume", "amount"):
            raw = row_data.get(key)
            row[key] = None if raw is None or pd.isna(raw) or str(raw).strip() in ("", "-") else Decimal(str(raw).replace(",", ""))
        rows.append(row)
    return sorted(rows, key=lambda item: item["date"])
