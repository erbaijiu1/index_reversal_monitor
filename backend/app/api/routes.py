from datetime import date,timedelta
from fastapi import APIRouter,Depends,HTTPException,Query,Header
from pydantic import BaseModel,Field
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from ..core.db import get_db
from ..core.config import settings
from ..core.models import Index,Weekly,Daily,Signal,MonitorConfig,JobRun,Alert
from ..services.pipeline import probe_index,sync_index,scan_index
from ..jobs.runner import execute_job,deliver_alerts

router=APIRouter(prefix='/index-reversal/api/v1')
def auth(x_admin_token:str|None=Header(None)):
    if settings.admin_token=='CHANGE_ME' or x_admin_token!=settings.admin_token:raise HTTPException(status_code=403,detail='Invalid admin token')
def data(x):
    if isinstance(x,list):return [data(v) for v in x]
    if isinstance(x,dict):return {k:data(v) for k,v in x.items()}
    from decimal import Decimal
    from datetime import date,datetime
    if isinstance(x,Decimal):return float(x)
    if isinstance(x,(date,datetime)):return x.isoformat()+'Z' if isinstance(x,datetime) else x.isoformat()
    return x
def dto(obj,fields):return data({k:getattr(obj,k) for k in fields})
IF='id index_code index_name market instrument_type provider provider_symbol data_status volume_basis enabled last_success_date last_error'.split()
SF='id index_id week_start status engulfed_count max_engulfable_count bearish_count breakout_high volume_basis volume_ratio cumulative_volume_ratio pace_ratio volume_level signal_level current_open current_close config_version'.split()
CF='id config_name enabled timeframe min_engulfed_count min_bearish_count max_lookback_weeks volume_lookback_weeks volume_warm_ratio volume_strong_ratio enable_forming_alert enable_confirmed_alert config_version'.split()
class IndexIn(BaseModel):
    index_code:str;index_name:str;market:str;instrument_type:str='THEME';provider:str;provider_symbol:str;enabled:bool=False
class IndexPatch(BaseModel):
    index_name:str|None=None;enabled:bool|None=None;provider:str|None=None;provider_symbol:str|None=None
    volume_basis:str|None=Field(default=None,pattern='^(VOLUME|AMOUNT|NONE)$')
class ConfigPatch(BaseModel):
    min_engulfed_count:int=Field(ge=2,le=26);min_bearish_count:int=Field(ge=2,le=26)
    max_lookback_weeks:int=Field(ge=2,le=104);volume_lookback_weeks:int=Field(ge=2,le=26)
    volume_warm_ratio:float=Field(gt=0,le=10);volume_strong_ratio:float=Field(gt=0,le=10)
    enable_forming_alert:bool=True;enable_confirmed_alert:bool=True
class JobArgs(BaseModel):
    index_ids:list[int]|None=None;start:date|None=None;end:date|None=None;days:int=Field(730,ge=14,le=3650);dry_run:bool=False

@router.get('/health')
def health():return {'status':'ok'}
@router.get('/indices')
def indices(market:str|None=None,enabled:bool|None=None,search:str|None=None,page:int=Query(1,ge=1),size:int=Query(50,ge=1,le=200),db:Session=Depends(get_db)):
    q=select(Index)
    if market:q=q.where(Index.market==market)
    if enabled is not None:q=q.where(Index.enabled==enabled)
    if search:q=q.where(Index.index_name.contains(search) | Index.index_code.contains(search))
    total=db.scalar(select(func.count()).select_from(q.subquery()))
    items=[]
    for x in db.scalars(q.order_by(Index.id).offset((page-1)*size).limit(size)):
        item=dto(x,IF)
        item['daily_count']=db.scalar(select(func.count()).select_from(Daily).where(Daily.index_id==x.id)) or 0
        item['weekly_count']=db.scalar(select(func.count()).select_from(Weekly).where(Weekly.index_id==x.id)) or 0
        item['signal_count']=db.scalar(select(func.count()).select_from(Signal).where(Signal.index_id==x.id)) or 0
        items.append(item)
    return {'total':total,'items':items}
@router.post('/indices',dependencies=[Depends(auth)])
def create_index(p:IndexIn,db:Session=Depends(get_db)):
    if p.market not in ('CN','HK'):raise HTTPException(400,'market must CN or HK')
    if db.scalar(select(Index).where(Index.index_code==p.index_code)):raise HTTPException(409,'duplicate code')
    x=Index(**p.model_dump());x.enabled=False;db.add(x);db.commit();db.refresh(x);return dto(x,IF)
@router.patch('/indices/{index_id}',dependencies=[Depends(auth)])
def patch_index(index_id:int,p:IndexPatch,db:Session=Depends(get_db)):
    x=db.get(Index,index_id)
    if not x:raise HTTPException(404,'index not found')
    changes=p.model_dump(exclude_unset=True)
    source_changed=('provider' in changes and changes['provider']!=x.provider) or ('provider_symbol' in changes and changes['provider_symbol']!=x.provider_symbol)
    if source_changed and db.scalar(select(func.count()).select_from(Daily).where(Daily.index_id==x.id)):
        raise HTTPException(409,'cannot change provider after price data exists')
    for k,v in changes.items():setattr(x,k,v)
    if source_changed:
        x.enabled=False;x.data_status='PENDING_SOURCE';x.last_success_date=None;x.last_error=None
    if p.enabled and x.data_status!='ACTIVE':raise HTTPException(409,'probe / sync source before enabling')
    db.commit();return dto(x,IF)
