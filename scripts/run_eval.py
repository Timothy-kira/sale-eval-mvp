#!/usr/bin/env python3
"""一键测评脚本

用法：
    python scripts/run_eval.py                    # 跑默认版本 v2
    python scripts/run_eval.py --version v1       # 跑指定版本
    python scripts/run_eval.py --compare v1,v2    # 对比两个版本
    python scripts/run_eval.py --filter E00       # 只跑 E001-E009
    python scripts/run_eval.py --log-dir ./logs   # 指定日志目录

环境变量：
    EVAL_LOG_DIR    日志保存目录（默认: eval_logs）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# 把项目根目录加入路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sales_agent.config import get_api_key
from sales_agent.eval.runner import run_all, run_and_compare_prompts, list_eval_logs
from sales_agent.prompts.registry import list_versions


def main() -> None:
    parser = argparse.ArgumentParser(description="Sales Agent 一键测评")
    parser.add_argument("--version", "-v", default="v2", help="Prompt 版本（默认: v2）")
    parser.add_argument("--compare", "-c", default=None, help="对比多个版本，逗号分隔，如 v1,v2")
    parser.add_argument("--filter", "-f", default=None, help="用例过滤前缀，如 E00 或 E010")
    parser.add_argument("--log-dir", "-l", default=None, help="日志目录（默认: eval_logs）")
    parser.add_argument("--list-logs", action="store_true", help="列出已有日志")
    parser.add_argument("--api-key", "-k", default=None, help="API Key（默认读取已保存的配置）")

    args = parser.parse_args()

    # 设置日志目录环境变量
    if args.log_dir:
        os.environ["EVAL_LOG_DIR"] = args.log_dir

    if args.list_logs:
        logs = list_eval_logs()
        print(f"[Eval] 已有 {len(logs)} 条日志:")
        for log in logs:
            print(f"  {log['log_id']:8} | {log['prompt_version']:6} | pass={log['pass_rate']:.2%} | {log['started_at']}")
        return

    # 获取 API Key
    api_key = args.api_key or os.getenv("OPENAI_API_KEY") or get_api_key()
    if not api_key:
        print("错误：未找到 API Key。请使用以下方式之一提供：")
        print("  1. python -m sales_agent.main --set-api-key ak_xxx")
        print("  2. 设置环境变量 OPENAI_API_KEY")
        print("  3. 使用 --api-key 参数")
        sys.exit(1)

    if args.compare:
        versions = [v.strip() for v in args.compare.split(",")]
        comparison = run_and_compare_prompts(
            api_key=api_key,
            versions=versions,
            cases=None,
        )
        print("\n" + "=" * 60)
        print("对比结果")
        print("=" * 60)
        print(json.dumps(comparison, ensure_ascii=False, indent=2))
    else:
        run = run_all(
            api_key=api_key,
            case_filter=args.filter,
            prompt_version=args.version,
        )
        print("\n" + "=" * 60)
        print("评测摘要")
        print("=" * 60)
        print(json.dumps(run.summary(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
