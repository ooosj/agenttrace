import pytest

from agenttrace.config import Settings
from agenttrace.config import get_settings
from agenttrace.services.embeddings import EmbeddingGenerationError
from agenttrace.services.embeddings import EmbeddingService
from agenttrace.services.embeddings import ChunkEmbeddingService
from agenttrace.services.embeddings import PostgresChunkEmbeddingSql
from agenttrace.services.embeddings import PostgresChunkEmbeddingStore
from agenttrace.services.embeddings import OpenAIEmbeddingProvider
from agenttrace.services.embeddings import build_openai_embedding_service


class FakeProvider:
    def __init__(self, vectors=None, failures=0):
        self.vectors = vectors or [[0.1] * 1536]
        self.failures = failures
        self.calls = 0

    def embed(self, texts, *, model):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("temporary failure")
        return self.vectors


def test_settings_prefer_agenttrace_openai_key_for_embedding(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("OPENAI_API_KEY", "generic-key")
    monkeypatch.setenv("AGENTTRACE_OPENAI_API_KEY", "agenttrace-key")
    monkeypatch.setenv("AGENTTRACE_EMBEDDING_MODEL", "text-embedding-3-small")

    settings = get_settings()

    assert settings.openai_api_key == "agenttrace-key"
    assert settings.embedding_model == "text-embedding-3-small"
    assert settings.embedding_dimension == 1536


def test_settings_prefer_agenttrace_openai_base_over_generic_base(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("AGENTTRACE_OPENAI_API_KEY", "agenttrace-key")
    monkeypatch.setenv("AGENTTRACE_OPENAI_API_BASE", "https://api.openai.com/v1")
    monkeypatch.setenv("OPENAI_API_BASE", "https://gms.example.test/v1")

    settings = get_settings()

    assert settings.openai_api_base == "https://api.openai.com/v1"


def test_embedding_service_retries_transient_failures():
    provider = FakeProvider(failures=2)
    service = EmbeddingService(provider=provider, model="text-embedding-3-small", dimension=1536, max_retries=3)

    vectors = service.embed_texts(["hello"])

    assert vectors == [[0.1] * 1536]
    assert provider.calls == 3


def test_embedding_service_fails_when_dimension_mismatches():
    provider = FakeProvider(vectors=[[0.1, 0.2]])
    service = EmbeddingService(provider=provider, model="text-embedding-3-small", dimension=1536, max_retries=1)

    with pytest.raises(EmbeddingGenerationError, match="dimension"):
        service.embed_texts(["hello"])


def test_openai_embedding_provider_uses_configured_model_and_key(monkeypatch):
    captured = {}

    class FakeEmbeddings:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def embed_documents(self, texts):
            return [[0.1] * 1536 for _ in texts]

    monkeypatch.setattr("agenttrace.services.embeddings.OpenAIEmbeddings", FakeEmbeddings)

    provider = OpenAIEmbeddingProvider(api_key="agenttrace-key", base_url="https://example.test/v1")
    result = provider.embed(["hello"], model="text-embedding-3-small")

    assert captured["api_key"] == "agenttrace-key"
    assert captured["base_url"] == "https://example.test/v1"
    assert captured["model"] == "text-embedding-3-small"
    assert len(result[0]) == 1536


def test_build_openai_embedding_service_returns_none_without_key():
    service = build_openai_embedding_service(Settings(openai_api_key=None))

    assert service is None


def test_build_openai_embedding_service_uses_agenttrace_settings(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("AGENTTRACE_OPENAI_API_KEY", "agenttrace-key")
    monkeypatch.setenv("AGENTTRACE_OPENAI_API_BASE", "https://api.openai.com/v1")

    service = build_openai_embedding_service(get_settings(), max_retries=1)

    assert service is not None
    assert service.model == "text-embedding-3-small"
    assert service.dimension == 1536
    assert service.provider.api_key == "agenttrace-key"
    assert service.provider.base_url == "https://api.openai.com/v1"


def test_chunk_embedding_service_embeds_chunk_content_and_pairs_ids():
    provider = FakeProvider(vectors=[[0.1] * 1536, [0.2] * 1536])
    service = ChunkEmbeddingService(
        embedding_service=EmbeddingService(
            provider=provider,
            model="text-embedding-3-small",
            dimension=1536,
            max_retries=1,
        )
    )
    chunks = [
        {"chunk_id": "chunk-a", "content": "alpha"},
        {"chunk_id": "chunk-b", "content": "beta"},
    ]

    rows = service.embed_chunks(chunks)

    assert rows == [
        {"chunk_id": "chunk-a", "embedding": [0.1] * 1536},
        {"chunk_id": "chunk-b", "embedding": [0.2] * 1536},
    ]


def test_chunk_embedding_service_skips_empty_chunks():
    provider = FakeProvider(vectors=[[0.1] * 1536])
    service = ChunkEmbeddingService(
        embedding_service=EmbeddingService(
            provider=provider,
            model="text-embedding-3-small",
            dimension=1536,
            max_retries=1,
        )
    )

    rows = service.embed_chunks([
        {"chunk_id": "chunk-a", "content": ""},
        {"chunk_id": "chunk-b", "content": "beta"},
    ])

    assert rows[0]["chunk_id"] == "chunk-b"


def test_source_chunk_embedding_update_sql_contract():
    sql = PostgresChunkEmbeddingSql.update_embeddings()

    assert "UPDATE source_chunks" in sql
    assert "embedding = data.embedding::vector" in sql
    assert "FROM jsonb_to_recordset" in sql
    assert "chunk_id" in sql


def test_postgres_chunk_embedding_store_updates_rows():
    class RecordingConnection:
        def __init__(self):
            self.calls = []

        def execute(self, sql, params=None):
            self.calls.append((sql, params or {}))
            return [{"chunk_id": "chunk-a"}]

    conn = RecordingConnection()
    store = PostgresChunkEmbeddingStore(conn)

    rows = store.update_embeddings([{"chunk_id": "chunk-a", "embedding": [0.1] * 1536}])

    assert rows == [{"chunk_id": "chunk-a"}]
    assert "UPDATE source_chunks" in conn.calls[0][0]
    assert conn.calls[0][1]["rows"][0]["chunk_id"] == "chunk-a"
