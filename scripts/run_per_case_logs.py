#!/usr/bin/env python3
"""为每个 case 生成对比 log（v1 vs v2）

用法：
    python scripts/run_per_case_logs.py

环境变量：
    AGENT_BASE_URL      API base URL
    AGENT_MODEL         模型名称
    AGENT_MAX_TURNS     最大轮次
    EVAL_LOG_DIR        日志目录（默认 eval_logs）
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sales_agent.config import get_api_key
from sales_agent.eval.runner import run_case
from sales_agent.eval.test_cases import ALL_CASES


def run_both_versions(case, api_key: str) -> dict[str, Any]:
    """为一个 case 跑 v1 和 v2，返回对比结果"""
    print(f"  → {case.case_id}: {case.name}")

    # v1
    print(f"    [v1]", end=" ", flush=True)
    try:
        r1 = run_case(case, api_key, prompt_version="v1")
        s1 = "PASS" if r1.score >= 1.0 else "FAIL"
        print(f"[{s1}] ({r1.duration_ms:.0f}ms)")
    except Exception as e:
        r1 = None
        print(f"[ERROR] {e}")

    # v2
    print(f"    [v2]", end=" ", flush=True)
    try:
        r2 = run_case(case, api_key, prompt_version="v2")
        s2 = "PASS" if r2.score >= 1.0 else "FAIL"
        print(f"[{s2}] ({r2.duration_ms:.0f}ms)")
    except Exception as e:
        r2 = None
        print(f"[ERROR] {e}")

    def _result_to_dict(r):
        if r is None:
            return {"error": "运行失败"}
        return {
            "score": r.score,
            "details": r.details,
            "duration_ms": round(r.duration_ms, 2),
            "trajectory": r.trajectory.to_dict(),
            "final_message": r.raw_output.get("assistant_message", "")[:500],
            "final_tool_calls": r.raw_output.get("tool_calls", []),
            "final_state": r.raw_output.get("state", {}),
        }

    return {
        "case_id": case.case_id,
        "name": case.name,
        "category": case.category,
        "prompt_v1": _result_to_dict(r1),
        "prompt_v2": _result_to_dict(r2),
    }


def main() -> None:
    api_key = os.getenv("OPENAI_API_KEY") or get_api_key()
    if not api_key:
        print("错误：未找到 API Key")
        sys.exit(1)

    log_dir = Path(os.getenv("EVAL_LOG_DIR", "eval_logs"))
    log_dir.mkdir(parents=True, exist_ok=True)

    total = len(ALL_CASES)
    print(f"[Eval] 开始为 {total} 个 case 生成对比 log (v1 vs v2)...")

    for case in ALL_CASES:
        comparison = run_both_versions(case, api_key)

        # 保存单个 case 的对比 log
        filename = log_dir / f"case_{case.case_id}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(comparison, f, ensure_ascii=False, indent=2)
        print(f"    已保存: {filename}")
        print()

    print(f"[Eval] 全部完成，共生成 {total} 个对比 log")
    print(f"[Eval] 日志目录: {log_dir}")


if __name__ == "__main__":
    main()
