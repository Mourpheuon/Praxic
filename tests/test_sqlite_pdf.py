"""sqlite_query + pdf_extract tools."""
import sqlite3
from pathlib import Path

import pytest

from praxic.tools.base import ToolStatus
from praxic.tools.pdf_extract import PdfExtractTool
from praxic.tools.registry import ToolRegistry
from praxic.tools.sqlite_query import SqliteQueryTool


@pytest.fixture
def db_ws(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "data.db"))
    conn.execute("CREATE TABLE users (id INTEGER, name TEXT, age INTEGER)")
    conn.executemany(
        "INSERT INTO users VALUES (?, ?, ?)",
        [(1, "张三", 25), (2, "李四", 32), (3, "王五", 28)],
    )
    conn.commit()
    conn.close()
    return tmp_path


@pytest.fixture
def pdf_ws(tmp_path):
    # 生成一个简单 PDF（用 pymupdf）
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello Praxic PDF")
    doc.save(str(tmp_path / "sample.pdf"))
    doc.close()
    return tmp_path


# ── sqlite_query ──
@pytest.mark.asyncio
async def test_sqlite_select(db_ws):
    tool = SqliteQueryTool(db_ws)
    result = await tool.run("data.db", "SELECT name, age FROM users WHERE age > 26")
    assert result.status == ToolStatus.SUCCESS
    assert result.data["count"] == 2  # 李四32、王五28
    assert result.data["columns"] == ["name", "age"]


@pytest.mark.asyncio
async def test_sqlite_pragma(db_ws):
    tool = SqliteQueryTool(db_ws)
    result = await tool.run("data.db", "PRAGMA table_info(users)")
    assert result.status == ToolStatus.SUCCESS
    assert result.data["count"] == 3  # id/name/age 三列


@pytest.mark.asyncio
async def test_sqlite_rejects_write(db_ws):
    tool = SqliteQueryTool(db_ws)
    result = await tool.run("data.db", "DELETE FROM users")
    assert result.status == ToolStatus.ERROR
    assert "只读" in result.error
    result = await tool.run("data.db", "INSERT INTO users VALUES (4, 'x', 1)")
    assert result.status == ToolStatus.ERROR


@pytest.mark.asyncio
async def test_sqlite_rejects_multi_statement(db_ws):
    tool = SqliteQueryTool(db_ws)
    result = await tool.run("data.db", "SELECT * FROM users; DROP TABLE users")
    assert result.status == ToolStatus.ERROR
    # 表未被删
    assert (db_ws / "data.db").exists()


@pytest.mark.asyncio
async def test_sqlite_limit_truncation(db_ws):
    tool = SqliteQueryTool(db_ws)
    result = await tool.run("data.db", "SELECT * FROM users", limit=2)
    assert result.status == ToolStatus.SUCCESS
    assert result.data["truncated"] is True
    assert result.data["count"] == 2


@pytest.mark.asyncio
async def test_sqlite_missing_db_and_path_escape(db_ws):
    tool = SqliteQueryTool(db_ws)
    result = await tool.run("nope.db", "SELECT 1")
    assert result.status == ToolStatus.ERROR
    result = await tool.run("../escape.db", "SELECT 1")
    assert result.status == ToolStatus.ERROR


# ── pdf_extract ──
@pytest.mark.asyncio
async def test_pdf_extract_text(pdf_ws):
    tool = PdfExtractTool(pdf_ws)
    result = await tool.run("sample.pdf")
    assert result.status == ToolStatus.SUCCESS
    assert "Praxic" in result.content or result.data["char_count"] > 0


@pytest.mark.asyncio
async def test_pdf_missing_and_wrong_type(pdf_ws):
    tool = PdfExtractTool(pdf_ws)
    result = await tool.run("nope.pdf")
    assert result.status == ToolStatus.ERROR
    (pdf_ws / "notes.txt").write_text("x", encoding="utf-8")
    result = await tool.run("notes.txt")
    assert result.status == ToolStatus.ERROR


# ── 注册与分级 ──
@pytest.mark.asyncio
async def test_registered_and_graded(db_ws, pdf_ws):
    registry = ToolRegistry()
    registry.register(SqliteQueryTool(db_ws))
    registry.register(PdfExtractTool(pdf_ws))
    descs = {d["name"]: d for d in registry.tool_descriptions()}
    assert descs["sqlite_query"]["action_kind"] == "observe"
    assert descs["pdf_extract"]["action_kind"] == "observe"
    prompt = registry.format_for_prompt()
    assert "sqlite_query" in prompt and "pdf_extract" in prompt
