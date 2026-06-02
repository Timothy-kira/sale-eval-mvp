"""系统 Prompt 生成 —— 复刻 Claude Code 的 prompts.ts"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sales_agent.tools.interface import BaseTool


def _format_lead_context(lead_context: dict | None) -> str:
    """格式化线索档案为可读文本（不包含 lead_id）"""
    if not lead_context:
        return "暂无档案信息。"
    lines = []
    mapping = {
        "company_name": "公司",
        "size": "规模",
        "industry": "行业",
        "known_pain_points": "已知痛点",
        "budget_range": "预算范围",
        "decision_maker": "决策人",
        "stage": "当前阶段",
        "collected_info": "已收集信息",
    }
    for key, label in mapping.items():
        value = lead_context.get(key)
        if value is not None:
            if isinstance(value, list):
                value = "、".join(str(v) for v in value) if value else "无"
            lines.append(f"- {label}: {value}")
    return "\n".join(lines) if lines else "暂无档案信息。"


def build_system_prompt(
    tools: list[BaseTool],
    qualification_level: str,
    missing_info: list[str],
    next_action: str,
    risk_flags: list[str],
    version: str = "v2",
    lead_context: dict | None = None,
) -> str:
    """构建系统 Prompt（复刻 Claude Code 的 getSystemPrompt）

    安全原则：
    - lead_id 绝不传入 prompt，防止 prompt injection 攻击
    - lead_context 中已过滤掉 lead_id 字段
    """
    from sales_agent.prompts.registry import load_prompt

    template = load_prompt(version)

    tool_descriptions = "\n".join(
        f"- {t.name}: {t.description}" for t in tools
    )

    return template.format(
        tool_descriptions=tool_descriptions,
        lead_context=_format_lead_context(lead_context),
        qualification_level=qualification_level,
        missing_info=missing_info or ["无"],
        next_action=next_action or "无",
        risk_flags=risk_flags or ["无"],
    )


def split_prompt_layers(full_prompt: str) -> list[dict]:
    """把完整的 system prompt 按 ## 标题拆分成层"""
    lines = full_prompt.split("\n")
    layers = []
    current_layer = {"name": "角色定义", "lines": []}

    for line in lines:
        if line.startswith("## "):
            if current_layer["lines"]:
                layers.append({
                    "name": current_layer["name"],
                    "content": "\n".join(current_layer["lines"]).strip(),
                })
            current_layer = {"name": line[3:].strip(), "lines": []}
        else:
            current_layer["lines"].append(line)

    if current_layer["lines"]:
        layers.append({
            "name": current_layer["name"],
            "content": "\n".join(current_layer["lines"]).strip(),
        })

    return layers
