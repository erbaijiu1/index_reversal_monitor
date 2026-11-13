from datetime import date,datetime,timedelta
from collections import defaultdict
from sqlalchemy import select
import exchange_calendars as xcals
from .pattern import Rule,identify,valid
from ..core.models import Daily,Weekly,Signal,SignalEvent,Alert,Index,MonitorConfig
from ..data_sources.akshare_adapter import fetch

CAL={'CN':'XSHG','HK':'XHKG'}
def session_schedule(market,start,end):
    """Return sessions plus whether the exchange calendar covers the range."""
    cal=xcals.get_calendar(CAL[market])
    try:
        return [x.date() for x in cal.sessions_in_range(start.isoformat(),end.isoformat())],True
    except (ValueError,TypeError):
        # Calendar packages have a finite future horizon. Official provider rows
        # remain authoritative; weekdays are only used to reject weekend rows.
        days=[];current=start
        while current<=end:
            if current.weekday()<5:days.append(current)
            current+=timedelta(days=1)
        return days,False
def sessions(market,start,end):return session_schedule(market,start,end)[0]
def monday(day):return day-timedelta(days=day.weekday())
def utc():return datetime.utcnow()
def candle(x):
    return {'open':x.open_price,'high':x.high_price,'low':x.low_price,'close':x.close_price,'volume':x.volume,'amount':x.amount,'is_complete':x.is_complete,'actual_sessions':x.actual_sessions}

def probe_index(idx,start,end):
    rows=fetch(idx.provider,idx.provider_symbol,start,end)
    sample=[r for r in rows if valid(r)]
    return {'total':len(rows),'valid':len(sample),'min_date':str(rows[0]['date']) if rows else None,'max_date':str(rows[-1]['date']) if rows else None,'volume_available':sum(r['volume'] is not None for r in rows),'amount_available':sum(r['amount'] is not None for r in rows)}

def sync_index(db,idx,start,end):
    rows=fetch(idx.provider,idx.provider_symbol,start,end)
    if not rows:raise ValueError('empty price series')
    allowed=set(sessions(idx.market,start,end));count=0;accepted_dates=[]
    for r in rows:
        if not valid(r) or r['date'] not in allowed:continue
        obj=db.scalar(select(Daily).where(Daily.index_id==idx.id,Daily.trade_date==r['date']))
        if obj is None:obj=Daily(index_id=idx.id,trade_date=r['date'],data_source=idx.provider);db.add(obj)
        for k in ('open','high','low','close') :setattr(obj,k+'_price',r[k])
        obj.volume=r['volume'];obj.amount=r['amount'];obj.fetched_at=utc();obj.session_complete=True
        count+=1;accepted_dates.append(r['date'])
    if count==0:raise ValueError('no valid sessions')
    idx.last_success_date=max(accepted_dates);idx.data_status='ACTIVE';idx.last_error=None
    db.flush();build_weeklies(db,idx);db.commit();return count

def build_weeklies(db,idx):
    daily=db.scalars(select(Daily).where(Daily.index_id==idx.id).order_by(Daily.trade_date)).all()
    groups=defaultdict(list)
    for d in daily:groups[monday(d.trade_date)].append(d)
    today=date.today()
    for week,group in sorted(groups.items()):
        week_end=week+timedelta(days=6)
        expected,calendar_covered=session_schedule(idx.market,week,week_end)
        if not expected:continue
        got={d.trade_date for d in group if d.session_complete}
        if calendar_covered:
            complete=all(day in got for day in expected) and today>max(expected)
        else:
            complete=today>week_end and bool(got)
            expected=sorted(got)
        o=db.scalar(select(Weekly).where(Weekly.index_id==idx.id,Weekly.week_start==week))
        if o is None:o=Weekly(index_id=idx.id,week_start=week);db.add(o)
        group.sort(key=lambda d:d.trade_date)
        o.first_trade_date=group[0].trade_date;o.last_trade_date=group[-1].trade_date
        o.open_price=group[0].open_price;o.close_price=group[-1].close_price
        o.high_price=max(d.high_price for d in group);o.low_price=min(d.low_price for d in group)
        o.volume=sum((d.volume for d in group),start=0) if all(d.volume is not None for d in group) else None
        o.amount=sum((d.amount for d in group),start=0) if all(d.amount is not None for d in group) else None
        o.actual_sessions=len(group);o.expected_sessions=len(expected);o.is_complete=complete
    db.flush()

def scan_index(db,idx,config,days=730,dry_run=False):
    items=db.scalars(select(Weekly).where(Weekly.index_id==idx.id).order_by(Weekly.week_start)).all()
    rule=Rule(config.min_engulfed_count,config.min_bearish_count,config.max_lookback_weeks,config.volume_lookback_weeks,config.volume_warm_ratio,config.volume_strong_ratio)
    outcomes=[]; earliest=date.today()-timedelta(days=days)
    for pos,bar in enumerate(items):
        if bar.week_start<earliest:continue
        window=items[max(0,pos-max(rule.max_lookback,rule.volume_lookback)):pos+1]
        outcome=identify([candle(k) for k in window],rule)
        existing=db.scalar(select(Signal).where(Signal.index_id==idx.id,Signal.week_start==bar.week_start,Signal.algorithm_version=='1.0',Signal.config_version==config.config_version))
        if outcome is None:
            if existing and existing.status in ('FORMING','CONFIRMED') and not dry_run:
                old=existing.status;existing.status='RETRACTED' if old=='CONFIRMED' else 'INVALIDATED';existing.invalidated_at=utc();db.add(SignalEvent(signal_id=existing.id,old_status=old,new_status=existing.status,event_type=existing.status))
            continue
        outcomes.append({'index_id':idx.id,'week_start':str(bar.week_start),**{k:str(v) if hasattr(v,'as_tuple') else v for k,v in outcome.items()}})
        if dry_run:continue
        if existing is None:
            existing=Signal(index_id=idx.id,week_start=bar.week_start,direction='UP',algorithm_version='1.0',config_version=config.config_version,first_detected_at=utc());db.add(existing)
            old_status=None
        else:old_status=existing.status
        for k,v in outcome.items():setattr(existing,k,v)
        existing.quote_asof=utc();existing.recomputed_at=utc()
        if outcome['status']=='CONFIRMED' and existing.confirmed_at is None:existing.confirmed_at=utc()
        db.flush()
        if old_status!=outcome['status']:
            db.add(SignalEvent(signal_id=existing.id,old_status=old_status,new_status=outcome['status'],event_type='DETECTED' if old_status is None else 'CONFIRMED' if outcome['status']=='CONFIRMED' else 'UPDATED'))
            phase=outcome['status']
            if (phase=='FORMING' and config.enable_forming_alert) or (phase=='CONFIRMED' and config.enable_confirmed_alert):
                key=f'{existing.id}:{phase}:WEBHOOK'
                if not db.scalar(select(Alert).where(Alert.dedupe_key==key)):
                    db.add(Alert(signal_id=existing.id,alert_phase=phase,channel='WEBHOOK',dedupe_key=key))
    if not dry_run:db.commit()
    return outcomes
