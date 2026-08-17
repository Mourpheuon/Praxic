"""P1 验收：组合装配（build_loop_from_composition）与旧构造路径行为等价。

对比维度：registry 工具集、阶段模块类型、policy 配置、运行时参数、
workspace 路径与 LLM 类型。
"""

import pytest

from praxic.cordis import CompositionError, Context, load_composition
from praxic.core.assembly import build_loop_from_composition
from praxic.core.cognitive_loop import CognitiveLoop


def _phase_types(loop) -> dict:
    return {
        name: type(getattr(loop, name)).__name__
        for name in (
            "investigation",
            "preprocessing",
            "contradiction",
            "rational",
            "practice",
            "reflection",
        )
    }


def _registry(loop):
    return loop._registry


# ----------------------------------------------------------------------
# 等价性
# ----------------------------------------------------------------------
def test_registry_tool_sets_equivalent():
    legacy = CognitiveLoop()
    composed = build_loop_from_composition(Context())
    assert set(_registry(composed).get_names()) == set(_registry(legacy).get_names())


def test_registry_tool_sets_nonempty():
    composed = build_loop_from_composition(Context())
    assert len(composed._registry.get_names()) >= 20


def test_phase_module_types_equivalent():
    legacy = CognitiveLoop()
    composed = build_loop_from_composition(Context())
    assert _phase_types(composed) == _phase_types(legacy)


def test_policy_config_equivalent():
    legacy = CognitiveLoop()
    composed = build_loop_from_composition(Context())
    assert (
        composed._registry.policy.permission_mode
        == legacy._registry.policy.permission_mode
    )
    assert composed._registry.policy.allow_network == legacy._registry.policy.allow_network
    assert (
        composed._registry.policy.allowed_roots
        == legacy._registry.policy.allowed_roots
    )


def test_runtime_params_equivalent():
    legacy = CognitiveLoop()
    composed = build_loop_from_composition(Context())
    assert composed.max_iterations == legacy.max_iterations
    assert composed.convergence_threshold == legacy.convergence_threshold
    assert composed.enable_trajectory_logging == legacy.enable_trajectory_logging
    assert composed.review_strategy == legacy.review_strategy


def test_llm_type_equivalent():
    legacy = CognitiveLoop()
    composed = build_loop_from_composition(Context())
    assert type(composed.llm) is type(legacy.llm)


def test_workspace_path_equivalent():
    legacy = CognitiveLoop()
    composed = build_loop_from_composition(Context())
    assert composed.workspace.workspace == legacy.workspace.workspace


def test_event_sink_wired():
    composed = build_loop_from_composition(Context())
    # bound method 每次访问会新建对象，用 __self__ 判断绑定目标
    assert composed._registry.event_sink is not None
    assert composed._registry.event_sink.__self__ is composed
    assert composed._registry.event_sink.__func__ is CognitiveLoop._on_registry_event


def test_cognitive_loop_service_registered_in_ctx():
    ctx = Context()
    loop = build_loop_from_composition(ctx)
    assert ctx.get("cognitive-loop").loop is loop


# ----------------------------------------------------------------------
# 组合语义
# ----------------------------------------------------------------------
def test_missing_cognitive_loop_raises(tmp_path, monkeypatch):
    from praxic.core import assembly

    broken = tmp_path / "broken.yml"
    broken.write_text(
        "- id: only-tool\n  name: praxic.cordis.services.tools:ToolService\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(assembly, "preset_path", lambda name="default": broken)
    with pytest.raises(CompositionError):
        build_loop_from_composition(Context())


def test_duplicate_tool_row_raises():
    """撞名策略（P2 收紧）：组合内重复 id 直接抛 CompositionError，不再首个胜出。"""
    ctx = Context()
    with pytest.raises(CompositionError):
        load_composition(
            """
- id: llm
  name: praxic.cordis.services.llm:LLMService
- id: workspace
  name: praxic.cordis.services.host:WorkspaceService
- id: permission-policy
  name: praxic.cordis.services.host:PermissionPolicyService
  inject: [workspace]
- id: tool-registry
  name: praxic.cordis.services.tools:ToolRegistryService
  inject: [permission-policy]
- id: python-exec
  name: praxic.cordis.services.tools:ToolService
  inject: [tool-registry, workspace]
- id: python-exec
  name: praxic.cordis.services.tools:ToolService
  inject: [tool-registry, workspace]
""",
            ctx,
        )


def test_failed_row_skipped_composition_continues():
    """装配失败的行跳过，组合继续。"""
    ctx = Context()
    res = load_composition(
        """
- id: broken
  name: no.such.module:Thing
- id: llm
  name: praxic.cordis.services.llm:LLMService
""",
        ctx,
    )
    assert "llm" in res.activated
    assert "broken" not in res.activated
    assert any(rid == "broken" for rid, _ in res.failed)


def test_unknown_preset_raises():
    from praxic.core.assembly import preset_path

    with pytest.raises(ValueError):
        preset_path("nope")


def test_default_preset_exists():
    from praxic.core.assembly import preset_path

    assert preset_path().exists()
