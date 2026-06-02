"""工具接口层 —— 复刻 Claude Code 的 Tool 抽象"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict


class ToolResult(BaseModel):
    """工具执行结果（复刻 Claude Code 的 ToolResult<Output>）"""
    model_config = ConfigDict(extra="allow")

    success: bool
    data: dict | None = None
    error: str | None = None


class BaseTool(ABC):
    """工具基类（复刻 Claude Code 的 Tool<Input, Output>）

    每个工具自包含：
    - name / description: 机器契约（传给 LLM 的 function schema）
    - input_schema: Pydantic 模型 = Zod Schema 的 Python 等价物
    - call(): 执行逻辑
    - is_read_only: 行为声明（评测时区分只读/写入）
    """

    name: str = ""
    description: str = ""
    input_schema: type[BaseModel] | None = None

    @abstractmethod
    def call(self, **kwargs: Any) -> ToolResult:
        """执行工具，子类必须实现"""
        raise NotImplementedError

    def validate(self, args: dict[str, Any]) -> BaseModel:
        """参数校验（复刻 inputSchema.safeParse）"""
        if self.input_schema is None:
            raise ValueError(f"Tool {self.name} has no input_schema")
        return self.input_schema(**args)

    @property
    def is_read_only(self) -> bool:
        """是否只读工具（复刻 isReadOnly）"""
        return False

    def to_openai_schema(self) -> dict[str, Any]:
        """生成 OpenAI function calling 所需的 schema（复刻 toolToAPISchema）

        清理 Pydantic 生成的多余字段（title/description/$defs），
        只保留 OpenAI 原生 function schema 所需的结构。
        """
        if self.input_schema is None:
            raise ValueError(f"Tool {self.name} has no input_schema")
        raw_schema = self.input_schema.model_json_schema()
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": _clean_openai_schema(raw_schema),
            },
        }


def _clean_openai_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """清理 Pydantic JSON Schema，生成 OpenAI 兼容的 function parameters schema。

    OpenAI function calling 只接受：
    - type: "object"
    - properties: {...}
    - required: [...]
    - enum, items, type 等标准 JSON Schema 字段

    移除：title, description（顶层）, $defs 等 Pydantic 特有字段。
    """
    cleaned: dict[str, Any] = {}
    # OpenAI function schema 不需要: title, description(顶层), $defs, default
    allowed_top = {"type", "properties", "required", "enum", "items", "anyOf", "oneOf", "allOf"}
    for key, value in schema.items():
        if key not in allowed_top:
            continue
        if key == "properties" and isinstance(value, dict):
            cleaned["properties"] = {
                k: _clean_openai_schema(v) if isinstance(v, dict) else v
                for k, v in value.items()
            }
        elif key == "items" and isinstance(value, dict):
            cleaned["items"] = _clean_openai_schema(value)
        elif key in ("anyOf", "oneOf", "allOf") and isinstance(value, list):
            cleaned[key] = [
                _clean_openai_schema(v) if isinstance(v, dict) else v
                for v in value
            ]
        else:
            cleaned[key] = value

    # 确保 type 为 object（仅在顶层 object 且没有 anyOf/oneOf/allOf 时）
    if "type" not in cleaned and not any(k in cleaned for k in ("anyOf", "oneOf", "allOf")):
        cleaned["type"] = "object"
    return cleaned

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name}>"
