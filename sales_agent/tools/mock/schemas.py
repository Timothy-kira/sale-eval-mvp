"""6 个 Mock 工具的 Pydantic Input Schema"""
from pydantic import BaseModel, Field


class GetLeadContextInput(BaseModel):
    lead_id: str = Field(..., description="线索ID，如 L001")


class SearchKnowledgeBaseInput(BaseModel):
    query: str = Field(..., description="查询关键词，如 '产品功能'、'部署方式'")


class CheckCalendarInput(BaseModel):
    timezone: str = Field(..., description="时区，如 Asia/Shanghai、Asia/Singapore")
    duration_minutes: int = Field(30, description="会议时长（分钟）")


class BookDemoInput(BaseModel):
    lead_id: str = Field(..., description="线索ID")
    slot_id: str = Field(..., description="时段ID，如 SH_20260604_1000")
    attendee_email: str = Field(..., description="参会者邮箱")
    summary: str = Field(..., description="会议主题摘要")


class WriteCrmNoteInput(BaseModel):
    lead_id: str = Field(..., description="线索ID")
    summary: str = Field(..., description="跟进摘要，必须包含痛点、阶段、下一步")
    qualification_level: str = Field(..., description="评级: high|medium|low|unknown")
    next_action: str = Field(..., description="下一步动作")


class HandoffToHumanInput(BaseModel):
    lead_id: str = Field(..., description="线索ID")
    reason: str = Field(..., description="转人工原因")
    urgency: str = Field("medium", description="紧急程度: high|medium|low")
