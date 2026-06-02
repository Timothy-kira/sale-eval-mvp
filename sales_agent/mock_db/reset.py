"""Mock DB 重置工具——每次评测前恢复数据库到干净状态"""
from __future__ import annotations

import shutil
from pathlib import Path

DB_DIR = Path(__file__).parent
SNAPSHOT_DIR = DB_DIR / "_snapshots"


def reset_mock_db() -> None:
    """将所有 mock_db JSON 文件恢复到初始快照状态"""
    if not SNAPSHOT_DIR.exists():
        raise RuntimeError(
            f"快照目录不存在: {SNAPSHOT_DIR}，"
            "请先运行快照初始化脚本保存干净状态"
        )

    for snapshot in SNAPSHOT_DIR.iterdir():
        if snapshot.name.startswith("."):
            continue
        dest = DB_DIR / snapshot.name
        shutil.copy2(snapshot, dest)

    # 删除 bookings.json（初始状态不存在）
    bookings = DB_DIR / "bookings.json"
    if bookings.exists():
        bookings.unlink()

    print("[mock_db] 已重置到初始状态")
