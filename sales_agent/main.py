"""Sales Agent Harness —— CLI + FastAPI 双模式入口

复刻 Claude Code 的 CLI 简洁风格，同时提供 HTTP API。
API Key 安全原则：
- 只从请求/参数中读取，不存储到任何持久化介质
- 不记录到日志、轨迹、错误信息
- 用完即弃（每轮请求独立）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

# 支持直接运行 main.py 时的相对导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from uvicorn import run as uvicorn_run

from sales_agent.agent.core import agent_loop
from sales_agent.agent.prompt import build_system_prompt, split_prompt_layers
from sales_agent.config import (
    clear_api_key,
    get_api_key,
    get_saved_api_key_preview,
    set_api_key,
)
from sales_agent.eval.runner import run_all, run_and_compare_prompts, list_eval_logs
from sales_agent.eval.test_cases import EvalCase
from sales_agent.prompts.registry import list_versions
from sales_agent.tools.registry import get_tools


# ═══════════════════════════════════════════════════════════
# Pydantic 请求/响应模型
# ═══════════════════════════════════════════════════════════

class ChatRequest(BaseModel):
    """输入格式 —— 严格遵循笔试要求"""
    lead_id: str = Field(description="线索唯一标识")
    api_key: str = Field(description="API Key（ak_...）")
    conversation: list[dict] = Field(description="对话历史")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "lead_id": "L001",
                "api_key": "ak_xxxxxxxx",
                "conversation": [
                    {"role": "user", "content": "我们是 300 人制造业公司..."},
                ],
            }
        }
    )


class ChatResponse(BaseModel):
    """输出格式 —— 严格遵循笔试要求"""
    assistant_message: str
    tool_calls: list[dict]
    state: dict


# ═══════════════════════════════════════════════════════════
# FastAPI 应用
# ═══════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期（复刻 Claude Code 的 bootstrap）"""
    print("[START] Sales Agent Harness")
    yield
    print("[STOP] Sales Agent Harness")


app = FastAPI(
    title="Sales Agent Harness",
    description="面向 B2B 销售场景的 AI Agent（笔试实现）",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS：允许前端通过 file:// 或任意 origin 访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/chat")
async def chat_endpoint(req: ChatRequest) -> StreamingResponse:
    """对话接口 —— SSE 流式输出，接收 lead_id + api_key + conversation"""
    # 安全：校验 API Key 格式（不记录内容）
    if not req.api_key or not req.api_key.startswith("ak_"):
        raise HTTPException(status_code=400, detail="无效的 API Key，必须以 ak_ 开头")

    # 在线程池中执行同步的 agent_loop，避免阻塞事件循环
    result = await asyncio.to_thread(
        agent_loop,
        lead_id=req.lead_id,
        conversation=req.conversation,
        api_key=req.api_key,
    )

    # 安全：确保响应中不包含 api_key
    result.pop("api_key", None)
    run_id = result.get("run_id")

    async def event_generator():
        assistant_message = result.get("assistant_message", "")
        # 逐字发送打字机效果
        for char in assistant_message:
            yield f"data: {json.dumps({'type': 'token', 'content': char}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.012)
        # 发送完成事件（附带 tool_calls、state、run_id）
        yield f"data: {json.dumps({'type': 'done', 'tool_calls': result.get('tool_calls', []), 'state': result.get('state', {}), 'run_id': run_id}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/health")
async def health() -> dict[str, str]:
    """健康检查"""
    return {"status": "ok"}


@app.get("/prompts")
async def get_prompts(version: str = "v2") -> dict[str, Any]:
    """获取当前分层 Prompt（用于测试面板的 A/B 对比）"""
    tools = get_tools()
    full_prompt = build_system_prompt(
        tools=tools,
        qualification_level="unknown",
        missing_info=[],
        next_action="",
        risk_flags=[],
        version=version,
    )
    layers = split_prompt_layers(full_prompt)
    return {
        "layers": layers,
        "full_prompt": full_prompt,
        "version": version,
    }


@app.get("/prompts/versions")
async def get_prompt_versions() -> dict[str, Any]:
    """获取所有可用的 prompt 版本"""
    from sales_agent.prompts.registry import list_versions, get_version_info
    versions = list_versions()
    return {
        "versions": [get_version_info(v) for v in versions],
        "current_default": "v2",
    }