@router.post('/indices/{index_id}/probe',dependencies=[Depends(auth)])
def probe(index_id:int,db:Session=Depends(get_db)):
    x=db.get(Index,index_id)
    if not x:raise HTTPException(404,'index not found')
    try:
        res=probe_index(x,date.today()-timedelta(days=90),date.today())
        x.data_status='PROBED' if res['valid']>=20 else 'PENDING_SOURCE';x.last_error=None;db.commit()
        return res
    except Exception as e:
        x.data_status='SOURCE_FAILED';x.last_error=str(e)[:500];db.commit();raise HTTPException(502,str(e))
@router.get('/indices/{index_id}/candles')
def candles(index_id:int,period:str='1w',start:date|None=None,end:date|None=None,db:Session=Depends(get_db)):
    if period not in ('1w','1d'):raise HTTPException(400,'period invalid')
    table=Weekly if period=='1w' else Daily;field=table.week_start if period=='1w' else table.trade_date
    q=select(table).where(table.index_id==index_id)
    if start:q=q.where(field>=start)
    if end:q=q.where(field<=end)
    items=db.scalars(q.order_by(field.desc()).limit(500)).all()
    return [dto(x, ['week_start' if period=='1w' else 'trade_date','open_price','high_price','low_price','close_price','volume','amount']+(['is_complete','actual_sessions','expected_sessions'] if period=='1w' else [])) for x in reversed(items)]
@router.get('/indices/{index_id}/signals')
def index_signals(index_id:int,db:Session=Depends(get_db)):
    return [dto(x,SF) for x in db.scalars(select(Signal).where(Signal.index_id==index_id).order_by(Signal.week_start.desc()).limit(300))]
@router.get('/signals')
def signals(market:str|None=None,status:str|None=None,level:str|None=None,week:date|None=None,min_engulfed_count:int=2,page:int=Query(1,ge=1),size:int=Query(50,ge=1,le=200),db:Session=Depends(get_db)):
    q=select(Signal,Index.index_name,Index.index_code).join(Index,Signal.index_id==Index.id).where(Signal.engulfed_count>=min_engulfed_count)
    if market:q=q.where(Index.market==market)
    if status:q=q.where(Signal.status==status)
    if level:q=q.where(Signal.signal_level==level)
    if week:q=q.where(Signal.week_start==week)
    total=db.scalar(select(func.count()).select_from(q.subquery()))
    rows=db.execute(q.order_by(Signal.week_start.desc(),Signal.id.desc()).offset((page-1)*size).limit(size)).all()
    return {'total':total,'items':[dict(dto(x,SF),index_name=name,index_code=code) for x,name,code in rows]}
@router.get('/signals/{signal_id}')
def signal(signal_id:int,db:Session=Depends(get_db)):
    x=db.get(Signal,signal_id)
    if not x:raise HTTPException(404,'signal not found')
    return dto(x,SF+['previous_first_close','previous_last_close','quote_asof','first_detected_at','confirmed_at','invalidated_at'])
@router.get('/overview')
def overview(db:Session=Depends(get_db)):
    count=db.scalar(select(func.count()).select_from(Index)) or 0
    active=db.scalar(select(func.count()).select_from(Index).where(Index.enabled==True)) or 0
    failed=db.scalar(select(func.count()).select_from(Index).where(Index.data_status=='SOURCE_FAILED')) or 0
    recent=db.execute(select(Signal,Index.index_name,Index.index_code).join(Index).order_by(Signal.week_start.desc(),Signal.id.desc()).limit(15)).all()
    return {'index_count':count,'enabled_count':active,'failed_count':failed,'recent':[dict(dto(s,SF),index_name=n,index_code=c) for s,n,c in recent]}
@router.get('/config')
def config(db:Session=Depends(get_db)):
    x=db.scalar(select(MonitorConfig).where(MonitorConfig.config_name=='default'))
    return dto(x,CF) if x else {}
@router.put('/config',dependencies=[Depends(auth)])
def update_config(p:ConfigPatch,db:Session=Depends(get_db)):
    if p.min_bearish_count>p.max_lookback_weeks or p.min_engulfed_count>p.max_lookback_weeks or p.volume_strong_ratio<p.volume_warm_ratio:raise HTTPException(400,'inconsistent config')
    x=db.scalar(select(MonitorConfig).where(MonitorConfig.config_name=='default'))
    if x is None:x=MonitorConfig(config_name='default');db.add(x)
    for k,v in p.model_dump().items():setattr(x,k,v)
    x.config_version+=1;db.commit();return dto(x,CF)
@router.post('/jobs/probe-sources',dependencies=[Depends(auth)])
def probe_all(p:JobArgs,db:Session=Depends(get_db)):
    results=[]
    for x in db.scalars(select(Index).where(Index.id.in_(p.index_ids)) if p.index_ids else select(Index)):
        try:results.append({'id':x.id,'result':probe_index(x,p.start or date.today()-timedelta(days=90),p.end or date.today())})
        except Exception as e:results.append({'id':x.id,'error':str(e)})
    return results
@router.post('/jobs/backfill',dependencies=[Depends(auth)])
def backfill(p:JobArgs,db:Session=Depends(get_db)):
    return execute_job(db,'backfill',p.index_ids,p.start or date.today()-timedelta(days=p.days),p.end or date.today(),p.days)
@router.post('/jobs/scan',dependencies=[Depends(auth)])
def scan(p:JobArgs,db:Session=Depends(get_db)):
    return execute_job(db,'scan',p.index_ids,None,None,p.days,p.dry_run)
@router.post('/jobs/deliver-alerts',dependencies=[Depends(auth)])
def alert(db:Session=Depends(get_db)):return deliver_alerts(db)
@router.get('/jobs')
def jobs(db:Session=Depends(get_db)):
    return [dto(x,['job_type','run_key','status','started_at','finished_at','processed_count','success_count','failure_count','error_summary']) for x in db.scalars(select(JobRun).order_by(JobRun.id.desc()).limit(50))]
