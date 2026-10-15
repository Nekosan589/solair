import asyncio
import json

from random import uniform
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from webapp.app.config import settings
from webapp.app.database import create_db_and_tables
from webapp.app.services.ws_manager import manager
from webapp.app.routers import ws
from webapp.app.ml.artifacts import load_artifacts
from webapp.app.routers import api

async def push_metrics():
    """TEST"""
    while True:
        payload = {
            "cpu" : uniform(0, 100),
            "memory": uniform(0, 100)
        }
        await manager.broadcast(json.dumps(payload))
        await asyncio.sleep(1)

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    load_artifacts(
        model_load_path=settings.MODEL_LOAD_PATH,
        model_filename=settings.MODEL_FILENAME,
        scaler_x_path=settings.SCALER_X_PATH,
        scaler_y_path=settings.SCALER_Y_PATH,
    )

    task = asyncio.create_task(push_metrics())
    yield
    task.cancel()

app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

# LAN-only note: CORS is left wide open here purely so any device on
# the network can load the page/hit the API during development. This
# app has no auth layer -- do not expose it beyond a trusted LAN
# without adding authentication and tightening this middleware.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api.router)
app.include_router(ws.router)

@app.get("/health")
def health_check():
    return {"status": "ok"}

app.mount("/static", StaticFiles(directory=settings.STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(settings.INDEX_FILE)