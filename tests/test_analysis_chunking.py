from agenttrace.agents.analysis.chunking import build_chunk_index, chunk_source_files
from agenttrace.agents.analysis.chunking import source_chunk_table_contract_sql
from agenttrace.agents.analysis.schemas.input import SourceFile


def test_chunk_source_files_preserves_file_boundary_and_line_numbers():
    files = [SourceFile(path="src/server.py", content="line1\nline2\nline3")]
    chunks = chunk_source_files(files, target_size=100, overlap=0)

    assert len(chunks) == 1
    assert chunks[0].file_path == "src/server.py"
    assert chunks[0].line_start == 1
    assert chunks[0].line_end == 3
    assert chunks[0].is_partial is False


def test_build_chunk_index_extracts_path_keywords():
    files = [SourceFile(path="src/mcp/server.py", content="def register_tool(): pass")]
    chunks = chunk_source_files(files, target_size=100, overlap=0)
    index = build_chunk_index(chunks)

    entry = index.entries[0]
    assert entry.file_path == "src/mcp/server.py"
    assert "mcp" in entry.keywords
    assert "register_tool" in entry.keywords
    assert chunks[0].chunk_id in index.chunks_by_id


def test_chunk_source_files_uses_overlap_and_tracks_multichunk_ranges():
    source = SourceFile(path="src/example.py", content="aa\nbb\ncc\ndd")
    files = [source]
    chunks = chunk_source_files(files, target_size=5, overlap=2)

    assert len({chunk.chunk_id for chunk in chunks}) == 3
    assert all(len(chunk.chunk_id) == 64 for chunk in chunks)
    assert [(chunk.start_byte, chunk.end_byte) for chunk in chunks] == [
        (0, 5),
        (3, 8),
        (6, 11),
    ]
    assert [(chunk.line_start, chunk.line_end) for chunk in chunks] == [
        (1, 2),
        (2, 3),
        (3, 4),
    ]
    assert [chunk.is_partial for chunk in chunks] == [True, True, True]
    assert {chunk.content_hash for chunk in chunks} == {source.content_hash}


def test_chunk_source_files_tracks_utf8_byte_offsets_for_non_ascii_content():
    source = SourceFile(path="src/unicode.py", content="éabc")
    chunks = chunk_source_files([source], target_size=3, overlap=0)

    assert [chunk.content for chunk in chunks] == ["éa", "bc"]
    assert chunks[0].end_byte == len(chunks[0].content.encode("utf-8"))
    assert chunks[-1].end_byte == len(source.content.encode("utf-8"))
    assert [(chunk.line_start, chunk.line_end) for chunk in chunks] == [(1, 1), (1, 1)]


def test_build_chunk_index_groups_entries_sorted_by_path():
    files = [
        SourceFile(path="src/zeta.py", content="def zeta_value(): pass"),
        SourceFile(path="src/alpha.py", content="def alpha_value(): pass"),
    ]
    chunks = chunk_source_files(files, target_size=100, overlap=0)
    index = build_chunk_index(chunks)

    assert [entry.file_path for entry in index.entries] == [
        "src/alpha.py",
        "src/zeta.py",
    ]
    assert [entry.chunk_count for entry in index.entries] == [1, 1]


def test_chunk_id_is_stable_sha256_from_path_lines_and_content_hash():
    source = SourceFile(path="src/server.py", content="def create_app():\n    pass\n")
    first = chunk_source_files([source], target_size=100, overlap=0)[0]
    second = chunk_source_files([source], target_size=100, overlap=0)[0]

    assert first.chunk_id == second.chunk_id
    assert len(first.chunk_id) == 64
    assert first.chunk_id != "chunk-0001"


def test_python_chunk_extracts_symbol_for_function_unit():
    source = SourceFile(path="src/server.py", content="def create_app():\n    pass\n")
    chunk = chunk_source_files([source], target_size=100, overlap=0)[0]

    assert chunk.symbol == "create_app"


def test_source_chunk_table_contract_uses_pgvector_and_doc_columns():
    sql = source_chunk_table_contract_sql()

    assert "CREATE TABLE source_chunks" in sql
    assert "chunk_id" in sql
    assert "file_path" in sql
    assert "start_line" in sql
    assert "end_line" in sql
    assert "symbol" in sql
    assert "embedding vector(1536)" in sql
