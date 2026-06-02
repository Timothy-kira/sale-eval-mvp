"""用户配置管理 —— 保存 API Key 等个人设置"""
from __future__ import annotations

import json
import os
from pathlib import Path

_CONFIG_DIR = Path.home() / ".sales_agent"
_CONFIG_FILE = _CONFIG_DIR / "config.json"


def _ensure_dir() -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    """加载用户配置"""
    if _CONFIG_FILE.exists():
        with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(config: dict) -> None:
    """保存用户配置"""
    _ensure_dir()
    with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def get_api_key() -> str | None:
    """获取已保存的 API Key"""
    return load_config().get("api_key")


def set_api_key(key: str) -> None:
    """保存 API Key"""
    config = load_config()
    config["api_key"] = key
    save_config(config)


def clear_api_key() -> None:
    """清除已保存的 API Key"""
    config = load_config()
    config.pop("api_key", None)
    save_config(config)


def get_saved_api_key_preview() -> str | None:
    """返回脱敏显示的 API Key"""
    key = get_api_key()
    if not key:
        return None
    if len(key) <= 8:
        return "***"
    return key[:4] + "***" + key[-4:]
