"""Evaluation Runner —— 支持交互式多轮对话 + Trajectory 记录 + 自动编号日志

核心改进：
1. 静态模式（兼容旧模式）：一次性传入完整 conversation
2. 交互式模式（新增）：UserSimulator 根据 Agent 每轮回复动态生成用户输入
3. Trajectory 记录：完整记录每轮的 model calls 和 tool executions
4. 基于 Trajectory 的评分：不只检查最终 tool_calls，还检查调用顺序、时机
5. 自动编号日志：每次 eval 保存 log1.json, log2.json...，包含完整交互详情
6. Prompt 版本对比：支持记录不同 prompt_version 的结果
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sales_agent.agent.core import agent_loop
from sales_agent.eval.checkers import check_all
from sales_agent.eval.test_cases import ALL_CASES, EvalCase, Trajectory

# 日志目录：默认使用相对路径 "eval_logs"，可通过环境变量 EVAL_LOG_DIR 覆盖
DEFAULT_LOG_DIR = Path(os.getenv("EVAL_LOG_DIR", "eval_logs"))


class EvalResult:
    """单个用例的评测结果"""

    def __init__(
        self,
        case: EvalCase,
        raw_output: dict,
        trajectory: Trajectory,
        score: float,
        details: list[str],
        duration_ms: float,
    ) -> None:
        self.case = case
        self.raw_output = raw_output
        self.trajectory = trajectory
        self.score = score
        self.details = details
        self.duration_ms = duration_ms

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case.case_id,
            "name": self.case.name,
            "category": self.case.category,
            "score": self.score,
            "details": self.details,
            "duration_ms": round(self.duration_ms, 2),
            "trajectory": self.trajectory.to_dict(),
            "final_tool_calls": [
                {"tool_name": tc.get("tool_name"), "arguments": tc.get("arguments")}
                for tc in self.raw_output.get("tool_calls", [])
            ],
            "final_message": self.raw_output.get("assistant_message", "")[:500],
        }

    def to_log_entry(self) -> dict[str, Any]:
        """生成日志条目 —— 包含完整的每轮交互详情"""
        return {
            "case_id": self.case.case_id,
            "name": self.case.name,
            "category": self.case.category,
            "score": self.score,
            "details": self.details,
            "duration_ms": round(self.duration_ms, 2),
            "turns": self.trajectory.to_dict()["turns"],
            "final_message": self.raw_output.get("assistant_message", ""),
            "final_tool_calls": self.raw_output.get("tool_calls", []),
            "final_state": self.raw_output.get("state", {}),
        }


class EvalRun:
    """一次完整评测运行"""

    def __init__(self, api_key: str, model: str | None = None, prompt_version: str = "v2") -> None:
        self.run_id = str(uuid.uuid4())[:8]
        self.api_key = api_key
        self.model = model or os.getenv("AGENT_MODEL", "LongCat-2.0-Preview")
        self.prompt_version = prompt_version
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.results: list[EvalResult] = []
        self.passed = 0
        self.failed = 0

    def add(self, result: EvalResult) -> None:
        self.results.append(result)
        if result.score >= 1.0:
            self.passed += 1
        else:
            self.failed += 1

    def summary(self) -> dict[str, Any]:
        category_scores: dict[str, list[float]] = {}
        for r in self.results:
            category_scores.setdefault(r.case.category, []).append(r.score)

        return {
            "run_id": self.run_id,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "started_at": self.started_at,
            "total": len(self.results),
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": round(self.passed / len(self.results), 4) if self.results else 0,
            "category_scores": {
                cat: round(sum(scores) / len(scores), 4)
                for cat, scores in category_scores.items()
            },
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "started_at": self.started_at,
            "summary": self.summary(),
            "results": [r.to_dict() for r in self.results],
        }

    def to_log(self) -> dict[str, Any]:
        """生成完整日志 —— 包含每个 case 的逐轮交互"""
        return {
            "log_type": "eval_run",
            "run_id": self.run_id,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "started_at": self.started_at,
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "summary": self.summary(),
            "cases": [r.to_log_entry() for r in self.results],
        }


# ═══════════════════════════════════════════════════════════
# 日志管理
# ═══════════════════════════════════════════════════════════

def _next_log_number(log_dir: Path = DEFAULT_LOG_DIR) -> int:
    """获取下一个日志编号（log1, log2...）"""
    log_dir.mkdir(parents=True, exist_ok=True)
    max_num = 0
    pattern = re.compile(r"log(\d+)\.json")
    for filename in os.listdir(log_dir):
        match = pattern.match(filename)
        if match:
            max_num = max(max_num, int(match.group(1)))
    return max_num + 1


def save_eval_log(
    run: EvalRun,
    log_dir: Path = DEFAULT_LOG_DIR,
) -> str:
    """保存评测日志到自动编号的文件

    Returns:
        保存的文件路径
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    num = _next_log_number(log_dir)
    filename = log_dir / f"log{num}.json"

    log_data = run.to_log()
    log_data["log_id"] = f"log{num}"
    log_data["log_file"] = str(filename)

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)

    print(f"[Eval] 日志已保存: {filename}")
    return str(filename)


