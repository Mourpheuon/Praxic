"""P2 验收：会话生命周期（session realm / 任务取消 / 多项目隔离 / 授权清理 / 泄漏断言）。

不依赖 FastAPI 服务器，直接测 SessionScope 与 agent 层的生命周期辅助，
覆盖任务书 P2 的五项测试要求。
"""

import asyncio

import pytest

from praxic.api.routes import agent as agent_mod
from praxic.cordis import Context
from praxic.cordis.services.session import SessionScope
from praxic.tools.base import ActionKind


def _fresh_scope() -> SessionScope:
    """独立 SessionScope，避免污染 agent 全局。"""
    return SessionScope()


def _loop_of(scope: SessionScope, label: str, project_id: str = ""):
    return scope.get_or_create(label, project_id=project_id).ctx.get("cognitive-loop").loop


# ----------------------------------------------------------------------
# 断线重连：会话 realm 复用，事件回放行为不变
# ----------------------------------------------------------------------
def test_reconnect_reuses_same_realm():
    s = _fresh_scope()
    r1 = s.get_or_create("conv-a")
    r2 = s.get_or_create("conv-a")
    assert r1 is r2
    assert s.live_count() == 1
    # 同一 realm 内 loop 实例唯一
    assert r1.ctx.get("cognitive-loop").loop is r2.ctx.get("cognitive-loop").loop


def test_realm_recreated_after_dispose():
    s = _fresh_scope()
    r1 = s.get_or_create("conv-a")
    asyncio.run(s.dispose("conv-a"))
    assert s.live_count() == 0
    r2 = s.get_or_create("conv-a")
    assert r2 is not r1
    assert not r2.fiber.disposed


def test_replay_buffer_contract_unchanged():
    """SSE 回放缓冲契约（独立于 realm）：订阅者回放历史 + EOF。"""
    conv = "conv-replay-p2"
    agent_mod._registry[conv] = {
        "replay": [{"type": "phase", "phase": "investigation", "summary": "s"}],
        "subscribers": [],
        "done": False,
        "created_at": 0.0,
    }
    try:
        q, already_done = agent_mod._create_subscriber(conv)
        assert already_done is False
        assert q.get_nowait()["phase"] == "investigation"
        agent_mod._finish_stream(conv)
        q2, done2 = agent_mod._create_subscriber(conv)
        assert done2 is True
    finally:
        agent_mod._registry.pop(conv, None)


# ----------------------------------------------------------------------
# stop：后台任务已取消（asyncio.all_tasks() 无残留协程）
# ----------------------------------------------------------------------
async def test_dispose_cancels_background_task():
    s = _fresh_scope()
    realm = s.get_or_create("conv-stop")
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def worker():
        started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    task = asyncio.create_task(worker())
    realm.fiber.track_task(task)
    await started.wait()
    await s.dispose("conv-stop")
    assert cancelled.is_set()
    assert task.cancelled()
    # 无残留协程（除当前测试任务外）
    leftover = [
        t for t in asyncio.all_tasks()
        if t is not asyncio.current_task() and not t.done()
    ]
    assert leftover == []


async def test_dispose_waits_task_before_cleanup():
    """dispose 顺序：先 cancel 任务并 await，再执行其余 disposable。"""
    s = _fresh_scope()
    realm = s.get_or_create("conv-order")
    order = []

    async def worker():
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            order.append("task-cancelled")
            raise

    task = asyncio.create_task(worker())
    realm.fiber.track_task(task)
    realm.fiber.register(lambda: order.append("disposable"))
    await asyncio.sleep(0)  # 让 worker 进入 await 点，取消才能触发 CancelledError 分支
    await s.dispose("conv-order")
    assert order == ["task-cancelled", "disposable"]


def test_agent_stop_path_disposes_realm():
    """/control stop 路径（controller.stop + adispose_session）后 realm 归零。"""
    scope = _fresh_scope()
    old = agent_mod._scope
    agent_mod._scope = scope
    try:
        _loop_of(scope, "conv-ctl-stop")
        assert scope.live_count() == 1
        asyncio.run(agent_mod.adispose_session("conv-ctl-stop"))
        assert scope.live_count() == 0
        assert scope.disposed_count == 1
        # 幂等
        asyncio.run(agent_mod.adispose_session("conv-ctl-stop"))
        assert scope.disposed_count == 1
    finally:
        agent_mod._scope = old


