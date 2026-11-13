from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from .core.db import Base,engine,SessionLocal
from .core.models import MonitorConfig,Index
from .api.routes import router
from .api.backtest_routes import router as backtest_router
from .backtest import models as backtest_models

app=FastAPI(title='Index Reversal Monitor',docs_url='/index-reversal/api/docs',openapi_url='/index-reversal/api/openapi.json')
app.include_router(router)
app.include_router(backtest_router)
@app.on_event('startup')
def bootstrap():
    # Production schema should be installed through sql/schema.sql. create_all is safe for fresh DB only.
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        if not db.scalar(select(MonitorConfig).where(MonitorConfig.config_name=='default')):db.add(MonitorConfig(config_name='default'))
        db.commit()