def list_eval_logs(log_dir: Path = DEFAULT_LOG_DIR) -> list[dict[str, Any]]:
    """列出所有评测日志的摘要"""
    log_dir.mkdir(parents=True, exist_ok=True)
    logs = []
    pattern = re.compile(r"log(\d+)\.json")
    for filename in sorted(os.listdir(log_dir)):
        match = pattern.match(filename)
        if match:
            path = log_dir / filename
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                logs.append({
                    "log_id": data.get("log_id", filename),
                    "prompt_version": data.get("prompt_version", "unknown"),
                    "model": data.get("model", "unknown"),
                    "started_at": data.get("started_at", ""),
                    "pass_rate": data.get("summary", {}).get("pass_rate", 0),
                    "total": data.get("summary", {}).get("total", 0),
                    "passed": data.get("summary", {}).get("passed", 0),
                    "file": str(path),
                })
            except Exception:
                pass
    return logs


def compare_eval_logs(
    log_ids: list[str] | None = None,
    log_dir: Path = DEFAULT_LOG_DIR,
) -> dict[str, Any]:
    """对比多个评测日志（按 prompt_version 分组）

    Args:
        log_ids: 指定要对比的 log 编号，如 ["log1", "log2"]。None 则对比所有。
    Returns:
        对比报告
    """
    all_logs = list_eval_logs(log_dir)
    if log_ids:
        all_logs = [l for l in all_logs if l["log_id"] in log_ids]

    # 按 prompt_version 分组
    by_version: dict[str, list[dict]] = {}
    for log in all_logs:
        by_version.setdefault(log["prompt_version"], []).append(log)

    # 计算每个版本的平均通过率
    version_stats = {}
    for version, logs in by_version.items():
        pass_rates = [l["pass_rate"] for l in logs]
        version_stats[version] = {
            "runs": len(logs),
            "avg_pass_rate": round(sum(pass_rates) / len(pass_rates), 4) if pass_rates else 0,
            "max_pass_rate": round(max(pass_rates), 4) if pass_rates else 0,
            "min_pass_rate": round(min(pass_rates), 4) if pass_rates else 0,
        }

    return {
        "compared_logs": [l["log_id"] for l in all_logs],
        "version_stats": version_stats,
        "best_version": max(version_stats, key=lambda v: version_stats[v]["avg_pass_rate"]) if version_stats else None,
    }


# ═══════════════════════════════════════════════════════════
# 运行逻辑
# ═══════════════════════════════════════════════════════════

