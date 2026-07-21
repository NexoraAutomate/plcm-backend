import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import (
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session
from contextlib import asynccontextmanager

from app.database import init_db, close_db, engine
from app.routers import router
from app.auth import (
    ensure_default_admin,
    initialize_roles_and_permissions,
    sync_roles_and_permissions,
)
from app.services.inventory_service import backfill_legacy_inventory_instances
from app.services.security_settings_service import get_or_create_security_settings
from app.services.inactivity_service import deactivate_inactive_users
from app.services.schema_bootstrap import ensure_user_management_schema

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    ensure_user_management_schema()
    # Initialize defaults on first run, then sync any newly added permissions/roles
    with Session(engine) as session:
        initialize_roles_and_permissions(session)
        sync_roles_and_permissions(session)
        # First-run bootstrap: create admin / password@82768243 unless CREATE_DEFAULT_ADMIN=false
        ensure_default_admin(session)
        # Legacy seed/import data stored qty on the parent row; project install needs instances.
        backfill_legacy_inventory_instances(session)
        get_or_create_security_settings(session)
        # Reusable inactivity job — also runnable via POST /api/auth/run-inactivity-check
        deactivate_inactive_users(session)
    try:
        yield
    finally:
        # shutdown
        close_db()


# Disable default CDN-backed docs; serve Swagger UI from local static assets instead.
app: FastAPI = FastAPI(
    title="PLCM System",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)

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


@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} - Swagger UI",
        oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
        swagger_js_url="/static/swagger/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger/swagger-ui.css",
        swagger_favicon_url="/static/favicon.png",
    )


@app.get(app.swagger_ui_oauth2_redirect_url, include_in_schema=False)
async def swagger_ui_redirect():
    return get_swagger_ui_oauth2_redirect_html()


@app.get("/")
def root():
    return {"message": "PLM FastAPI running"}


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=os.getenv("BACKEND_HOST", "0.0.0.0"),
        port=int(os.getenv("BACKEND_PORT", "8000")),
        reload=os.getenv("BACKEND_RELOAD", "true").lower() in ("1", "true", "yes"),
        reload_dirs=["app"],
    )