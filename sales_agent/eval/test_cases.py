"""评测用例集 —— 从 JSON 配置加载，支持交互式多轮对话 + Trajectory 验证

设计原则：
- 测试消息不再硬编码在 Python 中，而是从 JSON 文件加载
- 交互式用例通过 messages 列表定义用户消息序列
- 复杂的 trajectory_checker / custom_checker 通过字符串名在注册表中查找
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


# ═══════════════════════════════════════════════════════════
# 用户模拟器协议
# ═══════════════════════════════════════════════════════════

class UserSimulator:
    """交互式用户模拟器

    根据 Agent 的每一轮回复，动态生成下一轮用户输入。
    返回 None 表示用户不再回复，对话结束。
    """

    def respond(
        self,
        agent_message: str,
        tool_calls: list[dict],
        trajectory: "Trajectory",
        turn: int,
    ) -> str | None:
        raise NotImplementedError


class SequentialUserSimulator(UserSimulator):
    """顺序消息模拟器 —— 按预定列表依次发送消息

    这是最常见的交互式模式：用户有一系列预定消息，
    无论 Agent 怎么回复，都按顺序发完。
    """

    def __init__(self, messages: list[str]) -> None:
        self.messages = messages

    def respond(self, agent_message: str, tool_calls: list[dict], trajectory: "Trajectory", turn: int) -> str | None:
        # turn=0 是初始化，对应 messages[0]；turn=1 对应 messages[1]，以此类推
        idx = turn
        if 0 <= idx < len(self.messages):
            return self.messages[idx]
        return None


# ═══════════════════════════════════════════════════════════
# Trajectory 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class Trajectory:
    """完整的交互轨迹"""

    case_id: str
    turns: list[dict] = field(default_factory=list)

    def add_turn(
        self,
        turn: int,
        user_message: str,
        agent_message: str,
        tool_calls: list[dict],
        state: dict,
    ) -> None:
        self.turns.append({
            "turn": turn,
            "user_message": user_message,
            "agent_message": agent_message,
            "tool_calls": tool_calls,
            "state": state,
        })

    def all_tool_calls(self) -> list[dict]:
        calls = []
        for t in self.turns:
            calls.extend(t.get("tool_calls", []))
        return calls

    def tool_names_sequence(self) -> list[str]:
        return [tc.get("tool_name") for tc in self.all_tool_calls()]

    def has_tool(self, tool_name: str) -> bool:
        return tool_name in self.tool_names_sequence()

    def tool_call_count(self, tool_name: str) -> int:
        return self.tool_names_sequence().count(tool_name)

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "turns": self.turns,
            "all_tool_names": self.tool_names_sequence(),
        }


# ═══════════════════════════════════════════════════════════
# 评测用例
# ═══════════════════════════════════════════════════════════

@dataclass(frozen=True)
class EvalCase:
    """单个评测用例"""

    case_id: str
    name: str
    category: str
    conversation: list[dict] = field(default_factory=list)
    user_simulator: UserSimulator | None = None
    expected_tools: list[str] | None = None
    forbidden_tools: list[str] | None = None
    expected_in_message: list[str] | None = None
    forbidden_in_message: list[str] | None = None
    expected_trajectory: list[str] | None = None
    trajectory_checker: Callable[["Trajectory"], tuple[bool, str]] | None = None
    custom_checker: Callable[[dict], tuple[bool, str]] | None = None
    max_turns: int = 5
    rubric: str | None = None


# ═══════════════════════════════════════════════════════════
# 自定义检查器注册表
# ═══════════════════════════════════════════════════════════

def _check_state_fields(result: dict) -> tuple[bool, str]:
    state = result.get("state", {})
    required = ["qualification_level", "missing_info", "next_action", "risk_flags"]
    missing = [f for f in required if f not in state]
    if missing:
        return False, f"state 缺少字段: {missing}"
    if state.get("qualification_level") not in ("high", "medium", "low", "unknown"):
        return False, f"qualification_level 值非法: {state.get('qualification_level')}"
    return True, "state 字段完整"


def _check_no_fake_booking_in_crm(result: dict) -> tuple[bool, str]:
    tool_calls = result.get("tool_calls", [])
    fake_booking_keywords = ["已预约", "已安排", "Demo已定", "预约成功", "已预订", "已排定"]
    for tc in tool_calls:
        if tc.get("tool_name") == "write_crm_note":
            summary = tc.get("arguments", {}).get("summary", "")
            has_fake = any(kw in summary for kw in fake_booking_keywords)
            has_booking_proof = "book_demo" in summary or "booking_id" in summary
            if has_fake and not has_booking_proof:
                return False, f"CRM 记录中包含虚假预约信息（{summary}）但未提及 book_demo 成功"
    return True, "CRM 记录合规"


def _check_demo_booking_trajectory(trajectory: Trajectory) -> tuple[bool, str]:
    names = trajectory.tool_names_sequence()
    if "check_calendar" not in names:
        return False, "未调用 check_calendar 查询可预约时间"
    if "book_demo" not in names:
        return False, "未调用 book_demo 完成预约"
    cal_idx = names.index("check_calendar")
    book_idx = names.index("book_demo")
    if book_idx < cal_idx:
        return False, "book_demo 在 check_calendar 之前调用，顺序错误"
    return True, "Demo 预约轨迹正确"


def _check_crm_trajectory(trajectory: Trajectory) -> tuple[bool, str]:
    if "write_crm_note" not in trajectory.tool_names_sequence():
        return False, "未调用 write_crm_note"
    return True, "CRM 更新轨迹正确"


def _check_no_budget_trajectory(trajectory: Trajectory) -> tuple[bool, str]:
    if "write_crm_note" in trajectory.tool_names_sequence():
        return False, "预算未定时不应写 CRM"
    return True, "无预算场景处理正确"


# 字符串名 -> 检查器函数 的映射（用于从 JSON 反序列化）
CUSTOM_CHECKERS: dict[str, Callable] = {
    "state_fields": _check_state_fields,
    "no_fake_booking": _check_no_fake_booking_in_crm,
}

TRAJECTORY_CHECKERS: dict[str, Callable[[Trajectory], tuple[bool, str]]] = {
    "demo_booking": _check_demo_booking_trajectory,
    "crm_update": _check_crm_trajectory,
    "no_budget": _check_no_budget_trajectory,
}


# ═══════════════════════════════════════════════════════════
# 从 JSON 加载用例
# ═══════════════════════════════════════════════════════════

_CASES_DIR = Path(__file__).parent / "cases"


def _load_json_cases(path: Path) -> list[EvalCase]:
    """从单个 JSON 文件加载用例"""
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    cases = []
    for item in data.get("cases", []):
        mode = item.get("mode", "static")

        # 构建 user_simulator 或 conversation
        conversation = []
        user_simulator = None
        if mode == "static":
            conversation = item.get("conversation", [])
        elif mode == "interactive":
            messages = item.get("messages", [])
            if messages:
                user_simulator = SequentialUserSimulator(messages)

        # 解析检查器引用
        custom_checker = None
        traj_checker = None
        cc_name = item.get("custom_checker")
        tc_name = item.get("trajectory_checker")
        if cc_name and isinstance(cc_name, str):
            custom_checker = CUSTOM_CHECKERS.get(cc_name)
        if tc_name and isinstance(tc_name, str):
            traj_checker = TRAJECTORY_CHECKERS.get(tc_name)

        cases.append(
            EvalCase(
                case_id=item["case_id"],
                name=item["name"],
                category=item["category"],
                conversation=conversation,
                user_simulator=user_simulator,
                expected_tools=item.get("expected_tools"),
                forbidden_tools=item.get("forbidden_tools"),
                expected_in_message=item.get("expected_in_message"),
                forbidden_in_message=item.get("forbidden_in_message"),
                expected_trajectory=item.get("expected_trajectory"),
                trajectory_checker=traj_checker,
                custom_checker=custom_checker,
                max_turns=item.get("max_turns", 5),
                rubric=item.get("rubric"),
            )
        )
    return cases


def load_all_cases() -> list[EvalCase]:
    """加载所有 JSON 用例"""
    cases: list[EvalCase] = []
    for filename in ("static_cases.json", "interactive_cases.json"):
        path = _CASES_DIR / filename
        cases.extend(_load_json_cases(path))
    return cases


# ═══════════════════════════════════════════════════════════
# 导出
# ═══════════════════════════════════════════════════════════

ALL_CASES: list[EvalCase] = load_all_cases()
