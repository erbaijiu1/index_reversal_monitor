from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from .core.db import Base,engine,SessionLocal
from .core.models import MonitorConfig,Index
from .api.routes import router
from .api.backtest_routes import router as backtest_router
from .backtest import models as backtest_models
# Historical main references price_center, but it may not be tracked on this branch.
# Only skip the optional package if that package itself is absent; never hide its import errors.
try:
    from .price_center.routes import router as price_center_router
    from .price_center.data import seed_etf_mappings
    from .price_center import models as price_center_models
except ModuleNotFoundError as exc:
    if exc.name not in ("app.price_center", "app.price_center.routes", "app.price_center.data"):
        raise
    price_center_router = None
    seed_etf_mappings = None
from .macro.routes import router as macro_router
from .macro import models as macro_models

app=FastAPI(title='Index Reversal Monitor',docs_url='/index-reversal/api/docs',openapi_url='/index-reversal/api/openapi.json')
app.include_router(router)
app.include_router(backtest_router)
if price_center_router is not None:
    app.include_router(price_center_router)
app.include_router(macro_router)
@app.on_event('startup')
def bootstrap():
    # Production schema should be installed through sql/schema.sql. create_all is safe for fresh DB only.
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        if not db.scalar(select(MonitorConfig).where(MonitorConfig.config_name=='default')):db.add(MonitorConfig(config_name='default'))
        db.commit()
        if seed_etf_mappings is not None:
            seed_etf_mappings(db)
