"""
SQLite 存储层

简单的日记存储实现，支持未来扩展但不复杂。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class Journal:
    """日记聚合根"""
    id: int
    user_id: int
    date: str  # YYYY-MM-DD
    status: str  # collecting, merged
    github_issue_url: Optional[str]  # 合并后的 GitHub Issue URL
    created_at: datetime


@dataclass
class Entry:
    """日记条目"""
    id: int
    journal_id: int
    source_type: str  # telegram, future: readwise, douban, etc.
    message_id: Optional[int]
    content: str
    images: list[str]  # ["file_id1", "file_id2"]
    tags: list[str]
    created_at: datetime


class Storage:
    """简单的 SQLite 存储"""
    
    def __init__(self, db_path: str = "data/munin.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self) -> None:
        """初始化数据库表"""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS journals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    date TEXT NOT NULL,
                    status TEXT DEFAULT 'collecting',
                    github_issue_url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, date)
                );
                
                CREATE TABLE IF NOT EXISTS entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    journal_id INTEGER NOT NULL,
                    source_type TEXT DEFAULT 'telegram',
                    message_id INTEGER,
                    content TEXT,
                    images JSON DEFAULT '[]',
                    tags JSON DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (journal_id) REFERENCES journals(id)
                );
                
                CREATE INDEX IF NOT EXISTS idx_journals_user_date 
                    ON journals(user_id, date);
                CREATE INDEX IF NOT EXISTS idx_entries_journal 
                    ON entries(journal_id);
            """)
            
            # 迁移：添加 github_issue_url 字段（如果不存在）
            cursor = conn.execute("PRAGMA table_info(journals)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'github_issue_url' not in columns:
                conn.execute("ALTER TABLE journals ADD COLUMN github_issue_url TEXT")
                conn.commit()
            
            # 用户配置表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_configs (
                    user_id INTEGER PRIMARY KEY,
                    show_entry_time INTEGER DEFAULT 1,
                    entry_time_format TEXT DEFAULT '%H:%M'
                )
            """)
            conn.commit()
    
    def _get_row_value(self, row, key: str, default=None):
        """安全地获取行值（处理旧数据库没有该字段的情况）"""
        try:
            return row[key]
        except (KeyError, IndexError):
            return default
    
    def get_or_create_journal(self, user_id: int, date: str) -> Journal:
        """获取或创建日记"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            # 尝试获取现有日记
            row = conn.execute(
                "SELECT * FROM journals WHERE user_id = ? AND date = ?",
                (user_id, date)
            ).fetchone()
            
            if row:
                return Journal(
                    id=row["id"],
                    user_id=row["user_id"],
                    date=row["date"],
                    status=row["status"],
                    github_issue_url=self._get_row_value(row, "github_issue_url"),
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
            
            # 创建新日记
            cursor = conn.execute(
                "INSERT INTO journals (user_id, date) VALUES (?, ?)",
                (user_id, date)
            )
            conn.commit()
            
            return Journal(
                id=cursor.lastrowid,
                user_id=user_id,
                date=date,
                status="collecting",
                github_issue_url=None,
                created_at=datetime.now(),
            )
    
    def add_entry(self, entry: Entry) -> Entry:
        """添加条目"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO entries 
                    (journal_id, source_type, message_id, content, images, tags)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    entry.journal_id,
                    entry.source_type,
                    entry.message_id,
                    entry.content,
                    json.dumps(entry.images),
                    json.dumps(entry.tags),
                )
            )
            conn.commit()
            
            # 从数据库重新读取以获取正确的 created_at
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM entries WHERE id = ?",
                (cursor.lastrowid,)
            ).fetchone()
            
            return Entry(
                id=cursor.lastrowid,
                journal_id=entry.journal_id,
                source_type=entry.source_type,
                message_id=entry.message_id,
                content=entry.content,
                images=entry.images,
                tags=entry.tags,
                created_at=datetime.fromisoformat(row["created_at"]),
            )
    
    def get_entries(self, journal_id: int) -> list[Entry]:
        """获取日记的所有条目"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM entries WHERE journal_id = ? ORDER BY created_at",
                (journal_id,)
            ).fetchall()
            
            return [
                Entry(
                    id=row["id"],
                    journal_id=row["journal_id"],
                    source_type=row["source_type"],
                    message_id=row["message_id"],
                    content=row["content"],
                    images=json.loads(row["images"]),
                    tags=json.loads(row["tags"]),
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
                for row in rows
            ]
    
    def get_journal(self, user_id: int, date: str) -> Optional[Journal]:
        """获取指定日期的日记"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM journals WHERE user_id = ? AND date = ?",
                (user_id, date)
            ).fetchone()
            
            if row:
                return Journal(
                    id=row["id"],
                    user_id=row["user_id"],
                    date=row["date"],
                    status=row["status"],
                    github_issue_url=self._get_row_value(row, "github_issue_url"),
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
            return None
    
    def get_collecting_journals(self, before_date: str) -> list[Journal]:
        """获取指定日期之前所有未合并的日记"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM journals WHERE status = 'collecting' AND date < ?",
                (before_date,)
            ).fetchall()
            
            return [
                Journal(
                    id=row["id"],
                    user_id=row["user_id"],
                    date=row["date"],
                    status=row["status"],
                    github_issue_url=self._get_row_value(row, "github_issue_url"),
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
                for row in rows
            ]
    
    def mark_journal_merged(self, journal_id: int, issue_url: str) -> None:
        """标记日记已合并"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE journals SET status = 'merged', github_issue_url = ? WHERE id = ?",
                (issue_url, journal_id)
            )
            conn.commit()
    
    # ── 用户配置 ─────────────────────────────────────────
    
    def get_user_config(self, user_id: int) -> dict:
        """获取用户配置"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM user_configs WHERE user_id = ?",
                (user_id,)
            ).fetchone()
            
            if row:
                return {
                    "show_entry_time": bool(row["show_entry_time"]),
                    "entry_time_format": row["entry_time_format"],
                }
            # 默认配置
            return {
                "show_entry_time": True,
                "entry_time_format": "%H:%M",
            }
    
    def set_user_config(self, user_id: int, key: str, value) -> None:
        """设置用户配置"""
        with sqlite3.connect(self.db_path) as conn:
            # 先检查是否存在
            row = conn.execute(
                "SELECT 1 FROM user_configs WHERE user_id = ?",
                (user_id,)
            ).fetchone()
            
            if row:
                # 更新
                conn.execute(
                    f"UPDATE user_configs SET {key} = ? WHERE user_id = ?",
                    (value, user_id)
                )
            else:
                # 插入（使用默认值填充其他字段）
                defaults = {"show_entry_time": True, "entry_time_format": "%H:%M"}
                defaults[key] = value
                conn.execute(
                    """INSERT INTO user_configs (user_id, show_entry_time, entry_time_format)
                        VALUES (?, ?, ?)""",
                    (user_id, defaults["show_entry_time"], defaults["entry_time_format"])
                )
            conn.commit()
