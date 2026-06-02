"""book_demo —— 预约产品演示（写入 Bookings）"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from sales_agent.tools.interface import BaseTool, ToolResult


class BookDemoInput(BaseModel):
    """参数 Schema"""
    lead_id: str = Field(description="线索ID")
    slot_id: str = Field(description="时段ID，如 SR001_20260604_1000")
    attendee_email: str = Field(description="参会者邮箱")
    summary: str = Field(description="会议主题摘要")


class BookDemoTool(BaseTool):
    """预约产品演示

    对应笔试题工具：book_demo(lead_id, slot_id, attendee_email, summary)
    复刻 Claude Code 的 write/memory 机制 —— 向持久化存储写入预约记录。
    调用前必须先确认客户邮箱、时区和参会目的，且已通过 check_calendar 确认时段可用。
    """

    name: str = "book_demo"
    description: str = (
        "预约产品演示会议。必须满足以下条件："
        "1）已获取客户邮箱；2）已通过 check_calendar 确认时段可用；"
        "3）已明确参会目的。调用成功后会返回 booking_id。"
    )
    input_schema: type[BaseModel] = BookDemoInput

    def __init__(self) -> None:
        self._calendar_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "mock_db", "calendar_db.json"
        )
        self._bookings_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "mock_db", "bookings.json"
        )
        self._leads_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "mock_db", "leads.json"
        )

    @property
    def is_read_only(self) -> bool:
        return False

    def _get_lead_info(self, lead_id: str) -> dict | None:
        with open(self._leads_path, "r", encoding="utf-8") as f:
            leads = json.load(f)
        return leads.get(lead_id)

    def _find_slot(self, slot_id: str) -> tuple[dict | None, str | None, str | None]:
        """查找时段，返回 (slot, date, sr_id)"""
        with open(self._calendar_path, "r", encoding="utf-8") as f:
            db = json.load(f)
        schedules = db.get("schedules", {})
        for date, day_schedule in schedules.items():
            for sr_id, slots in day_schedule.items():
                for slot in slots:
                    if slot.get("slot_id") == slot_id:
                        return slot, date, sr_id
        return None, None, None

    def call(self, **kwargs: Any) -> ToolResult:
        try:
            validated = self.validate(kwargs)
            lead_id = validated.lead_id
            slot_id = validated.slot_id
            attendee_email = validated.attendee_email
            summary = validated.summary

            # 1. 检查线索是否存在
            lead = self._get_lead_info(lead_id)
            if not lead:
                return ToolResult(
                    success=False,
                    error=f"未找到线索 {lead_id}",
                )

            # 2. 检查时段是否可用
            slot, date, sr_id = self._find_slot(slot_id)
            if not slot:
                return ToolResult(
                    success=False,
                    error=f"未找到时段 {slot_id}，请重新调用 check_calendar 查询可用时段。",
                )
            if slot.get("status") != "available":
                return ToolResult(
                    success=False,
                    error=f"时段 {slot_id} 已被占用（状态: {slot.get('status')}），请选择其他时段。",
                )

            # 3. 读取现有预约
            if not os.path.exists(self._bookings_path):
                bookings_db = {"bookings": []}
            else:
                with open(self._bookings_path, "r", encoding="utf-8") as f:
                    bookings_db = json.load(f)
            bookings = bookings_db.get("bookings", [])

            # 4. 创建新预约
            booking_id = f"BK{len(bookings) + 1:03d}"
            new_booking = {
                "booking_id": booking_id,
                "lead_id": lead_id,
                "lead_email": attendee_email,
                "lead_company": lead.get("company_name", ""),
                "topic": summary,
                "slot_id": slot_id,
                "date": date,
                "start_time": slot.get("start_time"),
                "end_time": slot.get("end_time"),
                "sales_rep_id": sr_id,
                "booked_at": datetime.now(timezone.utc).isoformat(),
            }
            bookings.append(new_booking)

            # 5. 更新 bookings.json
            bookings_db["bookings"] = bookings
            with open(self._bookings_path, "w", encoding="utf-8") as f:
                json.dump(bookings_db, f, ensure_ascii=False, indent=2)

            # 6. 更新 calendar_db.json 中的时段状态
            with open(self._calendar_path, "r", encoding="utf-8") as f:
                db = json.load(f)
            schedules = db.get("schedules", {})
            for d, day_schedule in schedules.items():
                for s_id, slots in day_schedule.items():
                    for sl in slots:
                        if sl.get("slot_id") == slot_id:
                            sl["status"] = "booked"
                            sl["booking"] = {
                                "booking_id": booking_id,
                                "lead_id": lead_id,
                            }
                            break
            with open(self._calendar_path, "w", encoding="utf-8") as f:
                json.dump(db, f, ensure_ascii=False, indent=2)

            return ToolResult(
                success=True,
                data={
                    "booking_id": booking_id,
                    "slot_id": slot_id,
                    "date": date,
                    "start_time": slot.get("start_time"),
                    "end_time": slot.get("end_time"),
                    "lead_email": attendee_email,
                    "topic": summary,
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=str(e))
