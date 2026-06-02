"""check_calendar —— 检查销售日历可用时段"""
from __future__ import annotations

import json
import os
from typing import Any

from pydantic import BaseModel, Field

from sales_agent.tools.interface import BaseTool, ToolResult


class CheckCalendarInput(BaseModel):
    """参数 Schema"""
    timezone: str = Field(
        default="Asia/Shanghai",
        description="客户时区，如 Asia/Shanghai、Asia/Singapore、America/New_York"
    )
    duration_minutes: int = Field(
        default=30,
        description="会议时长（分钟），默认30"
    )
    preferred_date: str | None = Field(
        default=None,
        description="偏好日期，格式 YYYY-MM-DD，如 2026-06-04"
    )


class CheckCalendarTool(BaseTool):
    """检查销售日历可用时段

    对应笔试题工具：check_calendar(timezone, duration_minutes)
    复刻 Claude Code 的查询机制 —— 从日历数据库中检索可用时段。
    """

    name: str = "check_calendar"
    description: str = (
        "检查销售团队的可预约时段。预约 Demo 前必须先调用此工具确认可用时间。"
        "支持按客户时区筛选，返回可预约的销售代表和时段列表。"
    )
    input_schema: type[BaseModel] = CheckCalendarInput

    def __init__(self) -> None:
        self._db_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "mock_db", "calendar_db.json"
        )

    @property
    def is_read_only(self) -> bool:
        return True

    def call(self, **kwargs: Any) -> ToolResult:
        try:
            validated = self.validate(kwargs)
            timezone = validated.timezone
            duration_minutes = validated.duration_minutes
            preferred_date = validated.preferred_date

            with open(self._db_path, "r", encoding="utf-8") as f:
                db = json.load(f)

            sales_reps = {sr["id"]: sr for sr in db.get("sales_reps", [])}
            schedules = db.get("schedules", {})

            # 收集可用时段
            available_slots = []
            for date, day_schedule in schedules.items():
                if preferred_date and date != preferred_date:
                    continue
                for sr_id, slots in day_schedule.items():
                    sr = sales_reps.get(sr_id)
                    if not sr:
                        continue
                    # 时区匹配：允许相同时区或通用时区
                    if timezone != sr.get("timezone", "") and timezone != "Any":
                        # 允许跨时区预约，但优先相同时区
                        pass
                    for slot in slots:
                        if slot.get("status") == "available":
                            available_slots.append({
                                "slot_id": slot.get("slot_id"),
                                "sales_rep_id": sr_id,
                                "sales_rep_name": sr.get("name"),
                                "sales_rep_timezone": sr.get("timezone"),
                                "date": date,
                                "start_time": slot.get("start_time"),
                                "end_time": slot.get("end_time"),
                                "languages": sr.get("languages", []),
                            })

            # 限制返回数量，避免提示词过长
            available_slots = available_slots[:20]

            # 按日期和销售代表分组摘要
            summary = {}
            for slot in available_slots:
                date = slot["date"]
                if date not in summary:
                    summary[date] = {}
                sr_name = slot["sales_rep_name"]
                if sr_name not in summary[date]:
                    summary[date][sr_name] = []
                summary[date][sr_name].append(slot["start_time"])

            return ToolResult(
                success=True,
                data={
                    "timezone": timezone,
                    "duration_minutes": duration_minutes,
                    "available_slots": available_slots,
                    "summary": summary,
                    "total_available": len(available_slots),
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=str(e))
