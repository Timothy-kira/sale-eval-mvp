"""状态管理 —— 复刻 Claude Code 的 ToolUseContext + Loop State"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AgentState(BaseModel):
    """Agent 回合级状态（复刻 Claude Code 的 Loop State）

    每次调用 agent_loop 时创建，随对话推进更新。
    """

    model_config = ConfigDict(extra="allow")

    lead_id: str = Field(description="当前线索 ID")
    messages: list[dict] = Field(
        default_factory=list, description="对话历史（含 system/user/assistant/tool）"
    )
    qualification_level: str = Field(
        default="unknown", description="线索评级: high | medium | low | unknown"
    )
    missing_info: list[str] = Field(
        default_factory=list, description="还缺少哪些关键信息"
    )
    next_action: str = Field(
        default="", description="推荐的下一步动作"
    )
    risk_flags: list[str] = Field(
        default_factory=list, description="风险标记"
    )
    tools_called: list[dict] = Field(
        default_factory=list, description="本回合已调用的工具（Trajectory）"
    )
    turn_count: int = Field(
        default=0, description="当前回合计数"
    )
