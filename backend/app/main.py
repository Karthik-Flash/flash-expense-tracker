from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import health
from app.config import settings

app = FastAPI(title="Flash Expense Tracker", version=__version__)
# Defaults allow GET only; widen methods/headers when write endpoints exist.
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list)
app.include_router(health.router)
