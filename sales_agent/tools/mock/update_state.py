"""更新 Agent 状态工具"""
from __future__ import annotations

from pydantic import BaseModel, Field

from sales_agent.tools.interface import BaseTool, ToolResult


class UpdateStateInput(BaseModel):
    """更新 Agent 状态参数"""

    qualification_level: str = Field(
        default="unknown",
        description="线索评级: high | medium | low | unknown",
    )
    missing_info: list[str] = Field(
        default_factory=list,
        description="还缺少哪些关键信息",
    )
    next_action: str = Field(
        default="",
        description="推荐的下一步动作",
    )
    risk_flags: list[str] = Field(
        default_factory=list,
        description="风险标记",
    )


class UpdateStateTool(BaseTool):
    """更新 Agent 内部状态

    这是一个元工具（meta-tool），用于让模型在对话过程中更新线索评级、
    缺失信息、下一步动作和风险标记。它不产生外部副作用。
    """

    name = "update_state"
    description = "更新当前对话的状态信息，包括线索评级、缺失信息、下一步动作和风险标记。在收集到关键信息或发生状态变化时调用。"
    input_schema = UpdateStateInput

    def call(
        self,
        qualification_level: str = "unknown",
        missing_info: list[str] | None = None,
        next_action: str = "",
        risk_flags: list[str] | None = None,
    ) -> ToolResult:
        return ToolResult(
            success=True,
            data={
                "qualification_level": qualification_level,
                "missing_info": missing_info or [],
                "next_action": next_action,
                "risk_flags": risk_flags or [],
            },
        )

    @property
    def is_read_only(self) -> bool:
        return True
