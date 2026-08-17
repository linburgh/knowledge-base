from fastapi import APIRouter

from app.api.open import router as open_router
from app.api.v1 import (
    auth,
    chat,
    conversations,
    documents,
    evaluations,
    guest,
    health,
    monitoring,
    organizations,
    search,
    tenants,
    users,
)
from app.api.v1.knowledge_base import mgr as knowledge_base_mgr
from app.api.v1.knowledge_base import overview as knowledge_base_overview
from app.api.v1.knowledge_base import qa_config as knowledge_base_qa_config
from app.api.v1.platform import overview as platform_overview
from app.api.v1.platform import roles as platform_roles

api_router = APIRouter()
api_router.include_router(open_router)
api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(health.router, prefix="/health", tags=["Health"])
api_router.include_router(
    knowledge_base_mgr.router, prefix="/knowledge-bases", tags=["KnowledgeBase"]
)
api_router.include_router(
    knowledge_base_overview.router, prefix="/knowledge-bases", tags=["KnowledgeBase"]
)
api_router.include_router(
    knowledge_base_qa_config.router, prefix="/knowledge-bases", tags=["KnowledgeBaseQaConfig"]
)
api_router.include_router(tenants.router, prefix="/tenants", tags=["Tenant"])
api_router.include_router(users.router, prefix="/users", tags=["User"])
api_router.include_router(organizations.router, prefix="/organizations", tags=["Organization"])
api_router.include_router(platform_overview.router, prefix="/platform", tags=["Platform"])
api_router.include_router(platform_roles.router, prefix="/platform", tags=["PlatformRole"])
api_router.include_router(documents.router, prefix="/documents", tags=["Document"])
api_router.include_router(conversations.router, prefix="/conversations", tags=["Conversation"])
api_router.include_router(search.router, prefix="/search", tags=["Search"])
api_router.include_router(chat.router, prefix="/chat", tags=["Chat"])
api_router.include_router(guest.router, prefix="/guest", tags=["Guest"])
api_router.include_router(evaluations.router, prefix="/platform/evaluations", tags=["Evaluation"])
api_router.include_router(monitoring.router, prefix="/monitoring", tags=["Monitoring"])
