from contextlib import asynccontextmanager
import logging

from fastapi import Depends, FastAPI
from sqlalchemy import text

from core import auth
from core.db import engine, metadata, transaction
from core.config import SEED_DEMO
from core.middleware import install
from core.migrate import migrate
from core.queueing import broker, view
from core.venue_dep import venue_code
from domain.routes import routers
from domain.venues import VENUE_NAMES, VENUES
from scripts.seed_demo import seed

@asynccontextmanager
async def lifespan(app):
    # 旧单场地库先幂等升级为多场地结构，再补齐新表。
    migrate()
    metadata.create_all(engine)
    if SEED_DEMO:
        try:
            seed()
        except Exception:
            logging.getLogger('uvicorn.error').exception('demo seed failed')
    yield

app = FastAPI(lifespan=lifespan)
install(app)
app.include_router(auth.router)
for router in routers:
    app.include_router(router)

@app.get('/health')
def health():
    with transaction() as conn:
        conn.execute(text('SELECT 1'))
    return {'ok': bool(broker.ping())}

@app.get('/venues')
def list_venues(user=Depends(auth.actor)):
    return {'venues': [{'code': code, 'name': VENUE_NAMES[code]} for code in VENUES]}

@app.get('/compute/{token}')
def compute(token: str, user=Depends(auth.actor), venue: str = Depends(venue_code)):
    return view(user, token, venue)
