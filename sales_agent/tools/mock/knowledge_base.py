"""search_knowledge_base —— 搜索产品知识库（Memory 机制）"""
from __future__ import annotations

import json
import os
from typing import Any

from pydantic import BaseModel, Field

from sales_agent.tools.interface import BaseTool, ToolResult


class SearchKnowledgeBaseInput(BaseModel):
    """参数 Schema"""
    query: str = Field(description="搜索关键词，如 '产品功能'、'部署方式'、'定价'")


class SearchKnowledgeBaseTool(BaseTool):
    """搜索产品知识库

    对应笔试题工具：search_knowledge_base(query)
    复刻 Claude Code 的 read/search 机制 —— 从知识库中检索相关信息。
    """

    name: str = "search_knowledge_base"
    description: str = (
        "搜索产品知识库，获取产品功能、定价、部署方式、客户案例、技术支持等信息。"
        "当客户询问产品细节时调用，不得编造信息。"
    )
    input_schema: type[BaseModel] = SearchKnowledgeBaseInput

    def __init__(self) -> None:
        self._db_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "mock_db", "knowledge_base.json"
        )

    @property
    def is_read_only(self) -> bool:
        return True

    def call(self, **kwargs: Any) -> ToolResult:
        try:
            validated = self.validate(kwargs)
            query = validated.query.lower()

            with open(self._db_path, "r", encoding="utf-8") as f:
                db = json.load(f)

            results = []
            for entry in db.get("entries", []):
                score = 0
                # 标题匹配权重最高
                if query in entry.get("title", "").lower():
                    score += 10
                # 分类匹配
                if query in entry.get("category", "").lower():
                    score += 5
                # 内容匹配
                if query in entry.get("content", "").lower():
                    score += 3
                # 分词匹配
                for word in query.split():
                    if len(word) > 1:
                        if word in entry.get("title", "").lower():
                            score += 2
                        if word in entry.get("content", "").lower():
                            score += 1
                if score > 0:
                    results.append({"score": score, "entry": entry})

            results.sort(key=lambda x: x["score"], reverse=True)
            top_results = [r["entry"] for r in results[:3]]

            if not top_results:
                return ToolResult(
                    success=True,
                    data={"results": [], "message": "未找到相关知识，请换用其他关键词或告知客户需要人工确认。"},
                )

            return ToolResult(
                success=True,
                data={
                    "results": top_results,
                    "count": len(top_results),
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=str(e))
