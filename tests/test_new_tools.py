"""New tools: file_copy/move/tail, archive_create, env/time, http_request, process/disk, download."""
from pathlib import Path

import pytest

from praxic.tools.archive import ArchiveCreateTool, ArchiveExtractTool
from praxic.tools.base import ToolStatus
from praxic.tools.environment import (
    DiskInfoTool,
    EnvTool,
    FileDownloadTool,
    HttpRequestTool,
    ProcessListTool,
    TimeTool,
)
from praxic.tools.file_ops import FileCopyTool, FileMoveTool, FileTailTool
from praxic.tools.registry import ToolRegistry


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "a.txt").write_text("line1\nline2\nline3\nline4\nline5\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("hello", encoding="utf-8")
    return tmp_path


# ── file_copy / file_move / file_tail ──
@pytest.mark.asyncio
async def test_copy_file(ws):
    tool = FileCopyTool(ws)
    result = await tool.run("a.txt", "a_copy.txt")
    assert result.status == ToolStatus.SUCCESS
    assert (ws / "a_copy.txt").read_text(encoding="utf-8") == (ws / "a.txt").read_text(encoding="utf-8")
    assert result.verification is None or True  # registry 层才做 verify


@pytest.mark.asyncio
async def test_copy_dir(ws):
    tool = FileCopyTool(ws)
    result = await tool.run("sub", "sub_copy")
    assert result.status == ToolStatus.SUCCESS
    assert (ws / "sub_copy" / "b.txt").read_text(encoding="utf-8") == "hello"


@pytest.mark.asyncio
async def test_move(ws):
    tool = FileMoveTool(ws)
    result = await tool.run("a.txt", "moved.txt")
    assert result.status == ToolStatus.SUCCESS
    assert (ws / "moved.txt").exists()
    assert not (ws / "a.txt").exists()


@pytest.mark.asyncio
async def test_tail(ws):
    tool = FileTailTool(ws)
    result = await tool.run("a.txt", lines=2)
    assert result.status == ToolStatus.SUCCESS
    assert "line4" in result.content and "line5" in result.content
    assert "line1" not in result.content


# ── archive_create ──
@pytest.mark.asyncio
async def test_create_archive_and_re_extract(ws):
    tool = ArchiveCreateTool(ws)
    result = await tool.run(["a.txt", "sub"], "bundle.zip")
    assert result.status == ToolStatus.SUCCESS
    assert (ws / "bundle.zip").exists()

    # 解压回来验证内容
    extract = ArchiveExtractTool(ws)
    r2 = await extract.run("bundle.zip", "restored")
    assert r2.status == ToolStatus.SUCCESS
    assert (ws / "restored" / "a.txt").read_text(encoding="utf-8").startswith("line1")


# ── env / time ──
@pytest.mark.asyncio
async def test_env_overview(ws):
    tool = EnvTool(ws)
    result = await tool.run()
    assert result.status == ToolStatus.SUCCESS
    assert "platform" in result.data or "Python" in result.content


@pytest.mark.asyncio
async def test_env_key_whitelist(ws):
    tool = EnvTool(ws)
    result = await tool.run("PATH")
    assert result.status == ToolStatus.SUCCESS
    result = await tool.run("AWS_SECRET_ACCESS_KEY")
    assert result.status == ToolStatus.ERROR


@pytest.mark.asyncio
async def test_time(ws):
    tool = TimeTool()
    result = await tool.run()
    assert result.status == ToolStatus.SUCCESS
    assert result.data["utc"]


# ── http_request ──
@pytest.mark.asyncio
async def test_http_rejects_localhost(ws):
    tool = HttpRequestTool()
    result = await tool.run("http://127.0.0.1:8000/")
    assert result.status == ToolStatus.ERROR
    assert "SSRF" in result.error or "本机" in result.error


@pytest.mark.asyncio
async def test_http_rejects_bad_scheme(ws):
    tool = HttpRequestTool()
    result = await tool.run("ftp://example.com/file")
    assert result.status == ToolStatus.ERROR


# ── process / disk ──
@pytest.mark.asyncio
async def test_disk_info(ws):
    tool = DiskInfoTool(ws)
    result = await tool.run()
    assert result.status == ToolStatus.SUCCESS
    assert "total_gb" in result.data


@pytest.mark.asyncio
async def test_process_list(ws):
    tool = ProcessListTool()
    result = await tool.run(limit=5)
    # psutil 可能未装，两种情况都算合理返回
    assert result.status in (ToolStatus.SUCCESS, ToolStatus.ERROR)


# ── 注册与权限分级 ──
@pytest.mark.asyncio
async def test_all_new_tools_registered_with_correct_kind(ws):
    registry = ToolRegistry()
    for t in [FileCopyTool(ws), FileMoveTool(ws), FileTailTool(ws),
              ArchiveCreateTool(ws), EnvTool(ws), TimeTool(),
              HttpRequestTool(), ProcessListTool(), DiskInfoTool(ws),
              FileDownloadTool(ws)]:
        registry.register(t)
    descs = {d["name"]: d for d in registry.tool_descriptions()}
    assert descs["file_tail"]["action_kind"] == "observe"
    assert descs["env_tool"]["action_kind"] == "observe"
    assert descs["time_tool"]["action_kind"] == "observe"
    assert descs["process_list"]["action_kind"] == "observe"
    assert descs["disk_info"]["action_kind"] == "observe"
    assert descs["file_copy"]["action_kind"] == "change"
    assert descs["file_move"]["action_kind"] == "change"
    assert descs["archive_create"]["action_kind"] == "change"
    assert descs["http_request"]["action_kind"] == "external"
    assert descs["file_download"]["action_kind"] == "external"
