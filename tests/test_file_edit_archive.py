"""File edit + archive extract tools (change class)."""
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from praxic.tools.archive import ArchiveExtractTool
from praxic.tools.base import ToolStatus
from praxic.tools.filesystem import FileEditTool
from praxic.tools.registry import ToolRegistry


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "config.txt").write_text(
        "host=localhost\nport=8080\nhost=localhost\n", encoding="utf-8"
    )
    return tmp_path


@pytest.mark.asyncio
async def test_edit_unique_replace(ws):
    tool = FileEditTool(ws)
    result = await tool.run("config.txt", "port=8080", "port=9090")
    assert result.status == ToolStatus.SUCCESS
    assert "1 处" in result.content
    content = (ws / "config.txt").read_text(encoding="utf-8")
    assert "port=9090" in content and "port=8080" not in content
    assert result.change is not None
    # 直接调 verify（registry 路径也会做同样的回读验证）
    verification = await tool.verify({"path": "config.txt", "old_text": "port=8080", "new_text": "port=9090"}, result)
    assert verification.ok


@pytest.mark.asyncio
async def test_edit_non_unique_requires_context(ws):
    tool = FileEditTool(ws)
    result = await tool.run("config.txt", "host=localhost", "host=example.com")
    assert result.status == ToolStatus.ERROR
    assert "不唯一" in result.error
    # 文件未被改动
    assert (ws / "config.txt").read_text(encoding="utf-8").count("host=localhost") == 2


@pytest.mark.asyncio
async def test_edit_count_explicit_all(ws):
    tool = FileEditTool(ws)
    result = await tool.run("config.txt", "host=localhost", "host=example.com", count=2)
    assert result.status == ToolStatus.SUCCESS
    assert "2 处" in result.content
    assert (ws / "config.txt").read_text(encoding="utf-8").count("host=example.com") == 2


@pytest.mark.asyncio
async def test_edit_missing_text(ws):
    tool = FileEditTool(ws)
    result = await tool.run("config.txt", "nothere", "x")
    assert result.status == ToolStatus.ERROR
    assert "未找到" in result.error


@pytest.mark.asyncio
async def test_edit_missing_file(ws):
    tool = FileEditTool(ws)
    result = await tool.run("nope.txt", "a", "b")
    assert result.status == ToolStatus.ERROR


@pytest.mark.asyncio
async def test_edit_blocks_path_escape(ws):
    tool = FileEditTool(ws)
    result = await tool.run("../escape.txt", "a", "b")
    assert result.status == ToolStatus.ERROR


@pytest.mark.asyncio
async def test_archive_extract_zip(ws):
    tool = ArchiveExtractTool(ws)
    archive = ws / "data.zip"
    with zipfile.ZipFile(str(archive), "w") as zf:
        zf.writestr("inner/a.txt", "hello")
        zf.writestr("inner/b.txt", "world")
    result = await tool.run("data.zip", "out")
    assert result.status == ToolStatus.SUCCESS
    # 条目共享顶层 inner/，剥离后落到 out/ 下
    assert (ws / "out" / "a.txt").read_text(encoding="utf-8") == "hello"
    assert (ws / "out" / "b.txt").read_text(encoding="utf-8") == "world"


@pytest.mark.asyncio
async def test_archive_extract_zip_no_common_prefix(ws):
    """无公共顶层目录时保留完整结构。"""
    tool = ArchiveExtractTool(ws)
    archive = ws / "mixed.zip"
    with zipfile.ZipFile(str(archive), "w") as zf:
        zf.writestr("a.txt", "a")
        zf.writestr("sub/b.txt", "b")
    result = await tool.run("mixed.zip", "out")
    assert result.status == ToolStatus.SUCCESS
    assert (ws / "out" / "a.txt").read_text(encoding="utf-8") == "a"
    assert (ws / "out" / "sub" / "b.txt").read_text(encoding="utf-8") == "b"


@pytest.mark.asyncio
async def test_archive_extract_tar_gz(ws):
    tool = ArchiveExtractTool(ws)
    archive = ws / "data.tar.gz"
    with tarfile.open(str(archive), "w:gz") as tf:
        data = b"payload"
        info = tarfile.TarInfo("inner/x.txt")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    result = await tool.run("data.tar.gz", "out")
    assert result.status == ToolStatus.SUCCESS
    assert (ws / "out" / "inner" / "x.txt").read_bytes() == b"payload"


@pytest.mark.asyncio
async def test_archive_blocks_zip_slip(ws):
    tool = ArchiveExtractTool(ws)
    archive = ws / "evil.zip"
    with zipfile.ZipFile(str(archive), "w") as zf:
        zf.writestr("../evil.txt", "escape")
    result = await tool.run("evil.zip", "out")
    assert result.status == ToolStatus.ERROR
    assert not (ws.parent / "evil.txt").exists()


@pytest.mark.asyncio
async def test_archive_unsupported_format(ws):
    tool = ArchiveExtractTool(ws)
    (ws / "plain.txt").write_text("x", encoding="utf-8")
    result = await tool.run("plain.txt", "out")
    assert result.status == ToolStatus.ERROR


@pytest.mark.asyncio
async def test_edit_and_archive_registered_and_describable(ws):
    registry = ToolRegistry()
    registry.register(FileEditTool(ws))
    registry.register(ArchiveExtractTool(ws))
    names = registry.get_names()
    assert "file_edit" in names
    assert "archive_extract" in names
    descs = {d["name"]: d for d in registry.tool_descriptions()}
    assert descs["file_edit"]["action_kind"] == "change"
    assert descs["archive_extract"]["action_kind"] == "change"
    prompt = registry.format_for_prompt()
    assert "file_edit" in prompt and "archive_extract" in prompt
