from fastapi import APIRouter

from app.api.v1 import health, knowledge_bases

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["Health"])
api_router.include_router(knowledge_bases.router,prefix="/knowledge-bases",tags=["KnowledgeBase"])
