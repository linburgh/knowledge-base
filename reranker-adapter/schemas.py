"""HTTP request and response schemas."""

from pydantic import BaseModel, Field, field_validator


class RerankRequest(BaseModel):
    model: str | None = None
    query: str = Field(min_length=1, max_length=8192)
    documents: list[str] = Field(min_length=1)
    top_n: int | None = Field(default=None, ge=1)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        return value.strip()


class RerankResult(BaseModel):
    index: int = Field(ge=0)
    relevance_score: float = Field(ge=0, le=1)


class RerankResponse(BaseModel):
    results: list[RerankResult]
    model: str
    elapsed_ms: float


class HealthResponse(BaseModel):
    status: str
    ollama_base_url: str
    model: str