# ----------------------------------------------------------------------
# 多项目并行：两个 project realm 互不影响（各自 registry 独立实例）
# ----------------------------------------------------------------------
def test_multi_project_isolated_registries():
    s = _fresh_scope()
    loop_a = _loop_of(s, "", project_id="proj-a")
    loop_b = _loop_of(s, "", project_id="proj-b")
    assert loop_a is not loop_b
    reg_a = loop_a._registry
    reg_b = loop_b._registry
    assert reg_a is not reg_b
    # 工具集一致但实例独立
    assert set(reg_a.get_names()) == set(reg_b.get_names())
    assert reg_a.policy is not reg_b.policy
    # workspace 隔离（项目独立目录）
    assert loop_a.workspace.workspace != loop_b.workspace.workspace
    # 互不干扰：一个注册新工具不影响另一个
    reg_a.register(_StubTool())
    assert "p2-only-tool" not in reg_b.get_names()
    assert s.live_count() == 2


class _StubTool:
    """极简工具桩（仅注册名测试用）。"""

    name = "p2-only-tool"
    description = "stub"
    category = "misc"
    group = ""
    sandbox_safe = True
    requires_authorization = False

    async def run(self, **kwargs):
        from praxic.tools.base import ToolResult, ToolStatus

        return ToolResult(status=ToolStatus.SUCCESS, content="stub")


# ----------------------------------------------------------------------
# 授权超时：dispose 后无悬挂授权等待
# ----------------------------------------------------------------------
def test_no_hanging_authorization_after_dispose():
    s = _fresh_scope()
    realm = s.get_or_create("conv-auth")
    registry = realm.ctx.get("tool-registry").registry
    registry.policy.create_authorization_request(
        tool_name="shell_exec",
        action_kind=ActionKind.CHANGE,
        params={"cmd": "echo hi"},
        scope="shell",
        reason="p2 test",
    )
    assert len(registry.pending_authorizations) == 1
    asyncio.run(s.dispose("conv-auth"))
    assert registry.pending_authorizations == []


def test_dispose_without_auths_is_noop():
    s = _fresh_scope()
    realm = s.get_or_create("conv-clean")
    asyncio.run(s.dispose("conv-clean"))
    assert s.live_count() == 0


# ----------------------------------------------------------------------
# 泄漏断言：N 轮会话结束后 realm 计数归零
# ----------------------------------------------------------------------
def test_no_leak_after_n_rounds():
    s = _fresh_scope()
    for i in range(5):
        s.get_or_create(f"conv-{i}")
    assert s.live_count() == 5
    for i in range(5):
        asyncio.run(s.dispose(f"conv-{i}"))
    assert s.live_count() == 0
    assert s.live_labels() == []
    assert s.disposed_count == 5


def test_agent_scope_no_leak_after_rounds():
    """agent 全局 scope：多轮会话后 live 归零（等价于 N 轮后无实例累积）。"""
    scope = _fresh_scope()
    old = agent_mod._scope
    agent_mod._scope = scope
    try:
        for i in range(3):
            _loop_of(scope, f"conv-round-{i}")
        assert scope.live_count() == 3
        for i in range(3):
            asyncio.run(agent_mod.adispose_session(f"conv-round-{i}"))
        assert scope.live_count() == 0
        assert scope.disposed_count == 3
    finally:
        agent_mod._scope = old


# ----------------------------------------------------------------------
# host 单例
# ----------------------------------------------------------------------
def test_host_services_are_shared_singletons():
    s = _fresh_scope()
    r1 = s.get_or_create("conv-host-a")
    r2 = s.get_or_create("conv-host-b")
    # memory / skill-manager 为 host 级单例（root 注册，realm 可解析同一实例）
    assert r1.ctx.get("memory") is r2.ctx.get("memory")
    assert r1.ctx.get("skill-manager") is r2.ctx.get("skill-manager")
    # session 服务为 realm 级（各自实例）
    assert r1.ctx.get("cognitive-loop") is not r2.ctx.get("cognitive-loop")
