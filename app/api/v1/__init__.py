from fastapi import APIRouter

from app.api.v1 import chat, conversations, documents, health, knowledge_bases, search

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["Health"])
api_router.include_router(knowledge_bases.router, prefix="/knowledge-bases", tags=["KnowledgeBase"])
api_router.include_router(documents.router, prefix="/documents", tags=["Document"])
api_router.include_router(conversations.router, prefix="/conversations", tags=["Conversation"])
api_router.include_router(search.router, prefix="/search", tags=["Search"])
api_router.include_router(chat.router, prefix="/chat", tags=["Chat"])
