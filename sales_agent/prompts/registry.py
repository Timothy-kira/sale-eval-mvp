"""Prompt 版本注册表 —— 支持 v1/v2/v3... 切换与对比"""
from __future__ import annotations

import os
from typing import Any

_PROMPTS_DIR = os.path.dirname(os.path.abspath(__file__))


def list_versions() -> list[str]:
    """列出所有可用的 prompt 版本"""
    versions = []
    for f in sorted(os.listdir(_PROMPTS_DIR)):
        if f.endswith(".md"):
            versions.append(f[:-3])
    return versions


def load_prompt(version: str) -> str:
    """加载指定版本的 prompt 模板"""
    path = os.path.join(_PROMPTS_DIR, f"{version}.md")
    if not os.path.exists(path):
        raise ValueError(
            f"Prompt 版本 '{version}' 不存在。可用版本: {list_versions()}"
        )
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def get_version_info(version: str) -> dict[str, Any]:
    """获取版本信息（文件名、大小、内容预览）"""
    path = os.path.join(_PROMPTS_DIR, f"{version}.md")
    if not os.path.exists(path):
        raise ValueError(f"Prompt 版本 '{version}' 不存在")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return {
        "version": version,
        "path": path,
        "size_chars": len(content),
        "lines": content.count("\n") + 1,
        "preview": content[:300] + "..." if len(content) > 300 else content,
    }


def save_new_version(version: str, content: str) -> str:
    """保存新版本 prompt，返回文件路径"""
    if version in list_versions():
        raise ValueError(f"版本 '{version}' 已存在，请使用新名称")
    path = os.path.join(_PROMPTS_DIR, f"{version}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path