class ABTestRequest(BaseModel):
    """A/B 测试请求 —— 用自定义 System Prompt 重新运行"""
    lead_id: str = Field(description="线索唯一标识")
    api_key: str = Field(description="API Key（ak_...）")
    conversation: list[dict] = Field(description="对话历史")
    custom_system_prompt: str = Field(description="自定义 System Prompt（B 版本）")


@app.post("/chat/ab")
async def chat_ab_endpoint(req: ABTestRequest) -> StreamingResponse:
    """A/B 测试接口 —— 用自定义 System Prompt 运行，SSE 流式输出"""
    if not req.api_key or not req.api_key.startswith("ak_"):
        raise HTTPException(status_code=400, detail="无效的 API Key，必须以 ak_ 开头")

    result = await asyncio.to_thread(
        agent_loop,
        lead_id=req.lead_id,
        conversation=req.conversation,
        api_key=req.api_key,
        custom_system_prompt=req.custom_system_prompt,
    )
    result.pop("api_key", None)
    run_id = result.get("run_id")

    async def event_generator():
        assistant_message = result.get("assistant_message", "")
        for char in assistant_message:
            yield f"data: {json.dumps({'type': 'token', 'content': char}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.012)
        yield f"data: {json.dumps({'type': 'done', 'tool_calls': result.get('tool_calls', []), 'state': result.get('state', {}), 'run_id': run_id}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class EvalRequest(BaseModel):
    """评测请求"""
    api_key: str = Field(description="API Key（ak_...）")
    case_filter: str | None = Field(default=None, description="可选，按 case_id 前缀过滤")
    prompt_version: str = Field(default="v2", description="Prompt 版本")
    cases: list[dict] | None = Field(default=None, description="可选，自定义评测用例列表")


class EvalCompareRequest(BaseModel):
    """评测对比请求"""
    api_key: str = Field(description="API Key（ak_...）")
    versions: list[str] = Field(default=["v1", "v2"], description="要对比的 Prompt 版本列表")
    case_filter: str | None = Field(default=None, description="可选，按 case_id 前缀过滤")


@app.post("/eval")
async def eval_endpoint(req: EvalRequest) -> dict[str, Any]:
    """运行评测集，返回评测结果"""
    if not req.api_key or not req.api_key.startswith("ak_"):
        raise HTTPException(status_code=400, detail="无效的 API Key，必须以 ak_ 开头")
    cases = None
    if req.cases:
        cases = []
        for c in req.cases:
            c_copy = dict(c)
            c_copy.pop("user_simulator", None)
            cases.append(EvalCase(**c_copy))
    run = run_all(
        api_key=req.api_key,
        case_filter=req.case_filter,
        prompt_version=req.prompt_version,
        cases=cases,
    )
    return run.to_dict()


@app.post("/eval/compare")
async def eval_compare_endpoint(req: EvalCompareRequest) -> dict[str, Any]:
    """对比多个 Prompt 版本的评测结果"""
    if not req.api_key or not req.api_key.startswith("ak_"):
        raise HTTPException(status_code=400, detail="无效的 API Key，必须以 ak_ 开头")
    cases = None
    if req.case_filter:
        from sales_agent.eval.test_cases import ALL_CASES
        cases = [c for c in ALL_CASES if c.case_id.startswith(req.case_filter)]
    return run_and_compare_prompts(
        api_key=req.api_key,
        versions=req.versions,
        cases=cases,
    )


@app.get("/eval/logs")
async def eval_logs_endpoint() -> list[dict[str, Any]]:
    """获取所有评测日志列表"""
    return list_eval_logs()


@app.get("/trace/{run_id}")
async def get_trace(run_id: str) -> dict[str, Any]:
    """获取指定 run_id 的轨迹（trajectory）"""
    import glob
    for path in glob.glob("trajectories/trajectory_*.json"):
        if run_id in path:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    raise HTTPException(status_code=404, detail=f"未找到 run_id={run_id} 的轨迹")


# ═══════════════════════════════════════════════════════════
# CLI 模式
# ═══════════════════════════════════════════════════════════

