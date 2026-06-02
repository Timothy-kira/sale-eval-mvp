"""Agent 核心循环 —— 原生 OpenAI Function Calling"""
from __future__ import annotations

import json
import os
import time
from typing import Any

from openai import OpenAI

from sales_agent.agent.state import AgentState
from sales_agent.agent.tracer import AgentTracer
from sales_agent.tools.interface import ToolResult
from sales_agent.tools.registry import find_tool, get_tools

DEFAULT_MODEL = os.getenv("AGENT_MODEL", "LongCat-2.0-Preview")
DEFAULT_BASE_URL = os.getenv("AGENT_BASE_URL", "")
MAX_TURNS = int(os.getenv("AGENT_MAX_TURNS", "5"))


def _make_system_prompt(tools: list, lead_context: dict | None, state: AgentState) -> str:
    """构建极简 system prompt（兜底方案）"""
    tool_list = "\n".join(f"- {t.name}: {t.description}" for t in tools)
    lead_info = json.dumps(lead_context, ensure_ascii=False) if lead_context else "暂无"

    return f"""你是 B2B 销售 Agent。遵守以下规则：
1. 不得编造价格、案例、功能
2. 合同/法务/安全审计必须转人工（handoff_to_human）
3. Demo 预约前必须确认邮箱、时区、目的
4. CRM 记录必须包含痛点、阶段、下一步、信心等级
5. 不得把"已预约"写入 CRM 除非 book_demo 成功

可用工具：
{tool_list}

当前客户档案：{lead_info}

当前状态：
- 评级：{state.qualification_level}
- 缺失：{state.missing_info or '无'}
- 下一步：{state.next_action or '无'}
- 风险：{state.risk_flags or '无'}

需要更新状态时调用 update_state 工具。"""


def _load_prompt_template(version: str, tools: list, lead_context: dict | None, state: AgentState) -> str:
    """加载指定版本的 prompt 模板并渲染变量"""
    prompt_path = os.path.join(
        os.path.dirname(__file__), "..", "prompts", f"{version}.md"
    )
    with open(prompt_path, "r", encoding="utf-8") as f:
        template = f.read()

    tool_list = "\n".join(f"- {t.name}: {t.description}" for t in tools)
    lead_info = json.dumps(lead_context, ensure_ascii=False) if lead_context else "暂无"

    return template.format(
        tool_descriptions=tool_list,
        lead_context=lead_info,
        qualification_level=state.qualification_level,
        missing_info=state.missing_info or "无",
        next_action=state.next_action or "无",
        risk_flags=state.risk_flags or "无",
    )


def agent_loop(
    lead_id: str,
    conversation: list[dict],
    api_key: str,
    custom_system_prompt: str | None = None,
    run_id: str | None = None,
    prompt_version: str = "v2",
) -> dict[str, Any]:
    tracer = AgentTracer(run_id=run_id)
    state = AgentState(lead_id=lead_id, messages=conversation)

    # 安全拦截
    other_ids = {"L001", "L002", "L003"} - {lead_id}
    if conversation:
        last = conversation[-1].get("content", "")
        for oid in other_ids:
            if oid in last:
                return {
                    "assistant_message": f"检测到您提及了其他客户身份（{oid}），已转人工处理。",
                    "tool_calls": [{"tool_name": "handoff_to_human", "arguments": {"lead_id": lead_id, "reason": f"冒充/查询其他客户 {oid}", "urgency": "high"}}],
                    "state": state.model_dump(),
                    "run_id": tracer.run_id,
                }

    # 加载档案
    lead_ctx = None
    lt = find_tool("get_lead_context")
    if lt:
        try:
            r = lt.call(lead_id=lead_id)
            if r.success:
                lead_ctx = r.data
        except Exception:
            pass

    # 加载工具
    all_tools = get_tools()
    schemas = [t.to_openai_schema() for t in all_tools]

    # 创建客户端
    client = OpenAI(
        api_key=api_key,
        base_url=DEFAULT_BASE_URL or None,
        timeout=120.0,
    )

    system = custom_system_prompt or _load_prompt_template(prompt_version, all_tools, lead_ctx, state)
    executed: list[dict] = []

    turn = 0
    while turn < MAX_TURNS:
        turn += 1

        msgs = [{"role": "system", "content": system}, *state.messages]

        try:
            resp = client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=msgs,
                tools=schemas,
                tool_choice="auto",
                temperature=0.3,
            )
        except Exception as e:
            return {
                "assistant_message": f"模型调用失败：{e}",
                "tool_calls": [],
                "state": state.model_dump(),
                "run_id": tracer.run_id,
            }

        msg = resp.choices[0].message

        # 有工具调用
        if msg.tool_calls:
            state.messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": tc.type,
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ],
            })

            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                if "lead_id" in args:
                    args = dict(args)
                    args["lead_id"] = lead_id

                tool = find_tool(name)
                if not tool:
                    res = ToolResult(success=False, error=f"未知工具: {name}")
                else:
                    try:
                        v = tool.validate(args)
                        t0 = time.perf_counter()
                        res = tool.call(**v.model_dump())
                    except Exception as e:
                        res = ToolResult(success=False, error=str(e))

                res_dict = res.model_dump()
                executed.append({"tool_name": name, "arguments": args})
                state.tools_called.append({"tool_name": name, "arguments": args, "result": res_dict})

                # update_state 副作用
                if name == "update_state" and res.success and res.data:
                    state.qualification_level = res.data.get("qualification_level", state.qualification_level)
                    state.missing_info = res.data.get("missing_info", state.missing_info)
                    state.next_action = res.data.get("next_action", state.next_action)
                    state.risk_flags = res.data.get("risk_flags", state.risk_flags)

                state.messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(res_dict, ensure_ascii=False),
                })
            continue

        # 无工具调用，最终回复
        content = msg.content or ""
        state.messages.append({"role": "assistant", "content": content})

        result = {
            "assistant_message": content,
            "tool_calls": [{"tool_name": e["tool_name"], "arguments": e["arguments"]} for e in executed],
            "state": state.model_dump(),
            "run_id": tracer.run_id,
        }
        tracer.finish(result)
        return result

    # 兜底
    result = {
        "assistant_message": "已达到最大对话轮次。",
        "tool_calls": [{"tool_name": e["tool_name"], "arguments": e["arguments"]} for e in executed],
        "state": state.model_dump(),
        "run_id": tracer.run_id,
    }
    tracer.finish(result)
    return result
