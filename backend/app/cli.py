import argparse
from datetime import date, timedelta
from sqlalchemy import select
from .core.db import SessionLocal
from .core.models import Index
from .jobs.runner import execute_job
from .services.pipeline import probe_index

DEFAULTS = [
    ("CN:000932", "中证主要消费", "CN", "INDUSTRY", "akshare_csindex", "000932"),
    ("CN:000931", "中证可选消费", "CN", "INDUSTRY", "akshare_csindex", "000931"),
    ("CN:000300", "沪深300", "CN", "BROAD", "akshare_csindex", "000300"),
    ("CN:000905", "中证500", "CN", "BROAD", "akshare_csindex", "000905"),
    ("CN:000688", "科创50", "CN", "BROAD", "akshare_csindex", "000688"),
    ("CN:399006", "创业板指", "CN", "BROAD", "akshare_tx_index", "sz399006"),
    ("CN:H30590", "中证机器人", "CN", "THEME", "akshare_csindex", "H30590"),
    ("HK:HSI", "恒生指数", "HK", "BROAD", "akshare_hk_em", "HSI"),
    ("HK:HSTECH", "恒生科技指数", "HK", "THEME", "akshare_hk_em", "HSTECH"),
]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["seed", "probe", "backfill", "scan", "alerts"])
    parser.add_argument("--days", type=int, default=730)
    args = parser.parse_args()

    with SessionLocal() as db:
        if args.command == "seed":
            for code, name, market, kind, provider, symbol in DEFAULTS:
                if not db.scalar(select(Index).where(Index.index_code == code)):
                    db.add(Index(index_code=code, index_name=name, market=market, instrument_type=kind, provider=provider, provider_symbol=symbol, volume_basis="VOLUME" if provider == "akshare_csindex" else "NONE", enabled=False))
            db.commit()
            print("Seeded candidates; none enabled until verified")
        elif args.command == "probe":
            for index in db.scalars(select(Index)).all():
                try:
                    result = probe_index(index, date.today() - timedelta(days=90), date.today())
                    print(index.index_code, result)
                except Exception as error:
                    print(index.index_code, "ERROR", error)
        elif args.command == "alerts":
            print(__import__("app.jobs.runner", fromlist=["deliver_alerts"]).deliver_alerts(db))
        else:
            print(execute_job(db, args.command, start=date.today() - timedelta(days=args.days), end=date.today(), days=args.days))

if __name__ == "__main__":
    main()
