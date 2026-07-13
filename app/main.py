from fastapi import FastAPI
from app.database import init_db, close_db, engine
from sqlmodel import Session
from contextlib import asynccontextmanager
from app.routers import router
from app.auth import initialize_roles_and_permissions

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Initialize default roles and permissions
    with Session(engine) as session:
        initialize_roles_and_permissions(session)
    try:
        yield
    finally:
        # shutdown
        close_db()
    

app: FastAPI = FastAPI(title="PLCM System", lifespan=lifespan)

from fastapi.middleware.cors import CORSMiddleware

origins = [
    'http://localhost:3000',
    'http://127.0.0.1:3000',
    'http://192.168.1.6:3000',
    'http://193.193.193.80:3000',
    'http://193.193.193.141:3000',
    'http://193.193.193.109:3000'
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+)(:\d+)?",
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
    uvicorn.run("app.main:app", reload=True, reload_dirs=["app"])