def run_interactive_case(
    case: EvalCase,
    api_key: str,
    prompt_version: str = "v2",
    lead_id: str = "L001",
) -> tuple[dict, Trajectory]:
    """运行交互式评测用例"""
    if case.user_simulator is None:
        raise ValueError(f"交互式评测需要 user_simulator，case {case.case_id} 未提供")

    conversation: list[dict] = []
    trajectory = Trajectory(case_id=case.case_id)

    user_msg = case.user_simulator.respond(
        agent_message="",
        tool_calls=[],
        trajectory=trajectory,
        turn=0,
    )
    if user_msg is None:
        raise ValueError(f"user_simulator 第一轮就返回 None，case {case.case_id}")

    conversation.append({"role": "user", "content": user_msg})

    turn = 0
    while turn < case.max_turns:
        turn += 1

        result = agent_loop(
            lead_id=lead_id,
            conversation=conversation,
            api_key=api_key,
            prompt_version=prompt_version,
        )

        agent_message = result.get("assistant_message", "")
        tool_calls = result.get("tool_calls", [])
        state = result.get("state", {})

        # agent_loop 内部可能多轮执行工具，最终返回的 tool_calls 可能为空。
        # 从 state.tools_called 补全本回合的所有工具调用。
        all_tools_called = state.get("tools_called", [])
        trajectory_tool_calls = tool_calls if tool_calls else [
            {"tool_name": t.get("tool_name"), "arguments": t.get("arguments")}
            for t in all_tools_called
        ]

        trajectory.add_turn(
            turn=turn,
            user_message=user_msg,
            agent_message=agent_message,
            tool_calls=trajectory_tool_calls,
            state=state,
        )

        next_user_msg = case.user_simulator.respond(
            agent_message=agent_message,
            tool_calls=tool_calls,
            trajectory=trajectory,
            turn=turn,
        )

        if next_user_msg is None:
            return result, trajectory

        state_messages = result.get("state", {}).get("messages", [])
        conversation = [dict(m) for m in state_messages]
        conversation.append({"role": "user", "content": next_user_msg})
        user_msg = next_user_msg

    return result, trajectory


def run_static_case(
    case: EvalCase,
    api_key: str,
    prompt_version: str = "v2",
    lead_id: str = "L001",
) -> tuple[dict, Trajectory]:
    """运行静态评测用例（兼容旧模式）"""
    result = agent_loop(
        lead_id=lead_id,
        conversation=case.conversation,
        api_key=api_key,
        prompt_version=prompt_version,
    )

    trajectory = Trajectory(case_id=case.case_id)
    trajectory.add_turn(
        turn=1,
        user_message=case.conversation[-1].get("content", "") if case.conversation else "",
        agent_message=result.get("assistant_message", ""),
        tool_calls=result.get("tool_calls", []),
        state=result.get("state", {}),
    )
    return result, trajectory


def run_case(
    case: EvalCase,
    api_key: str,
    prompt_version: str = "v2",
) -> EvalResult:
    """运行单个评测用例（自动选择交互式或静态模式）"""
    # 重置 mock_db，避免 case 间状态污染
    from sales_agent.mock_db.reset import reset_mock_db

    reset_mock_db()

    start = time.perf_counter()

    if case.user_simulator is not None:
        result, trajectory = run_interactive_case(
            case=case,
            api_key=api_key,
            prompt_version=prompt_version,
        )
    else:
        result, trajectory = run_static_case(
            case=case,
            api_key=api_key,
            prompt_version=prompt_version,
        )

    duration_ms = (time.perf_counter() - start) * 1000

    check = check_all(result, trajectory, case)
    score = check["score"]
    details = check["details"]

    return EvalResult(
        case=case,
        raw_output=result,
        trajectory=trajectory,
        score=score,
        details=details,
        duration_ms=duration_ms,
    )


