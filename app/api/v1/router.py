"""API v1 root router aggregator."""

from fastapi import APIRouter
from app.api.v1.auth import router as auth_router
from app.api.v1.chat import router as chat_router
from app.api.v1.integrations import router as integrations_router
from app.api.v1.mappings import router as mappings_router
from app.api.v1.webhooks import router as webhooks_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(auth_router)
api_v1_router.include_router(integrations_router)
api_v1_router.include_router(mappings_router)
api_v1_router.include_router(chat_router)
api_v1_router.include_router(webhooks_router)
