from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class ContentChunk(BaseModel):
    chunk_id: str
    file_path: str
    content: str
    symbol: str | None = None
    start_byte: int = Field(ge=0)
    end_byte: int = Field(ge=0)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    is_partial: bool
    content_hash: str

    @model_validator(mode="after")
    def validate_ranges(self) -> ContentChunk:
        if self.start_byte > self.end_byte:
            raise ValueError("start_byte must be less than or equal to end_byte")
        if self.line_start > self.line_end:
            raise ValueError("line_start must be less than or equal to line_end")
        return self


class ChunkIndexEntry(BaseModel):
    file_path: str
    chunk_ids: list[str]
    keywords: list[str] = Field(default_factory=list)
    chunk_count: int


class ChunkIndex(BaseModel):
    entries: list[ChunkIndexEntry] = Field(default_factory=list)
    chunks_by_id: dict[str, ContentChunk] = Field(default_factory=dict)
