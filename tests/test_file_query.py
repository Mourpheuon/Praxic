"""File query tools (observe class): file_grep, file_batch_read, file_stat."""
import pytest

from praxic.tools.file_query import (
    FileBatchReadTool,
    FileGrepTool,
    FileStatTool,
)
from praxic.tools.base import ToolStatus
from praxic.tools.registry import ToolRegistry


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "a.py").write_text("import os\nvalue = 42\nprint(value)\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("hello world\nvalue=7\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.py").write_text("import sys\n# value placeholder\n", encoding="utf-8")
    return tmp_path


@pytest.mark.asyncio
async def test_grep_finds_matches_across_files(ws):
    tool = FileGrepTool(ws)
    result = await tool.run("value")
    assert result.status == ToolStatus.SUCCESS
    assert result.data["match_count"] == 4  # a.py:2 lines + b.txt:1 + sub/c.py:1
    assert "a.py:2" in result.content
    assert "b.txt:2" in result.content
    assert "sub/c.py:2" in result.content


@pytest.mark.asyncio
async def test_grep_respects_glob_and_recursive(ws):
    tool = FileGrepTool(ws)
    result = await tool.run("value", glob="*.py")
    assert result.data["match_count"] == 3  # a.py(2) + sub/c.py(1), excludes b.txt
    result = await tool.run("value", recursive=False)
    assert result.data["match_count"] == 3  # top-level only: a.py(2) + b.txt(1)


@pytest.mark.asyncio
async def test_grep_regex_and_ignore_case(ws):
    tool = FileGrepTool(ws)
    result = await tool.run("^VALUE", ignore_case=True)
    assert result.data["match_count"] >= 1


@pytest.mark.asyncio
async def test_grep_invalid_regex_returns_error(ws):
    tool = FileGrepTool(ws)
    result = await tool.run("([unclosed")
    assert result.status == ToolStatus.ERROR


@pytest.mark.asyncio
async def test_grep_no_match(ws):
    tool = FileGrepTool(ws)
    result = await tool.run("zzz_nothing")
    assert result.status == ToolStatus.SUCCESS
    assert result.data["match_count"] == 0


@pytest.mark.asyncio
async def test_grep_blocks_path_escape(ws):
    tool = FileGrepTool(ws)
    import os
    result = await tool.run("value", path="../")
    assert result.status == ToolStatus.ERROR


@pytest.mark.asyncio
async def test_batch_read_multiple_files_with_truncation(ws):
    tool = FileBatchReadTool(ws)
    long_file = ws / "long.txt"
    long_file.write_text("\n".join(f"line{i}" for i in range(500)), encoding="utf-8")
    result = await tool.run(["a.py", "long.txt", "missing.txt"], max_lines_per_file=50)
    assert result.status == ToolStatus.SUCCESS
    assert result.data["files"]["a.py"]["exists"] is True
    assert result.data["files"]["long.txt"]["truncated"] is True
    assert result.data["files"]["missing.txt"]["exists"] is False
    assert "### a.py" in result.content


@pytest.mark.asyncio
async def test_batch_read_empty_paths(ws):
    tool = FileBatchReadTool(ws)
    result = await tool.run([])
    assert result.status == ToolStatus.ERROR


@pytest.mark.asyncio
async def test_stat_file_metadata(ws):
    tool = FileStatTool(ws)
    result = await tool.run("a.py")
    assert result.status == ToolStatus.SUCCESS
    assert result.data["kind"] == "file"
    assert result.data["size_bytes"] > 0
    assert len(result.data["sha256"]) == 64


@pytest.mark.asyncio
async def test_stat_directory_and_missing(ws):
    tool = FileStatTool(ws)
    result = await tool.run("sub")
    assert result.status == ToolStatus.SUCCESS
    assert result.data["kind"] == "directory"
    result = await tool.run("nope.txt")
    assert result.status == ToolStatus.ERROR


@pytest.mark.asyncio
async def test_file_query_tools_registered_and_describable(ws):
    registry = ToolRegistry()
    registry.register(FileGrepTool(ws))
    registry.register(FileBatchReadTool(ws))
    registry.register(FileStatTool(ws))
    names = registry.get_names()
    assert "file_grep" in names
    assert "file_batch_read" in names
    assert "file_stat" in names
    descs = registry.tool_descriptions()
    by_name = {d["name"]: d for d in descs}
    assert by_name["file_grep"]["action_kind"] == "observe"
    assert by_name["file_grep"]["parameters"]["pattern"]["type"] == "string"
    assert by_name["file_batch_read"]["action_kind"] == "observe"
    assert by_name["file_stat"]["action_kind"] == "observe"


@pytest.mark.asyncio
async def test_file_query_tools_appear_in_prompt(ws):
    registry = ToolRegistry()
    registry.register(FileGrepTool(ws))
    registry.register(FileBatchReadTool(ws))
    registry.register(FileStatTool(ws))
    prompt = registry.format_for_prompt()
    assert "file_grep" in prompt
    assert "file_batch_read" in prompt
    assert "file_stat" in prompt
