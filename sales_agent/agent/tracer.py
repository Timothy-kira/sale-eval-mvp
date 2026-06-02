"""可观测性 —— trace / log / run_id / trajectory"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any


class AgentTracer:
    """Agent 调用轨迹追踪器（复刻 Claude Code 的 telemetry 机制）

    记录每一次 agent_loop 的完整轨迹：
    - run_id: 唯一标识
    - 时间戳: started_at, ended_at
    - 输入: lead_id, conversation
    - 中间步骤: model_calls (每轮 messages + response)
    - 工具调用: tool_executions
    - 输出: assistant_message, tool_calls, state
    - 异常: error (如果有)
    """

    def __init__(self, run_id: str | None = None) -> None:
        self.run_id = run_id or str(uuid.uuid4())[:12]
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.ended_at: str | None = None
        self.steps: list[dict[str, Any]] = []
        self.tool_executions: list[dict[str, Any]] = []
        self.error: str | None = None

    def log_model_call(
        self,
        turn: int,
        messages: list[dict],
        response_raw: str,
        parsed: dict,
    ) -> None:
        """记录一轮模型调用"""
        self.steps.append({
            "type": "model_call",
            "turn": turn,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "messages_count": len(messages),
            "response_preview": response_raw[:500],
            "parsed_tool_calls": [
                {"tool_name": tc.get("tool_name"), "arguments": tc.get("arguments")}
                for tc in parsed.get("tool_calls", [])
            ],
        })

    def log_tool_execution(
        self,
        turn: int,
        tool_name: str,
        arguments: dict,
        result: dict,
        duration_ms: float | None = None,
    ) -> None:
        """记录一次工具执行"""
        self.tool_executions.append({
            "type": "tool_execution",
            "turn": turn,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool_name": tool_name,
            "arguments": arguments,
            "result": result,
            "duration_ms": duration_ms,
        })

    def log_error(self, error: str) -> None:
        """记录异常"""
        self.error = error

    def finish(self, result: dict[str, Any]) -> None:
        """标记运行结束"""
        self.ended_at = datetime.now(timezone.utc).isoformat()
        self.result_summary = {
            "assistant_message_preview": result.get("assistant_message", "")[:200],
            "tool_calls_count": len(result.get("tool_calls", [])),
            "state": result.get("state", {}),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "steps": self.steps,
            "tool_executions": self.tool_executions,
            "error": self.error,
            "result_summary": getattr(self, "result_summary", {}),
        }

    def save(self, output_dir: str = "trajectories") -> str:
        """保存轨迹到文件"""
        os.makedirs(output_dir, exist_ok=True)
        filename = os.path.join(
            output_dir,
            f"trajectory_{self.run_id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json",
        )
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        return filename


def get_tracer(run_id: str | None = None) -> AgentTracer:
    """获取一个新的追踪器实例"""
    return AgentTracer(run_id=run_id)
