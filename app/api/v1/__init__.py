from fastapi import APIRouter

from app.api.v1 import documents, health, knowledge_bases

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["Health"])
api_router.include_router(knowledge_bases.router,prefix="/knowledge-bases",tags=["KnowledgeBase"])
api_router.include_router(documents.router,prefix="/documents",tags=["Document"])
