"""loader 单元测试：group 嵌套、isolate 生效、disabled 白名单、坏行跳过、inject 环报错、缺 id/name 报错。"""

import sys

import pytest

from praxic.cordis import (
    CompositionError,
    Context,
    InjectCycleError,
    eval_disabled,
    load_composition,
)

FIX = "tests.cordis.fixtures"


def compose(text: str):
    ctx = Context()
    result = load_composition(text, ctx)
    return ctx, result


# ----------------------------------------------------------------------
# group 嵌套
# ----------------------------------------------------------------------
def test_group_nesting_flattened():
    ctx, res = compose(
        f"""
- id: outer
  group:
    - id: inner
      name: {FIX}:CounterService
    - id: sibling
      group:
        - id: deep
          name: {FIX}:CounterService
"""
    )
    assert set(res.activated) == {"inner", "deep"}
    assert ctx.has("inner")
    assert ctx.has("deep")
    assert not ctx.has("outer")  # group 行本身不产生服务


def test_group_path_recorded_in_rows():
    ctx, res = compose(
        f"""
- id: top
  group:
    - id: leaf
      name: {FIX}:CounterService
"""
    )
    leaf = [r for r in res.rows if r.id == "leaf"]
    assert leaf and leaf[0].group == ["top"]


# ----------------------------------------------------------------------
# isolate 声明
# ----------------------------------------------------------------------
def test_isolate_declaration_effective():
    ctx, res = compose(
        f"""
- id: llm
  name: {FIX}:CounterService
  isolate:
    llm: true
"""
    )
    assert "llm" in res.realms
    realm = res.realms["llm"]
    svc = realm.get("llm")
    assert svc is not None
    assert svc.name == "llm"
    # root 侧被隔离墙挡住：llm 不可见
    assert not ctx.has("llm")


def test_isolate_duplicate_in_same_realm_raises():
    """P2 收紧：同 realm 内同名第二次注册是组合级错误，直接抛 CompositionError。"""
    ctx = Context()
    with pytest.raises(CompositionError):
        compose(
            f"""
- id: llm
  name: {FIX}:CounterService
  isolate:
    llm: true
- id: llm
  name: {FIX}:CounterService
"""
        )


def test_isolate_shared_realm_reused():
    """两行都声明隔离 llm 时共享同一 realm（同 label 幂等复用）。"""
    ctx, res = compose(
        f"""
- id: first
  name: {FIX}:CounterService
  isolate:
    llm: true
- id: second
  name: {FIX}:CounterService
  isolate:
    llm: true
"""
    )
    assert len(res.realms) == 1
    # 两个不同服务名（first/second）都挂在 root，隔离声明不影响它们自身
    assert ctx.has("first")
    assert ctx.has("second")


# ----------------------------------------------------------------------
# disabled 白名单
# ----------------------------------------------------------------------
def test_disabled_boolean():
    ctx, res = compose(
        f"""
- id: sw_off
  name: {FIX}:CounterService
  disabled: true
- id: sw_on
  name: {FIX}:CounterService
  disabled: false
"""
    )
    assert "sw_off" not in res.activated
    assert "sw_on" in res.activated


def test_disabled_platform_mapping():
    ctx, res = compose(
        f"""
- id: here
  name: {FIX}:CounterService
  disabled:
    platform: {sys.platform}
- id: there
  name: {FIX}:CounterService
  disabled:
    platform: never-exists
"""
    )
    assert "here" not in res.activated
    assert "there" in res.activated


def test_disabled_env_mapping():
    ctx, res = compose(
        f"""
- id: envless
  name: {FIX}:CounterService
  disabled:
    env: CORDIS_TEST_DOES_NOT_EXIST_KEY
- id: envset
  name: {FIX}:CounterService
  disabled:
    env: PATH
"""
    )
    assert "envless" in res.activated
    assert "envset" not in res.activated


def test_disabled_string_form():
    assert eval_disabled("true") is True
    assert eval_disabled("false") is False
    assert eval_disabled("platform:win32|linux", platform="win32") is True
    assert eval_disabled("platform:win32|linux", platform="darwin") is False
    assert eval_disabled("env:KEY", env={"KEY": "1"}) is True
    assert eval_disabled("env:MISSING", env={}) is False


def test_disabled_unsupported_expression_raises():
    with pytest.raises(ValueError):
        eval_disabled("exec('x')")
    with pytest.raises(ValueError):
        eval_disabled(42)


