from __future__ import annotations

from typing import Any, Protocol

from agenttrace.config import Settings

try:
    from langchain_openai import OpenAIEmbeddings
except Exception:  # pragma: no cover - exercised when optional dependency is absent
    OpenAIEmbeddings = None  # type: ignore[assignment]


class EmbeddingGenerationError(RuntimeError):
    pass


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        ...


class SqlConnection(Protocol):
    def execute(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        ...


class OpenAIEmbeddingProvider:
    def __init__(self, *, api_key: str, base_url: str | None = None) -> None:
        self.api_key = api_key
        self.base_url = base_url

    def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        if OpenAIEmbeddings is None:
            raise EmbeddingGenerationError("langchain-openai is required for OpenAI embeddings.")
        kwargs = {"model": model, "api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        embeddings = OpenAIEmbeddings(**kwargs)
        return embeddings.embed_documents(texts)


class EmbeddingService:
    def __init__(
        self,
        *,
        provider: EmbeddingProvider,
        model: str,
        dimension: int,
        max_retries: int = 3,
    ) -> None:
        if max_retries < 1:
            raise ValueError("max_retries must be greater than or equal to 1")
        self.provider = provider
        self.model = model
        self.dimension = dimension
        self.max_retries = max_retries

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        last_error: Exception | None = None
        for _ in range(self.max_retries):
            try:
                vectors = self.provider.embed(texts, model=self.model)
                self._validate_vectors(texts, vectors)
                return vectors
            except Exception as exc:
                last_error = exc

        raise EmbeddingGenerationError(f"Embedding generation failed: {last_error}") from last_error

    def _validate_vectors(self, texts: list[str], vectors: list[list[float]]) -> None:
        if len(vectors) != len(texts):
            raise EmbeddingGenerationError("Embedding result count does not match input count.")
        for vector in vectors:
            if len(vector) != self.dimension:
                raise EmbeddingGenerationError(
                    f"Embedding dimension mismatch: expected {self.dimension}, got {len(vector)}."
                )


class ChunkEmbeddingService:
    def __init__(self, *, embedding_service: EmbeddingService) -> None:
        self.embedding_service = embedding_service

    def embed_chunks(self, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        eligible = [
            chunk
            for chunk in chunks
            if chunk.get("chunk_id") and (chunk.get("content") or "").strip()
        ]
        texts = [chunk["content"] for chunk in eligible]
        vectors = self.embedding_service.embed_texts(texts)
        return [
            {"chunk_id": chunk["chunk_id"], "embedding": vector}
            for chunk, vector in zip(eligible, vectors, strict=True)
        ]


def build_openai_embedding_service(settings: Settings, *, max_retries: int = 3) -> EmbeddingService | None:
    if not settings.openai_api_key:
        return None
    return EmbeddingService(
        provider=OpenAIEmbeddingProvider(
            api_key=settings.openai_api_key,
            base_url=settings.openai_api_base,
        ),
        model=settings.embedding_model,
        dimension=settings.embedding_dimension,
        max_retries=max_retries,
    )


class PostgresChunkEmbeddingSql:
    @staticmethod
    def update_embeddings() -> str:
        return """
            UPDATE source_chunks
            SET embedding = data.embedding::vector
            FROM jsonb_to_recordset(%(rows)s::jsonb)
                AS data(chunk_id text, embedding double precision[])
            WHERE source_chunks.chunk_id = data.chunk_id
            RETURNING source_chunks.chunk_id
        """.strip()


class PostgresChunkEmbeddingStore:
    def __init__(self, connection: SqlConnection) -> None:
        self._connection = connection

    def update_embeddings(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not rows:
            return []
        return self._connection.execute(PostgresChunkEmbeddingSql.update_embeddings(), {"rows": rows})
