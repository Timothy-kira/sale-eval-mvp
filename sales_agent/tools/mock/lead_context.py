"""get_lead_context —— 获取线索已有信息（Memory 机制）"""
from __future__ import annotations

import json
import os
from typing import Any

from pydantic import BaseModel, Field

from sales_agent.tools.interface import BaseTool, ToolResult


class GetLeadContextInput(BaseModel):
    """参数 Schema（复刻 Claude Code 的 inputSchema）"""
    lead_id: str = Field(description="线索唯一标识，如 L001")


class GetLeadContextTool(BaseTool):
    """获取线索已有信息

    对应笔试题工具：get_lead_context(lead_id)
    复刻 Claude Code 的 memory 机制 —— 从持久化存储中读取上下文。
    """

    name: str = "get_lead_context"
    description: str = "获取指定线索的已有信息，包括公司规模、行业、已知痛点、预算范围、决策人、当前阶段、已收集信息等。"
    input_schema: type[BaseModel] = GetLeadContextInput

    def __init__(self) -> None:
        self._db_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "mock_db", "leads.json"
        )

    @property
    def is_read_only(self) -> bool:
        return True

    def call(self, **kwargs: Any) -> ToolResult:
        try:
            validated = self.validate(kwargs)
            lead_id = validated.lead_id

            with open(self._db_path, "r", encoding="utf-8") as f:
                leads = json.load(f)

            lead = leads.get(lead_id)
            if not lead:
                return ToolResult(
                    success=False,
                    error=f"未找到线索 {lead_id}",
                )

            return ToolResult(success=True, data=lead)

        except Exception as e:
            return ToolResult(success=False, error=str(e))
