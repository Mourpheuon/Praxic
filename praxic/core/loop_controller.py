"""
Praxic Agent —— 认知循环运行时控制器
支持三种控制操作：
  interrupt  打断：暂停当前阶段，等待用户指令后继续
  stop       终止：立即停止，返回已完成部分的结果
  steer      引导：注入方向提示，下一个小循环/阶段边界开始时生效
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import structlog

log = structlog.get_logger(__name__)


class ControlAction(str, Enum):
    INTERRUPT = "interrupt"   # 暂停，等待用户继续或取消
    STOP      = "stop"        # 终止整个循环
    STEER     = "steer"       # 注入引导方向，不停止循环
    RESUME    = "resume"      # 从打断状态恢复


class SteeringType(str, Enum):
    """S线：五类操控标签"""
    INFO_SUPPLEMENT    = "info_supplement"     # 信息补充：用户补充智能体无从知晓的领域事实
    INTENT_CORRECTION  = "intent_correction"   # 需求修正：用户厘清了自己真正想要什么
    JUDGMENT_CHALLENGE = "judgment_challenge"  # 判断挑战：用户认为某个分析判断有误
    CONFIRMATION       = "confirmation"        # 确认：用户认可方向，加速推进
    PRACTICE_REPORT    = "practice_report"     # 实践反馈：用户报告现实世界实践结果（V3 认识论地位）


@dataclass
class SteerMessage:
    """用户注入的引导信息"""
    content: str                                                        # 引导内容
    target_phase: str = ""                                              # 目标阶段（空=广播给所有阶段）
    priority: str = "normal"                                            # normal | high
    steering_type: SteeringType = SteeringType.INFO_SUPPLEMENT          # S线：操控类型
    persistent: bool = False                                            # True = 跨迭代生效，直到用户显式撤回
    iteration_added: int = 0                                            # 记录在第几轮迭代加入
    applied_phases: set[str] = field(default_factory=set)               # 广播消息已在这些阶段/小循环上下文应用


class LoopController:
    """
    每个 session 拥有一个独立的 LoopController 实例。
    cognitive_loop 在每个阶段边界检查这个控制器的状态。
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._stop_event   = asyncio.Event()   # 设置 = 终止
        self._pause_event  = asyncio.Event()   # 设置 = 暂停中
        self._resume_event = asyncio.Event()   # 设置 = 可以继续
        self._steer_queue: asyncio.Queue[SteerMessage] = asyncio.Queue()
        self.current_phase: str = ""
        self.interrupted_at: str = ""
        # 智能体主动提问（澄清）——阻塞等待用户回答
        self._clarify_event = asyncio.Event()
        self._clarify_questions: list[str] = []
        self._clarify_answer: str = ""
        self.awaiting_clarification: bool = False

    # ── 外部调用（API 层）────────────────────────────────────────

    def stop(self) -> None:
        """终止循环（不可恢复）"""
        log.info("controller.stop", session=self.session_id)
        self._stop_event.set()
        self._resume_event.set()   # 解除可能存在的暂停，避免死锁
        self._clarify_event.set()  # 解除可能存在的澄清等待，避免死锁

    def interrupt(self) -> None:
        """打断循环（下一个阶段边界暂停，等待 resume）"""
        log.info("controller.interrupt", session=self.session_id, phase=self.current_phase)
        self._pause_event.set()
        self._resume_event.clear()

    def resume(self, steer: Optional[str] = None) -> None:
        """从打断状态恢复，可选附带引导方向"""
        log.info("controller.resume", session=self.session_id, has_steer=bool(steer))
        if steer:
            self._steer_queue.put_nowait(
                SteerMessage(content=steer, priority="high")
            )
        self._pause_event.clear()
        self._resume_event.set()

    def steer(self, content: str, target_phase: str = "") -> None:
        """注入引导方向（不停止，在当前运行的下一个检查点生效）"""
        log.info("controller.steer", session=self.session_id, target=target_phase or "all")
        self._steer_queue.put_nowait(
            SteerMessage(content=content, target_phase=target_phase)
        )

    # ── 智能体主动提问（澄清）────────────────────────────────────
    def begin_clarification(self, questions) -> None:
        """智能体发起澄清：进入等待用户回答状态。"""
        self._clarify_questions = list(questions or [])
        self._clarify_answer = ""
        self._clarify_event.clear()
        self.awaiting_clarification = True
        log.info("controller.clarify_begin", session=self.session_id, n=len(self._clarify_questions))

    def submit_clarification(self, answer: str) -> None:
        """用户回答澄清问题（由 /control answer 调用）。"""
        self._clarify_answer = answer or ""
        self.awaiting_clarification = False
        self._clarify_event.set()
        log.info("controller.clarify_answer", session=self.session_id, has=bool(answer))

    async def await_clarification(self, timeout: Optional[float] = None) -> str:
        """阻塞等待用户回答；返回答案字符串（超时/终止返回 ""）。"""
        try:
            if timeout and timeout > 0:
                await asyncio.wait_for(self._clarify_event.wait(), timeout=timeout)
            else:
                await self._clarify_event.wait()
        except asyncio.TimeoutError:
            self.awaiting_clarification = False
            log.info("controller.clarify_timeout", session=self.session_id)
            return ""
        self.awaiting_clarification = False
        if self.should_stop:
            return ""
        return self._clarify_answer

    # ── 内部调用（cognitive_loop 层）────────────────────────────

    @property
    def should_stop(self) -> bool:
        return self._stop_event.is_set()

    @property
    def is_interrupted(self) -> bool:
        return self._pause_event.is_set()

    async def check_phase_boundary(self, phase_name: str) -> Optional[str]:
        """
        在阶段开始前调用。
        - 如果收到 stop 信号，返回 "stop"
        - 如果收到 interrupt，等待用户 resume，返回 "resumed" 或 "stop"
        - 正常则返回 None，并附带收集到的 steer 提示
        """
        self.current_phase = phase_name

        if self.should_stop:
            return "stop"

        if self.is_interrupted:
            self.interrupted_at = phase_name
            log.info("controller.paused_at", phase=phase_name)
            # 等待用户 resume 或 stop
            await self._resume_event.wait()
            self._resume_event.clear()
            if self.should_stop:
                return "stop"
            return "resumed"

        return None

    def collect_steers(self, phase_name: str = "") -> str:
        """
        取出适用于当前阶段的引导消息，合并为字符串。
        target_phase 为空的广播消息在本次控制器生命周期内持续生效；
        指定阶段的消息在命中后消费。
        """
        hints: list[str] = []
        temp: list[SteerMessage] = []

        while not self._steer_queue.empty():
            msg = self._steer_queue.get_nowait()
            if not msg.target_phase:
                # 广播 steering 要跨阶段保留，但同一阶段可能有多个小循环。
                # 每个消息只在同一阶段第一次被取出时应用，避免每次工具调用都重复注入旧内容。
                if phase_name not in msg.applied_phases:
                    hints.append(msg.content)
                    msg.applied_phases.add(phase_name)
                temp.append(msg)
            elif msg.target_phase == phase_name:
                hints.append(msg.content)
            else:
                temp.append(msg)   # 不属于本阶段，放回

        for msg in temp:
            self._steer_queue.put_nowait(msg)

        if hints:
            log.info("controller.steer_applied", phase=phase_name, n=len(hints))
            return "\n[用户引导] " + " / ".join(hints)
        return ""

    def get_pending_steers(self) -> list[SteerMessage]:
        """
        S线：取出所有待处理的 steering（不消费，由反思阶段统一消费）。
        与 collect_steers 不同：此方法返回完整的 SteerMessage 对象列表，
        供反思阶段做类型感知处理。
        """
        result: list[SteerMessage] = []
        while not self._steer_queue.empty():
            result.append(self._steer_queue.get_nowait())
        return result

    def requeue_persistent_steers(
        self, steers: list[SteerMessage], current_iteration: int
    ) -> None:
        """
        S线：将 persistent=True 的 steering 重新入队，供下一轮使用。
        """
        for s in steers:
            if s.persistent:
                self._steer_queue.put_nowait(s)
                log.info("controller.steer_requeued",
                         type=s.steering_type, iter=current_iteration)


# ── 全局 session 注册表 ────────────────────────────────────────────

_registry: dict[str, LoopController] = {}
_conv_to_session: dict[str, str] = {}   # conversation_id → session_id


def get_controller(session_id: str) -> LoopController:
    if session_id not in _registry:
        _registry[session_id] = LoopController(session_id)
    return _registry[session_id]


def release_controller(session_id: str) -> None:
    _registry.pop(session_id, None)


def list_active_sessions() -> list[str]:
    return list(_registry.keys())


def register_conv_controller(conv_id: str, session_id: str) -> None:
    """建立 conversation_id → session_id 映射，供 steering API 路由。"""
    _conv_to_session[conv_id] = session_id
    log.info("controller.conv_registered", conv_id=conv_id, session_id=session_id)


def get_controller_by_conv(conv_id: str) -> LoopController | None:
    """通过 conversation_id 查找活跃的控制器（用于 steering）。"""
    sid = _conv_to_session.get(conv_id)
    if sid and sid in _registry:
        return _registry[sid]
    return None


def release_conv_controller(conv_id: str) -> None:
    """释放 conversation 对应的控制器和映射。"""
    sid = _conv_to_session.pop(conv_id, None)
    if sid:
        release_controller(sid)