def run_cli(input_path: str | None, api_key: str | None, prompt_version: str = "v2") -> None:
    """命令行模式：读取 JSON 文件或 stdin，输出结果到 stdout"""
    # 读取输入
    if input_path:
        with open(input_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    else:
        payload = json.load(sys.stdin)

    lead_id = payload.get("lead_id", "L001")
    conversation = payload.get("conversation", [])

    # API Key 优先级：参数 > 环境变量 > 输入 JSON
    key = api_key or os.getenv("OPENAI_API_KEY") or payload.get("api_key")
    if not key:
        print("错误：需要提供 API Key（--api-key 参数）", file=sys.stderr)
        sys.exit(1)

    result = agent_loop(
        lead_id=lead_id,
        conversation=conversation,
        api_key=key,
        prompt_version=prompt_version,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="Sales Agent Harness")
    parser.add_argument("--input", "-i", help="输入 JSON 文件路径（默认从 stdin 读取）")
    parser.add_argument("--api-key", "-k", help="API Key")
    parser.add_argument("--serve", "-s", action="store_true", help="启动 HTTP 服务（默认端口 8000）")
    parser.add_argument("--port", "-p", type=int, default=8000, help="HTTP 服务端口")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP 服务绑定的主机地址")
    parser.add_argument("--eval", action="store_true", help="运行评测集（需要 --api-key）")
    parser.add_argument("--eval-filter", default=None, help="评测用例过滤前缀")
    parser.add_argument("--eval-file", default=None, help="从 JSON 文件导入自定义评测用例")
    parser.add_argument("--eval-compare", action="store_true", help="对比多个 Prompt 版本的评测结果")
    parser.add_argument("--eval-compare-versions", default="v1,v2", help="要对比的版本，逗号分隔（默认: v1,v2）")
    parser.add_argument("--prompt-version", default="v2", help=f"Prompt 版本（可用: {', '.join(list_versions())}）")
    parser.add_argument("--set-api-key", metavar="KEY", help="保存 API Key 到本地配置（~/.sales_agent/config.json）")
    parser.add_argument("--clear-api-key", action="store_true", help="清除已保存的 API Key")
    parser.add_argument("--show-config", action="store_true", help="显示当前保存的配置")

    args = parser.parse_args()

    if args.set_api_key:
        set_api_key(args.set_api_key)
        print(f"[Config] API Key 已保存: {get_saved_api_key_preview()}")
        print(f"[Config] 配置文件路径: {Path.home() / '.sales_agent' / 'config.json'}")
        sys.exit(0)

    if args.clear_api_key:
        clear_api_key()
        print("[Config] API Key 已清除")
        sys.exit(0)

    if args.show_config:
        preview = get_saved_api_key_preview()
        print(f"[Config] 已保存 API Key: {preview or '无'}")
        print(f"[Config] 配置文件路径: {Path.home() / '.sales_agent' / 'config.json'}")
        sys.exit(0)

    # 自动读取已保存的 API Key（优先级：命令行参数 > 环境变量 > 本地配置 > 输入文件）
    resolved_api_key = args.api_key or os.getenv("OPENAI_API_KEY") or get_api_key()

    if args.serve:
        uvicorn_run(app, host=args.host, port=args.port)
    elif args.eval:
        if not resolved_api_key:
            print("错误：--eval 需要提供 API Key。请使用 --set-api-key 保存，或设置 OPENAI_API_KEY 环境变量。", file=sys.stderr)
            sys.exit(1)
        # 从文件导入自定义用例
        cases = None
        if args.eval_file:
            with open(args.eval_file, "r", encoding="utf-8") as f:
                file_data = json.load(f)
            cases = []
            for item in file_data.get("cases", []):
                item.pop("user_simulator", None)
                cases.append(EvalCase(**item))
            print(f"[Eval] 从文件导入 {len(cases)} 个自定义用例")
        if args.eval_compare:
            versions = [v.strip() for v in args.eval_compare_versions.split(",")]
            comparison = run_and_compare_prompts(
                api_key=resolved_api_key,
                versions=versions,
                cases=cases,
            )
            print(json.dumps(comparison, ensure_ascii=False, indent=2))
        else:
            run = run_all(
                api_key=resolved_api_key,
                case_filter=args.eval_filter,
                prompt_version=args.prompt_version,
                cases=cases,
            )
            print(json.dumps(run.summary(), ensure_ascii=False, indent=2))
    else:
        run_cli(args.input, resolved_api_key, prompt_version=args.prompt_version)


if __name__ == "__main__":
    main()