def test_disabled_bad_expression_marks_row_failed():
    ctx, res = compose(
        f"""
- id: evil
  name: {FIX}:CounterService
  disabled: exec('x')
"""
    )
    assert "evil" not in res.activated
    assert any(rid == "evil" for rid, _ in res.failed)


# ----------------------------------------------------------------------
# 坏行跳过
# ----------------------------------------------------------------------
def test_bad_import_skipped():
    ctx, res = compose(
        """
- id: broken
  name: no.such.module:Thing
- id: good
  name: tests.cordis.fixtures:CounterService
"""
    )
    assert "good" in res.activated
    assert "broken" not in res.activated
    assert any(rid == "broken" for rid, _ in res.failed)
    assert ctx.has("good")


def test_config_validation_failure_skipped():
    ctx, res = compose(
        f"""
- id: badcfg
  name: {FIX}:StrictService
  config:
    threshold: 999
- id: goodcfg
  name: {FIX}:StrictService
  config:
    threshold: 5
"""
    )
    assert "goodcfg" in res.activated
    assert "badcfg" not in res.activated
    assert any(rid == "badcfg" for rid, _ in res.failed)


def test_missing_id_marks_failed():
    ctx, res = compose(
        f"""
- name: {FIX}:CounterService
"""
    )
    assert res.activated == []
    assert len(res.failed) >= 1
    assert res.rows and res.rows[0].ok is False


def test_boolean_like_id_is_bad_row():
    """YAML 1.1 会把 off/on 解析成布尔；这种 id 必须被判为坏行。"""
    ctx, res = compose(
        f"""
- id: off
  name: {FIX}:CounterService
- id: on
  name: {FIX}:CounterService
"""
    )
    assert res.activated == []
    assert len(res.failed) == 2


def test_missing_name_marks_failed():
    ctx, res = compose(
        """
- id: noname
"""
    )
    assert res.activated == []
    assert any(rid == "noname" for rid, _ in res.failed)


def test_inject_missing_dependency_skipped_not_fatal():
    """依赖不可用的行被跳过，组合继续。"""
    ctx, res = compose(
        f"""
- id: needllm
  name: {FIX}:CounterService
  inject: [llm]
- id: llm
  name: {FIX}:CounterService
"""
    )
    assert "llm" in res.activated
    assert "needllm" not in res.activated
    assert any(rid == "needllm" for rid, _ in res.failed)


def test_inject_satisfied_dependency_activates():
    """依赖先注册后，声明依赖的行可激活。"""
    ctx, res = compose(
        f"""
- id: llm
  name: {FIX}:CounterService
- id: needllm
  name: {FIX}:DepService
  inject: [llm]
  config:
    dep: llm
"""
    )
    assert "llm" in res.activated
    assert "needllm" in res.activated
    assert ctx.get("needllm").dep is ctx.get("llm")


# ----------------------------------------------------------------------
# inject 环
# ----------------------------------------------------------------------
def test_inject_cycle_raises():
    ctx = Context()
    with pytest.raises(InjectCycleError):
        load_composition(
            f"""
- id: a
  name: {FIX}:CounterService
  inject: [b]
- id: b
  name: {FIX}:CounterService
  inject: [a]
""",
            ctx,
        )


def test_inject_self_cycle_raises():
    ctx = Context()
    with pytest.raises(InjectCycleError):
        load_composition(
            f"""
- id: solo
  name: {FIX}:CounterService
  inject: [solo]
""",
            ctx,
        )


def test_inject_cycle_error_message_contains_cycle():
    ctx = Context()
    with pytest.raises(InjectCycleError) as exc_info:
        load_composition(
            f"""
- id: a
  name: {FIX}:CounterService
  inject: [b]
- id: b
  name: {FIX}:CounterService
  inject: [a]
""",
            ctx,
        )
    assert "a" in str(exc_info.value) and "b" in str(exc_info.value)


# ----------------------------------------------------------------------
# config 传递
# ----------------------------------------------------------------------
def test_config_passed_to_service():
    ctx, res = compose(
        f"""
- id: greet
  name: {FIX}:GreetingService
  config:
    greeting: 你好
"""
    )
    assert res.activated == ["greet"]
    assert ctx.get("greet").config.greeting == "你好"


def test_load_from_file_path(tmp_path):
    path = tmp_path / "agent.yml"
    path.write_text(
        f"""
- id: greet
  name: {FIX}:GreetingService
""",
        encoding="utf-8",
    )
    ctx = Context()
    res = load_composition(path, ctx)
    assert "greet" in res.activated
