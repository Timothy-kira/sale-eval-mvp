"""工具注册表 —— 复刻 Claude Code 的 getAllBaseTools()"""
from __future__ import annotations

from sales_agent.tools.interface import BaseTool
from sales_agent.tools.mock.lead_context import GetLeadContextTool
from sales_agent.tools.mock.crm import WriteCrmNoteTool
from sales_agent.tools.mock.knowledge_base import SearchKnowledgeBaseTool
from sales_agent.tools.mock.calendar import CheckCalendarTool
from sales_agent.tools.mock.demo_booking import BookDemoTool
from sales_agent.tools.mock.handoff import HandoffToHumanTool
from sales_agent.tools.mock.update_state import UpdateStateTool

# 静态数组注册（复刻 Claude Code 显式列表）
# 顺序影响 prompt cache 稳定性，固定排列
ALL_TOOLS: list[BaseTool] = [
    GetLeadContextTool(),
    SearchKnowledgeBaseTool(),
    CheckCalendarTool(),
    BookDemoTool(),
    WriteCrmNoteTool(),
    HandoffToHumanTool(),
    UpdateStateTool(),
]


def get_tools() -> list[BaseTool]:
    """获取所有可用工具"""
    return ALL_TOOLS


def find_tool(name: str) -> BaseTool | None:
    """通过名称查找工具（复刻 findToolByName）"""
    return next((t for t in ALL_TOOLS if t.name == name), None)
