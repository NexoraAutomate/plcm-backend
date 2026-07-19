import os
from fastapi import FastAPI
from app.database import init_db, close_db, engine
from sqlmodel import Session
from contextlib import asynccontextmanager
from app.routers import router
from app.auth import initialize_roles_and_permissions, sync_roles_and_permissions
from app.services.inventory_service import backfill_legacy_inventory_instances

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Initialize defaults on first run, then sync any newly added permissions/roles
    with Session(engine) as session:
        initialize_roles_and_permissions(session)
        sync_roles_and_permissions(session)
        # Legacy seed/import data stored qty on the parent row; project install needs instances.
        backfill_legacy_inventory_instances(session)
    try:
        yield
    finally:
        # shutdown
        close_db()
    

app: FastAPI = FastAPI(title="PLCM System", lifespan=lifespan)

from fastapi.middleware.cors import CORSMiddleware

_default_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://192.168.1.6:3000",
    "http://193.193.193.80:3000",
    "http://193.193.193.141:3000",
    "http://193.193.193.109:3000",
]
_cors_origins_env = os.getenv("CORS_ORIGINS", "")
origins = (
    [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
    if _cors_origins_env.strip()
    else _default_origins
)
_cors_origin_regex = os.getenv(
    "CORS_ORIGIN_REGEX",
    r"https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+)(:\d+)?",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=_cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count"],
)

app.include_router(router, prefix="/api")

@app.get("/")
def root():
    return {"message": "PLM FastAPI running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=os.getenv("BACKEND_HOST", "0.0.0.0"),
        port=int(os.getenv("BACKEND_PORT", "8000")),
        reload=os.getenv("BACKEND_RELOAD", "true").lower() in ("1", "true", "yes"),
        reload_dirs=["app"],
    )