def run_all(
    api_key: str,
    case_filter: str | None = None,
    prompt_version: str = "v2",
    cases: list[EvalCase] | None = None,
    save_log: bool = True,
) -> EvalRun:
    """运行全部评测用例

    Args:
        api_key: 用于调用模型的 API Key
        case_filter: 可选，按 case_id 前缀过滤
        prompt_version: prompt 版本，如 "v1", "v2"
        cases: 可选，传入自定义用例列表
        save_log: 是否保存详细日志（默认 True）
    """
    run = EvalRun(api_key=api_key, prompt_version=prompt_version)
    if cases is None:
        cases = ALL_CASES
    if case_filter:
        cases = [c for c in cases if c.case_id.startswith(case_filter)]

    print(f"[Eval] 运行 {len(cases)} 个用例 (run_id={run.run_id}, prompt={prompt_version})...")
    for case in cases:
        print(f"  → {case.case_id}: {case.name}", end=" ")
        try:
            res = run_case(case, api_key, prompt_version=prompt_version)
            run.add(res)
            status = "PASS" if res.score >= 1.0 else "FAIL"
            traj_summary = " -> ".join(res.trajectory.tool_names_sequence()) or "无工具"
            print(f"[{status}] ({res.duration_ms:.0f}ms) [{traj_summary}]")
        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            run.add(
                EvalResult(
                    case=case,
                    raw_output={},
                    trajectory=Trajectory(case_id=case.case_id),
                    score=0.0,
                    details=[f"运行时异常: {e}", error_detail],
                    duration_ms=0.0,
                )
            )
            print(f"[ERROR] {e}")

    if save_log:
        save_eval_log(run)

    return run


def run_and_save(
    api_key: str,
    output_dir: str = "eval_runs",
    prompt_version: str = "v2",
) -> str:
    """运行评测并保存结果到 JSON 文件

    Returns:
        保存的文件路径
    """
    run = run_all(api_key, prompt_version=prompt_version, save_log=True)
    os.makedirs(output_dir, exist_ok=True)
    filename = f"{output_dir}/run_{run.run_id}_{prompt_version}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(run.to_dict(), f, ensure_ascii=False, indent=2)
    print(f"[Eval] 结果已保存: {filename}")
    return filename


def run_and_compare_prompts(
    api_key: str,
    versions: list[str],
    cases: list[EvalCase] | None = None,
) -> dict[str, Any]:
    """对比多个 Prompt 版本的评测结果

    依次运行每个版本的评测，保存日志，并生成对比报告。

    Args:
        api_key: API Key
        versions: Prompt 版本列表，如 ["v1", "v2"]
        cases: 可选，自定义用例列表
    Returns:
        对比报告
    """
    print(f"[Eval] 开始对比 {len(versions)} 个 Prompt 版本: {versions}")
    runs: list[EvalRun] = []
    for version in versions:
        print(f"\n{'='*50}")
        print(f"[Eval] 运行 Prompt 版本: {version}")
        print(f"{'='*50}")
        run = run_all(api_key, prompt_version=version, cases=cases, save_log=True)
        runs.append(run)

    # 生成对比报告
    comparison = {
        "compared_versions": versions,
        "runs": [r.summary() for r in runs],
        "best_version": max(runs, key=lambda r: r.summary()["pass_rate"]).prompt_version if runs else None,
    }

    # 按 case 对比
    case_comparison = {}
    for case_id in {r.case.case_id for run in runs for r in run.results}:
        case_comparison[case_id] = {}
        for run in runs:
            result = next((r for r in run.results if r.case.case_id == case_id), None)
            if result:
                case_comparison[case_id][run.prompt_version] = {
                    "score": result.score,
                    "trajectory": result.trajectory.tool_names_sequence(),
                    "duration_ms": result.duration_ms,
                }
    comparison["case_comparison"] = case_comparison

    # 保存对比报告
    report_path = log_dir / f"compare_{'_'.join(versions)}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    log_dir.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(comparison, f, ensure_ascii=False, indent=2)
    print(f"\n[Eval] 对比报告已保存: {report_path}")

    return comparison
