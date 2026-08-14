"""Data query tool (observe class): CSV/JSON/JSONL overview, filter, stats, head."""
import json
from pathlib import Path

import pytest

from praxic.tools.base import ToolStatus
from praxic.tools.data_query import DataQueryTool
from praxic.tools.registry import ToolRegistry


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "people.csv").write_text(
        "name,age,city\n张三,25,北京\n李四,32,上海\n王五,28,北京\n赵六,45,广州\n",
        encoding="utf-8",
    )
    (tmp_path / "events.json").write_text(
        json.dumps([
            {"id": 1, "value": 10.5, "tag": "a"},
            {"id": 2, "value": 20.0, "tag": "b"},
            {"id": 3, "value": 5.25, "tag": "a"},
        ], ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "log.jsonl").write_text(
        '{"ts": 1, "level": "info"}\n{"ts": 2, "level": "error"}\n{"ts": 3, "level": "info"}\n',
        encoding="utf-8",
    )
    return tmp_path


@pytest.mark.asyncio
async def test_csv_overview(ws):
    tool = DataQueryTool(ws)
    result = await tool.run("people.csv")
    assert result.status == ToolStatus.SUCCESS
    assert "4" in result.content
    assert "name" in result.content and "age" in result.content and "city" in result.content


@pytest.mark.asyncio
async def test_csv_filter_numeric(ws):
    tool = DataQueryTool(ws)
    result = await tool.run("people.csv", action="filter", condition="age > 30")
    assert result.status == ToolStatus.SUCCESS
    assert result.data["count"] == 2  # 李四32、赵六45
    assert result.data["returned"] == 2


@pytest.mark.asyncio
async def test_csv_filter_string(ws):
    tool = DataQueryTool(ws)
    result = await tool.run("people.csv", action="filter", condition="city == 北京")
    assert result.status == ToolStatus.SUCCESS
    assert result.data["count"] == 2  # 张三、王五


@pytest.mark.asyncio
async def test_csv_stats(ws):
    tool = DataQueryTool(ws)
    result = await tool.run("people.csv", action="stats", fields=["age"])
    assert result.status == ToolStatus.SUCCESS
    stats = result.data["stats"]["age"]
    assert stats["count"] == 4
    assert stats["min"] == 25
    assert stats["max"] == 45
    assert stats["mean"] == (25 + 32 + 28 + 45) / 4


@pytest.mark.asyncio
async def test_json_filter_and_stats(ws):
    tool = DataQueryTool(ws)
    result = await tool.run("events.json", action="filter", condition="tag == a")
    assert result.data["count"] == 2
    stats = await tool.run("events.json", action="stats", fields=["value"])
    assert round(stats.data["stats"]["value"]["mean"], 4) == round((10.5 + 20.0 + 5.25) / 3, 4)


@pytest.mark.asyncio
async def test_jsonl_overview_and_filter(ws):
    tool = DataQueryTool(ws)
    overview = await tool.run("log.jsonl")
    assert overview.status == ToolStatus.SUCCESS
    assert "3" in overview.content
    filtered = await tool.run("log.jsonl", action="filter", condition="level == error")
    assert filtered.data["count"] == 1


@pytest.mark.asyncio
async def test_head_with_fields_and_limit(ws):
    tool = DataQueryTool(ws)
    result = await tool.run("people.csv", action="head", fields=["name"], limit=2)
    assert result.status == ToolStatus.SUCCESS
    assert len(result.data["rows"]) == 2
    assert all(list(r.keys()) == ["name"] for r in result.data["rows"])


@pytest.mark.asyncio
async def test_unsupported_format(ws):
    tool = DataQueryTool(ws)
    (ws / "data.txt").write_text("x", encoding="utf-8")
    result = await tool.run("data.txt")
    assert result.status == ToolStatus.ERROR


@pytest.mark.asyncio
async def test_missing_file_and_path_escape(ws):
    tool = DataQueryTool(ws)
    result = await tool.run("nope.csv")
    assert result.status == ToolStatus.ERROR
    result = await tool.run("../escape.csv")
    assert result.status == ToolStatus.ERROR


@pytest.mark.asyncio
async def test_bad_condition(ws):
    tool = DataQueryTool(ws)
    result = await tool.run("people.csv", action="filter", condition="gibberish")
    assert result.status == ToolStatus.ERROR


@pytest.mark.asyncio
async def test_group_by_city(ws):
    tool = DataQueryTool(ws)
    result = await tool.run("people.csv", action="group", fields=["city"])
    assert result.status == ToolStatus.SUCCESS
    assert result.data["groups"]["北京"]["count"] == 2
    assert result.data["groups"]["上海"]["count"] == 1


@pytest.mark.asyncio
async def test_group_with_value_field(ws):
    tool = DataQueryTool(ws)
    result = await tool.run("people.csv", action="group", fields=["city", "age"])
    assert result.status == ToolStatus.SUCCESS
    # 北京两行 age 25+28=53
    assert result.data["groups"]["北京"]["sum"] == 53


@pytest.mark.asyncio
async def test_missing_stats(ws):
    tool = DataQueryTool(ws)
    (ws / "dirty.csv").write_text("name,age\n张三,25\n李四,\n王五,30\n", encoding="utf-8")
    result = await tool.run("dirty.csv", action="missing")
    assert result.status == ToolStatus.SUCCESS
    assert result.data["missing"]["age"]["missing"] == 1
    assert result.data["total"] == 3


@pytest.mark.asyncio
async def test_registered_and_describable(ws):
    registry = ToolRegistry()
    registry.register(DataQueryTool(ws))
    assert "data_query" in registry.get_names()
    descs = {d["name"]: d for d in registry.tool_descriptions()}
    assert descs["data_query"]["action_kind"] == "observe"
    assert "data_query" in registry.format_for_prompt()
