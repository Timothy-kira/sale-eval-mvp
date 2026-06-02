```
sales_agent/
├── __init__.py
├── main.py                      # CLI + FastAPI 入口
├── config.py                    # 配置管理
├── requirements.txt             # 依赖
├── agent/
│   ├── __init__.py
│   ├── core.py                  # Agent 核心循环（原生 Function Calling）
│   ├── prompt.py                # Prompt 构建
│   ├── state.py                 # 状态管理
│   └── tracer.py                # 轨迹追踪
├── eval/
│   ├── __init__.py
│   ├── runner.py                # 评测运行器
│   ├── checkers.py              # 评分检查器（LLM 独立评判 + Trajectory 硬编码）
│   ├── test_cases.py            # 测试用例加载器
│   └── cases/                   # JSON 测试用例配置
│       ├── static_cases.json
│       └── interactive_cases.json
├── prompts/
│   ├── registry.py              # Prompt 版本注册表
│   ├── v1.md                    # v1 Prompt（基础规则）
│   └── v2.md                    # v2 Prompt（COT + 负面示例）
├── mock_db/                     # Mock 数据库（JSON 文件）
│   ├── calendar_db.json
│   ├── crm_records.json
│   ├── handoffs.json
│   ├── knowledge_base.json
│   ├── leads.json
│   └── reset.py                 # 重置工具（恢复到干净快照）
└── tools/
    ├── __init__.py
    ├── interface.py             # 工具接口（BaseTool、ToolResult）
    ├── registry.py              # 工具注册表
    └── mock/                    # Mock 工具实现
        ├── __init__.py
        ├── calendar.py
        ├── crm.py
        ├── demo_booking.py
        ├── handoff.py
        ├── knowledge_base.py
        ├── lead_context.py
        ├── schemas.py
        └── update_state.py

scripts/
├── run_eval.py                  # 一键测评脚本
└── run_per_case_logs.py         # 生成分 case 对比 log 的脚本

README.md
.gitignore
```

## 评测体系

### 评判方式

- **Message Content**：由独立 LLM（LongCat-2.0）做语义评判，不再硬编码关键词匹配。
  - 每个 case 配有 `rubric`（评分标准），描述期望行为和参考正确做法。
  - LLM 评判语义正确性，不因为措辞差异而误判。
- **Trajectory**：保留硬编码检查，验证工具调用序列、顺序和时机。
- **Custom Checker**：保留硬编码检查，用于 JSON 字段校验、CRM 内容校验等明确规则。

### 评测日志结构

```
eval_logs/
├── case_E001.json               # 单 case 对比 log（v1 vs v2）
├── case_E002.json
├── ...
├── case_E018.json
└── 评测汇总报告.txt             # 中文汇总报告（通过率、失败清单）
```

单个 case log 格式：
```json
{
  "case_id": "E001",
  "name": "询问未知价格时不得编造",
  "category": "policy_compliance",
  "prompt_v1": {
    "score": 1.0,
    "details": ["LLM评判: Agent正确说明需要确认", "Trajectory 检查通过"],
    "duration_ms": 15000,
    "trajectory": { "turns": [...] },
    "final_message": "...",
    "final_tool_calls": [...],
    "final_state": {...}
  },
  "prompt_v2": { ... }
}
```

### 运行评测

> **API Key**：已通过私信/邮箱发送，请勿上传到公开仓库。

```bash
# 环境变量
export OPENAI_API_KEY="your_key"
export AGENT_BASE_URL="https://api.longcat.chat/openai"
export AGENT_MODEL="LongCat-2.0-Preview"
export AGENT_MAX_TURNS="5"

# 分 case 对比评测（v1 vs v2），结果保存在 eval_logs/
python scripts/run_per_case_logs.py
```

### Mock DB 重置

每个 case 运行前自动重置 `sales_agent/mock_db/` 到干净快照状态，避免 case 间状态污染（如 `book_demo` 占用的时段、CRM 追加记录等）。
