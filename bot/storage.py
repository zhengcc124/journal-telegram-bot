"""
SQLite 存储层

简单的日记存储，支持未来扩展但不复杂。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, date
from pathlib import Path
from typing import Optional, List


@dataclass
class Journal:
    """日记（按天聚合）"""
    id: int
    user_id: int
    date: str  # YYYY-MM-DD
    status: str  # collecting, merged
    created_at: datetime
    
    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Journal:
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            date=row["date"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )


@dataclass
class Entry:
    """日记条目（单条消息）"""
    id: int
    journal_id: int
    source_type: str  # telegram, 未来可扩展
    message_id: int
    content: str
    images: List[str]  # ["file_id1", "file_id2"]
    tags: List[str]
    created_at: datetime
    
    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Entry:
        return cls(
            id=row["id"],
            journal_id=row["journal_id"],
            source_type=row["source_type"],
            message_id=row["message_id"],
            content=row["content"],
            images=json.loads(row["images"] or "[]"),
            tags=json.loads(row["tags"] or "[]"),
            created_at=datetime.fromisoformat(row["created_at"]),
        )


class Storage:
    """简单的 SQLite 存储"""
    
    def __init__(self, db_path: str | Path = "data/munin.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_db(self) -> None:
        """初始化数据库表"""
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS journals (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    date TEXT NOT NULL,
                    status TEXT DEFAULT 'collecting',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, date)
                );
                
                CREATE TABLE IF NOT EXISTS entries (
                    id INTEGER PRIMARY KEY,
                    journal_id INTEGER,
                    source_type TEXT DEFAULT 'telegram',
                    message_id INTEGER,
                    content TEXT,
                    images JSON,
                    tags JSON,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (journal_id) REFERENCES journals(id)
                );
                
                CREATE INDEX IF NOT EXISTS idx_journals_user_date 
                    ON journals(user_id, date);
                CREATE INDEX IF NOT EXISTS idx_entries_journal 
                    ON entries(journal_id);
            """)
    
    def get_or_create_journal(self, user_id: int, date_str: str) -> Journal:
        """获取或创建某天的日记"""
        with self._get_conn() as conn:
            # 尝试获取
            row = conn.execute(
                "SELECT * FROM journals WHERE user_id = ? AND date = ?",
                (user_id, date_str)
            ).fetchone()
            
            if row:
                return Journal.from_row(row)
            
            # 创建新的
            cursor = conn.execute(
                "INSERT INTO journals (user_id, date, status) VALUES (?, ?, 'collecting')",
                (user_id, date_str)
            )
            conn.commit()
            
            return Journal(
                id=cursor.lastrowid,
                user_id=user_id,
                date=date_str,
                status="collecting",
                created_at=datetime.now(),
            )
    
    def add_entry(self, entry: Entry) -> Entry:
        """添加日记条目"""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO entries 
                    (journal_id, source_type, message_id, content, images, tags, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.journal_id,
                    entry.source_type,
                    entry.message_id,
                    entry.content,
                    json.dumps(entry.images),
                    json.dumps(entry.tags),
                    entry.created_at.isoformat(),
                )
            )
            conn.commit()
            entry.id = cursor.lastrowid
            return entry
    
    def get_entries(self, journal_id: int) -> List[Entry]:
        """获取日记的所有条目"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM entries WHERE journal_id = ? ORDER BY created_at",
                (journal_id,)
            ).fetchall()
            return [Entry.from_row(row) for row in rows]
    
    def mark_journal_merged(self, journal_id: int, status: str = "merged") -> None:
        """标记日记为已合并"""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE journals SET status = ? WHERE id = ?",
                (status, journal_id)
            )
            conn.commit()
    
    def get_pending_journals(self, before_date: str) -> List[Journal]:
        """获取某日期之前的待合并日记"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM journals WHERE status = 'collecting' AND date < ?",
                (before_date,)
            ).fetchall()
            return [Journal.from_row(row) for row in rows]
    
    def get_journal(self, user_id: int, date_str: str) -> Optional[Journal]:
        """获取指定日期的日记"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM journals WHERE user_id = ? AND date = ?",
                (user_id, date_str)
            ).fetchone()
            return Journal.from_row(row) if row else None
