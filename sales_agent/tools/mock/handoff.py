"""handoff_to_human —— 转人工处理"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from sales_agent.tools.interface import BaseTool, ToolResult


class HandoffToHumanInput(BaseModel):
    """参数 Schema"""
    lead_id: str = Field(description="线索ID")
    reason: str = Field(description="转人工原因，如 '合同条款咨询'、'定制报价'、'安全审计'、'客户明确要求人工'")
    urgency: str = Field(default="medium", description="紧急程度: high|medium|low")


class HandoffToHumanTool(BaseTool):
    """转人工处理

    对应笔试题工具：handoff_to_human(lead_id, reason, urgency)
    当客户询问合同、法务、安全审计、定制报价，或情绪激烈、明确要求人工时调用。
    复刻 Claude Code 的权限/升级机制 —— 将复杂或敏感操作升级给人类处理。
    """

    name: str = "handoff_to_human"
    description: str = (
        "将线索转接给人工销售处理。必须在以下场景调用："
        "1）客户询问合同条款、法务问题；2）客户要求定制报价；"
        "3）客户提出安全审计需求；4）客户情绪激烈或明确要求人工；"
        "5）超出AI能力范围的高价值复杂需求。"
    )
    input_schema: type[BaseModel] = HandoffToHumanInput

    def __init__(self) -> None:
        self._db_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "mock_db", "handoffs.json"
        )

    @property
    def is_read_only(self) -> bool:
        return False

    def call(self, **kwargs: Any) -> ToolResult:
        try:
            validated = self.validate(kwargs)
            lead_id = validated.lead_id
            reason = validated.reason
            urgency = validated.urgency

            # 校验 urgency 枚举
            if urgency not in ("high", "medium", "low"):
                return ToolResult(
                    success=False,
                    error=f"urgency 必须是 high/medium/low 之一，收到: {urgency}",
                )

            # 读取或创建 handoffs 记录
            if os.path.exists(self._db_path):
                with open(self._db_path, "r", encoding="utf-8") as f:
                    db = json.load(f)
            else:
                db = {"handoffs": []}

            handoff = {
                "handoff_id": f"HF{len(db['handoffs']) + 1:03d}",
                "lead_id": lead_id,
                "reason": reason,
                "urgency": urgency,
                "status": "pending",
                "assigned_to": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "resolved_at": None,
            }
            db["handoffs"].append(handoff)

            with open(self._db_path, "w", encoding="utf-8") as f:
                json.dump(db, f, ensure_ascii=False, indent=2)

            return ToolResult(
                success=True,
                data={
                    "handoff_id": handoff["handoff_id"],
                    "status": "pending",
                    "message": f"已成功转人工（紧急程度: {urgency}）。销售同事将在 {'2小时内' if urgency == 'high' else '1个工作日内' if urgency == 'medium' else '3个工作日内'}联系客户。",
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=str(e))
