"""tests/test_file_catalog.py

build_file_catalog 노드 및 관련 헬퍼 함수 테스트.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# _classify_file 단위 테스트
# ---------------------------------------------------------------------------

def test_classify_source_files():
    from agenttrace.agents.analysis.nodes.build_file_catalog import _classify_file

    assert _classify_file("src/main.py") == "source"
    assert _classify_file("lib/utils.ts") == "source"
    assert _classify_file("app/server.go") == "source"
    assert _classify_file("core/engine.rs") == "source"


def test_classify_critical_config():
    from agenttrace.agents.analysis.nodes.build_file_catalog import _classify_file

    assert _classify_file("pyproject.toml") == "critical_config"
    assert _classify_file("Dockerfile") == "critical_config"
    assert _classify_file(".github/workflows/ci.yml") == "critical_config"
    assert _classify_file("docker-compose.yaml") == "critical_config"
    assert _classify_file("package.json") == "critical_config"


def test_classify_docs():
    from agenttrace.agents.analysis.nodes.build_file_catalog import _classify_file

    assert _classify_file("README.md") == "docs"
    assert _classify_file("docs/guide.mdx") == "docs"
    assert _classify_file("CHANGELOG.md") == "docs"


def test_classify_test_files():
    from agenttrace.agents.analysis.nodes.build_file_catalog import _classify_file

    assert _classify_file("tests/test_api.py") == "test"
    assert _classify_file("test/unit/service_test.go") == "test"
    assert _classify_file("src/main_test.go") == "test"
    assert _classify_file("spec/user_spec.rb") == "test"


def test_classify_other():
    from agenttrace.agents.analysis.nodes.build_file_catalog import _classify_file

    assert _classify_file("scripts/migrate.sh") == "other"
    assert _classify_file("data/seed.csv") == "other"


# ---------------------------------------------------------------------------
# build_file_catalog 노드 단위 테스트
# ---------------------------------------------------------------------------

def _make_state(file_tree_paths: list[str]) -> dict:
    return {
        "run_id": "test-run",
        "file_tree": [{"path": p} for p in file_tree_paths],
    }


def test_catalog_node_populates_file_catalog():
    from agenttrace.agents.analysis.nodes.build_file_catalog import build_file_catalog

    state = _make_state(["src/a.py", "pyproject.toml", "README.md"])
    result = build_file_catalog(state)

    catalog = result["file_catalog"]
    assert len(catalog) == 3
    paths = {e["path"] for e in catalog}
    assert paths == {"src/a.py", "pyproject.toml", "README.md"}


def test_catalog_node_critical_config_paths():
    from agenttrace.agents.analysis.nodes.build_file_catalog import build_file_catalog

    state = _make_state([
        "src/main.py",
        "pyproject.toml",
        "Dockerfile",
        ".github/workflows/ci.yml",
    ])
    result = build_file_catalog(state)

    critical = set(result["critical_config_paths"])
    assert "pyproject.toml" in critical
    assert "Dockerfile" in critical
    assert ".github/workflows/ci.yml" in critical
    assert "src/main.py" not in critical


def test_catalog_node_preserves_existing_size():
    from agenttrace.agents.analysis.nodes.build_file_catalog import build_file_catalog

    state = {
        "run_id": "test-run",
        "file_tree": [{"path": "src/a.py", "size": 1234}],
    }
    result = build_file_catalog(state)
    entry = result["file_catalog"][0]
    assert entry["size"] == 1234


def test_catalog_node_empty_tree():
    from agenttrace.agents.analysis.nodes.build_file_catalog import build_file_catalog

    result = build_file_catalog({"run_id": "x", "file_tree": []})
    assert result["file_catalog"] == []
    assert result["critical_config_paths"] == []


# ---------------------------------------------------------------------------
# analysis_planner — file_catalog 통합 테스트
# ---------------------------------------------------------------------------

def test_planner_uses_catalog_for_target_paths():
    """file_catalog가 있으면 source 카테고리 파일이 target_paths에 포함된다."""
    from agenttrace.agents.analysis.nodes.legacy.analysis_planner import analysis_planner

    state = {
        "run_id": "test-run",
        "claims": [
            {
                "claim_id": "c1",
                "claim_text": "provides an MCP server with tool support",
            }
        ],
        "file_tree": [{"path": "server.py"}, {"path": "pyproject.toml"}],
        "file_catalog": [
            {"path": "server.py", "category": "source", "ext": ".py", "size": 500},
            {"path": "pyproject.toml", "category": "critical_config", "ext": ".toml", "size": 200},
        ],
        "critical_config_paths": ["pyproject.toml"],
    }
    result = analysis_planner(state)
    tasks = result["analysis_plan"]["tasks"]
    assert tasks, "태스크가 최소 1개 이상 생성돼야 한다"

    all_targets = {p for task in tasks for p in task["target_paths"]}
    # 중요 설정 파일은 모든 태스크의 target_paths에 포함돼야 한다
    assert "pyproject.toml" in all_targets


def test_planner_includes_critical_configs_in_every_task():
    """critical_config_paths는 태스크 수와 무관하게 모든 target_paths에 포함된다."""
    from agenttrace.agents.analysis.nodes.legacy.analysis_planner import analysis_planner

    state = {
        "run_id": "test-run",
        "claims": [
            {"claim_id": "c1", "claim_text": "MCP server with tools"},
            {"claim_id": "c2", "claim_text": "supports eval harness benchmarks"},
        ],
        "file_tree": [{"path": "src/server.py"}, {"path": "pyproject.toml"}],
        "file_catalog": [
            {"path": "src/server.py", "category": "source", "ext": ".py", "size": 800},
            {"path": "pyproject.toml", "category": "critical_config", "ext": ".toml", "size": 300},
        ],
        "critical_config_paths": ["pyproject.toml"],
    }
    result = analysis_planner(state)
    for task in result["analysis_plan"]["tasks"]:
        assert "pyproject.toml" in task["target_paths"], (
            f"task {task['task_id']}의 target_paths에 pyproject.toml이 없습니다"
        )
