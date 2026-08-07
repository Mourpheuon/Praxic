"""Plugin scanner (tier 3): manifest loading, registration, error handling."""
import sys
from pathlib import Path

import pytest

from praxic.tools.base import ToolStatus
from praxic.tools.permissions import PermissionPolicy
from praxic.tools.plugin import DeclaredTool, PluginScanner, load_plugins
from praxic.tools.registry import ToolRegistry

PLUGIN_MODULE = """\
async def run(text='world'):
    return {'content': f'hello {text}', 'echo': text}

async def risky():
    return 'risky result'
"""

GOOD_MANIFEST = """\
name: hello_tool
category: data
description: 测试插件
action_kind: observe
run: test_plugin_mod:run
"""


@pytest.fixture
def plugin_env(tmp_path, monkeypatch):
    # 插件目录：plugins/hello/manifest.yaml + 可 import 模块
    plugins_root = tmp_path / "plugins"
    (plugins_root / "hello").mkdir(parents=True)
    (plugins_root / "hello" / "manifest.yaml").write_text(GOOD_MANIFEST, encoding="utf-8")
    # 执行模块放 plugins_root 下，加入 sys.path
    (plugins_root / "test_plugin_mod.py").write_text(PLUGIN_MODULE, encoding="utf-8")
    monkeypatch.syspath_prepend(str(plugins_root))
    return plugins_root


def test_scan_loads_manifest(plugin_env):
    scanner = PluginScanner(plugin_env)
    tools = scanner.scan()
    assert len(tools) == 1
    tool = tools[0]
    assert tool.name == "hello_tool"
    assert tool.category == "data"
    assert tool.action_kind.value == "observe"
    assert tool.sandbox_safe is False  # 外部代码默认不信任


@pytest.mark.asyncio
async def test_plugin_callable(plugin_env):
    reg = ToolRegistry(policy=PermissionPolicy())
    count = load_plugins(reg, plugin_env)
    assert count == 1
    assert "hello_tool" in reg.get_names()
    result = await reg.call("hello_tool", text="Praxic")
    assert result.status == ToolStatus.SUCCESS
    assert "hello Praxic" in result.content
    # format 呈现
    assert "hello_tool" in reg.format_for_prompt()


def test_manifest_missing_run(plugin_env):
    (plugin_env / "hello" / "manifest.yaml").write_text(
        "name: bad_tool\ncategory: data\ndescription: x\naction_kind: observe\n",
        encoding="utf-8",
    )
    scanner = PluginScanner(plugin_env)
    tools = scanner.scan()  # 坏的跳过，不崩溃
    assert all(t.name != "bad_tool" for t in tools)


def test_manifest_bad_category(plugin_env):
    (plugin_env / "hello" / "manifest.yaml").write_text(
        "name: bad_tool\ncategory: unknown_xyz\ndescription: x\naction_kind: observe\nrun: test_plugin_mod:run\n",
        encoding="utf-8",
    )
    scanner = PluginScanner(plugin_env)
    assert scanner.scan() == []


def test_manifest_bad_action_kind(plugin_env):
    (plugin_env / "hello" / "manifest.yaml").write_text(
        "name: bad_tool\ncategory: data\ndescription: x\naction_kind: explode\nrun: test_plugin_mod:run\n",
        encoding="utf-8",
    )
    scanner = PluginScanner(plugin_env)
    assert scanner.scan() == []


def test_scan_missing_dir():
    scanner = PluginScanner(Path("C:/definitely/not/here/plugins"))
    assert scanner.scan() == []


def test_declared_tool_infers_params(plugin_env):
    scanner = PluginScanner(plugin_env)
    tool = scanner.scan()[0]
    assert "text" in tool.parameter_schema
    assert tool.parameter_schema["text"]["type"] == "string"
