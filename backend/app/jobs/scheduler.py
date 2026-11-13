from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy.orm import Session
from ..core.db import SessionLocal
from ..core.config import settings
from .runner import execute_job,deliver_alerts
from datetime import date,timedelta

def daily():
    with SessionLocal() as db:
        execute_job(db,'backfill',start=date.today()-timedelta(days=30),end=date.today())
        execute_job(db,'scan',days=settings.history_days)
        deliver_alerts(db)

def main():
    if not settings.schedule_enabled:
        raise RuntimeError('Set SCHEDULE_ENABLED=true to run scheduler')
    s=BlockingScheduler(timezone=settings.timezone)
    # Run every day: official index sources may publish Friday data over the
    # weekend. The 30-day overlap makes the sync idempotent and self-healing.
    s.add_job(daily,'cron',hour=settings.sync_cron_hour,minute=settings.sync_cron_minute,id='daily',max_instances=1,coalesce=True,misfire_grace_time=3600)
    s.start()
if __name__=='__main__':main()
