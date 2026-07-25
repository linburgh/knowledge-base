"""Configuration for the local Ollama reranker adapter."""

from dataclasses import dataclass
import os


@dataclass(frozen=True, slots=True)
class Settings:
    host: str = os.getenv("RERANKER_ADAPTER_HOST", "127.0.0.1")
    port: int = int(os.getenv("RERANKER_ADAPTER_PORT", "7998"))
    ollama_base_url: str = os.getenv(
        "RERANKER_OLLAMA_BASE_URL", "http://127.0.0.1:11434"
    ).rstrip("/")
    ollama_model: str = os.getenv(
        "RERANKER_OLLAMA_MODEL", "B-A-M-N/qwen3-reranker-0.6b-fp16:latest"
    )
    ollama_timeout_seconds: float = float(
        os.getenv("RERANKER_OLLAMA_TIMEOUT_SECONDS", "120")
    )
    max_documents: int = int(os.getenv("RERANKER_MAX_DOCUMENTS", "30"))
    top_logprobs: int = int(os.getenv("RERANKER_TOP_LOGPROBS", "20"))
    fallback_binary_score: bool = os.getenv(
        "RERANKER_FALLBACK_BINARY_SCORE", "true"
    ).lower() in {"1", "true", "yes"}


settings = Settings()
