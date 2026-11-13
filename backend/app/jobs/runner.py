from datetime import datetime,date,timedelta
from uuid import uuid4
from sqlalchemy import select
import httpx
from ..core.models import Index,MonitorConfig,JobRun,Alert,Signal
from ..core.config import settings
from ..services.pipeline import sync_index,scan_index

def execute_job(db,job_type,index_ids=None,start=None,end=None,days=730,dry_run=False):
    job=JobRun(job_type=job_type,run_key=str(uuid4()),status='RUNNING');db.add(job);db.commit()
    result=[];success=0;fail=0
    q=select(Index).where(Index.id.in_(index_ids)) if index_ids else select(Index).where(Index.enabled==True)
    config=db.scalar(select(MonitorConfig).where(MonitorConfig.config_name=='default'))
    for idx in db.scalars(q).all():
        try:
            if job_type=='backfill':output=sync_index(db,idx,start,end)
            else:output=scan_index(db,idx,config,days,dry_run)
            success+=1;result.append({'index':idx.index_code,'result':len(output) if isinstance(output,list) else output})
        except Exception as e:
            db.rollback();fail+=1;result.append({'index':idx.index_code,'error':str(e)})
            idx=db.get(Index,idx.id);idx.last_error=str(e)[:500];idx.data_status='SOURCE_FAILED' if job_type=='backfill' else idx.data_status;db.commit()
    job=db.get(JobRun,job.id);job.status='PARTIAL' if fail and success else 'FAILED' if fail else 'SUCCESS';job.finished_at=datetime.utcnow();job.processed_count=success+fail;job.success_count=success;job.failure_count=fail;job.error_summary=str([r for r in result if 'error' in r])[:5000] if fail else None;db.commit()
    return {'job_id':job.id,'status':job.status,'items':result}

def deliver_alerts(db):
    if not settings.alert_enabled or not settings.webhook_url:return {'status':'DISABLED','sent':0}
    sent=0;failed=0
    for a in db.scalars(select(Alert).where(Alert.delivery_status.in_(['PENDING','FAILED']),Alert.attempt_count<5).limit(100)).all():
        signal=db.get(Signal,a.signal_id);idx=db.get(Index,signal.index_id)
        payload={'text':f'指数周线反转 {idx.index_name} {idx.index_code} {a.alert_phase} 一阳吞{signal.engulfed_count}线 量能:{signal.volume_level}'}
        try:
            response=httpx.post(settings.webhook_url,json=payload,timeout=10);response.raise_for_status()
            a.delivery_status='SENT';a.sent_at=datetime.utcnow();sent+=1
        except Exception as e:a.delivery_status='FAILED';a.last_error=str(e)[:500];failed+=1
        a.attempt_count+=1;db.commit()
    return {'sent':sent,'failed':failed}
