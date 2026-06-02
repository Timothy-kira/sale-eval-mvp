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

## 已知问题与不足

### 一、核心功能缺陷

1. **E009：信息完整后未主动写 CRM**
   - 问题：用户表达 Demo 意向并告知完整需求后，Agent 只执行 `get_lead_context -> update_state`，**未调用 `write_crm_note`**。
   - 根因：Prompt 中虽规定「收集到完整信息后应主动写 CRM」，但 COT 流程未将其固化为必要步骤，模型仍易遗漏。
   - 修复方向：在 COT 中增加固定 SOP 触发器——当 `missing_info` 为空且用户有 Demo 意向时，必须追加 `write_crm_note`。

2. **E010：Demo 预约顺序错误**
   - 问题：Agent 直接调用 `book_demo`，**缺少前置的 `check_calendar`**，导致可能预约已占用时段。
   - 根因：Prompt 对 Demo 预约流程的顺序约束不够刚性，模型未形成「先查可用时段，再提交预约」的肌肉记忆。
   - 修复方向：在 COT 和规则中明确 SOP：`确认信息 → check_calendar → book_demo`。

### 二、评测体系问题

1. **LLM 评判成本高**
   - 18 个 case × 2 个 prompt 版本 = 36 次主调用；每 case 另需 1 次独立 LLM 评判，总计 36 次评判调用。
   - 完整一轮评测约 15 分钟，迭代效率低。
   - 优化方向：可引入分级评判——先走硬编码 Trajectory/Custom checker，仅当存在争议或语义模糊时才触发 LLM 评判，降低 50% 以上调用量。

2. **缺少稳定性测试**
   - 当前评测为单次运行，未对同一 case 跑多次取平均。LLM 输出存在方差，单次结果可能无法反映 prompt 真实上限。
   - 优化方向：增加 `n=3` 重复运行模式，统计通过率均值与方差，识别 flaky case。

### 三、代码架构不足

1. **MAX_TURNS 兜底消息体验差**
   - 当前达到最大轮次（默认 5 轮）后，Agent 直接硬截断，返回「已达到最大对话轮次」。用户调研显示该提示令人沮丧。
   - 根因：无优雅退出策略（如总结当前进展、给出下一步建议、或主动转人工）。
   - 修复方向：在 `agent_loop()` 的截断逻辑前增加「收尾模式」——生成一个包含当前状态摘要和明确行动建议的结束语，而非机械提示。

2. **安全拦截为硬编码，非通用安全层**
   - E012/E013（禁止查询其他 lead_id）目前通过在 `core.py` 中硬编码字符串匹配实现，响应速度虽快（0ms PASS），但不具备通用性。
   - 根因：安全规则未抽象为可配置、可扩展的中间件/策略层。
   - 修复方向：将安全规则抽离为 `sales_agent/security/` 模块，支持基于正则/语义的多级校验，并允许通过配置文件动态增删规则。
