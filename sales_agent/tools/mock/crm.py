"""write_crm_note —— 写入 CRM 记录（Memory 机制）"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from sales_agent.tools.interface import BaseTool, ToolResult


class WriteCrmNoteInput(BaseModel):
    """参数 Schema"""
    lead_id: str = Field(description="线索唯一标识")
    summary: str = Field(description="摘要，必须包含客户痛点、当前阶段、下一步动作、信心等级")
    qualification_level: str = Field(description="线索评级：high | medium | low | unknown")
    next_action: str = Field(description="下一步动作")


class WriteCrmNoteTool(BaseTool):
    """写入 CRM 记录

    对应笔试题工具：write_crm_note(lead_id, summary, qualification_level, next_action)
    复刻 Claude Code 的 memory 机制 —— 向持久化存储中写入上下文。
    """

    name: str = "write_crm_note"
    description: str = "将线索信息写入 CRM 系统。summary 必须包含客户痛点、当前阶段、下一步动作、信心等级。qualification_level 必须是 high/medium/low/unknown 之一。"
    input_schema: type[BaseModel] = WriteCrmNoteInput

    def __init__(self) -> None:
        self._db_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "mock_db", "crm_records.json"
        )

    @property
    def is_read_only(self) -> bool:
        return False

    def validate(self, args: dict[str, Any]) -> BaseModel:
        """自定义校验（复刻 Claude Code 的 validateInput）"""
        validated = super().validate(args)

        # 校验 qualification_level 枚举
        if validated.qualification_level not in ("high", "medium", "low", "unknown"):
            raise ValueError(
                f"qualification_level 必须是 high/medium/low/unknown 之一，"
                f"收到: {validated.qualification_level}"
            )

        # 校验 summary 非空
        if not validated.summary or not validated.summary.strip():
            raise ValueError("summary 不能为空")

        # 校验不得在未预约成功时写入"已预约"
        if "已预约" in validated.summary and "book_demo 成功" not in validated.summary:
            raise ValueError(
                "不得把'已预约'写入 CRM，除非 book_demo 工具调用成功"
            )

        return validated

    def call(self, **kwargs: Any) -> ToolResult:
        try:
            validated = self.validate(kwargs)

            with open(self._db_path, "r", encoding="utf-8") as f:
                records = json.load(f)

            note = {
                "note_id": f"CRM{len(records.get(validated.lead_id, [])) + 1:03d}",
                "lead_id": validated.lead_id,
                "summary": validated.summary,
                "qualification_level": validated.qualification_level,
                "next_action": validated.next_action,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }

            records.setdefault(validated.lead_id, []).append(note)

            with open(self._db_path, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)

            return ToolResult(success=True, data={"note_id": note["note_id"]})

        except Exception as e:
            return ToolResult(success=False, error=str(e))
