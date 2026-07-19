from fastapi import APIRouter

from app.api.v1 import (
    auth,
    chat,
    conversations,
    documents,
    health,
    knowledge_bases,
    organizations,
    platform_overview,
    search,
    tenants,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(health.router, prefix="/health", tags=["Health"])
api_router.include_router(knowledge_bases.router, prefix="/knowledge-bases", tags=["KnowledgeBase"])
api_router.include_router(tenants.router, prefix="/tenants", tags=["Tenant"])
api_router.include_router(users.router, prefix="/users", tags=["User"])
api_router.include_router(organizations.router, prefix="/organizations", tags=["Organization"])
api_router.include_router(platform_overview.router, prefix="/platform", tags=["Platform"])
api_router.include_router(documents.router, prefix="/documents", tags=["Document"])
api_router.include_router(conversations.router, prefix="/conversations", tags=["Conversation"])
api_router.include_router(search.router, prefix="/search", tags=["Search"])
api_router.include_router(chat.router, prefix="/chat", tags=["Chat"])
