"""
日记服务

处理日记逻辑：添加消息、合并日记、检查跨天等
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Any

from .storage import Storage, Journal, Entry
from .github_client import GitHubClient
from .config import Config

logger = logging.getLogger(__name__)


@dataclass
class MergeResult:
    """合并结果"""
    success: bool
    issue_url: Optional[str] = None
    error: Optional[str] = None


class DiaryService:
    """处理日记逻辑"""
    
    def __init__(self, storage: Storage, github: GitHubClient, config: Config):
        self.storage = storage
        self.github = github
        self.config = config
    
    def add_message(self, user_id: int, message: Any) -> Entry:
        """
        添加消息到当天的日记
        
        Args:
            user_id: Telegram 用户 ID
            message: Telegram 消息对象
            
        Returns:
            创建的 Entry
        """
        # 获取今天的日期
        now = datetime.now(tz=self.config.timezone)
        today_str = now.strftime("%Y-%m-%d")
        
        # 获取或创建今天的 Journal
        journal = self.storage.get_or_create_journal(user_id, today_str)
        
        # 提取消息内容
        text = message.text or message.caption or ""
        
        # 提取图片 file_ids
        images = []
        if message.photo:
            # 取最大尺寸的图片
            largest = max(message.photo, key=lambda p: p.file_size or 0)
            images = [largest.file_id]
        
        # 提取标签
        tags = self._extract_tags(text)
        
        # 创建 Entry
        entry = Entry(
            id=0,  # 数据库会生成
            journal_id=journal.id,
            source_type="telegram",
            message_id=message.message_id,
            content=text,
            images=images,
            tags=tags,
            created_at=now,
        )
        
        return self.storage.add_entry(entry)
    
    def merge_journal(self, user_id: int, date_str: str) -> MergeResult:
        """
        合并某天的日记到 GitHub Issue
        
        Args:
            user_id: Telegram 用户 ID
            date_str: 日期字符串 YYYY-MM-DD
            
        Returns:
            合并结果
        """
        try:
            # 获取 Journal
            journal = self.storage.get_journal(user_id, date_str)
            if not journal:
                return MergeResult(success=False, error=f"未找到 {date_str} 的日记")
            
            if journal.status == "merged":
                return MergeResult(success=False, error="日记已合并")
            
            # 获取所有条目
            entries = self.storage.get_entries(journal.id)
            if not entries:
                return MergeResult(success=False, error="日记为空")
            
            # 构建 Issue 内容
            title, body = self._build_issue_content(entries, date_str)
            
            # 收集所有标签
            all_tags = set()
            for entry in entries:
                all_tags.update(entry.tags)
            all_tags.add(self.config.journal_label)
            
            # 创建 GitHub Issue
            issue = self.github.create_issue(
                title=title,
                body=body,
                labels=list(all_tags),
            )
            
            # 标记为已合并
            self.storage.mark_journal_merged(journal.id)
            
            logger.info(f"日记 {date_str} 已合并到 Issue: {issue['html_url']}")
            return MergeResult(success=True, issue_url=issue['html_url'])
            
        except Exception as e:
            logger.exception(f"合并日记 {date_str} 失败")
            return MergeResult(success=False, error=str(e))
    
    def should_merge(self, user_id: int, date_str: str) -> bool:
        """
        检查是否应该合并某天的日记（跨天检查）
        
        Args:
            user_id: Telegram 用户 ID
            date_str: 日期字符串 YYYY-MM-DD
            
        Returns:
            是否应该合并
        """
        journal = self.storage.get_journal(user_id, date_str)
        if not journal:
            return False
        
        if journal.status != "collecting":
            return False
        
        # 检查是否有条目
        entries = self.storage.get_entries(journal.id)
        return len(entries) > 0
    
    def merge_all_pending(self, before_date: Optional[str] = None) -> list[MergeResult]:
        """
        合并所有待处理的日记（用于跨天自动合并）
        
        Args:
            before_date: 合并此日期之前的日记，默认为今天
            
        Returns:
            合并结果列表
        """
        if before_date is None:
            before_date = datetime.now(tz=self.config.timezone).strftime("%Y-%m-%d")
        
        pending = self.storage.get_pending_journals(before_date)
        results = []
        
        for journal in pending:
            result = self.merge_journal(journal.user_id, journal.date)
            results.append(result)
        
        return results
    
    def _extract_tags(self, text: str) -> list[str]:
        """从文本中提取 #标签"""
        import re
        pattern = r"#([\w\u4e00-\u9fa5]+)"
        matches = re.findall(pattern, text)
        
        # 去重 + 过滤 journal 标签
        tags = list(dict.fromkeys(matches))
        tags = [t for t in tags if t != self.config.journal_label]
        
        return tags
    
    def _build_issue_content(self, entries: list[Entry], date_str: str) -> tuple[str, str]:
        """
        构建 Issue 标题和正文
        
        Args:
            entries: 日记条目列表
            date_str: 日期字符串 YYYY-MM-DD
            
        Returns:
            (title, body)
        """
        # 标题：yyyyMMdd
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        title = date_obj.strftime("%Y%m%d")
        
        # 正文：按时间顺序合并所有条目
        body_parts = []
        
        for entry in entries:
            entry_parts = []
            
            if entry.content:
                entry_parts.append(entry.content)
            
            # 图片占位符（将在上传后替换）
            for file_id in entry.images:
                entry_parts.append(f"![](image:{file_id})")
            
            if entry_parts:
                body_parts.append("\n".join(entry_parts))
        
        # 用分隔线连接多个条目
        body = "\n\n---\n\n".join(body_parts)
        
        return title, body
    
    def get_today_summary(self, user_id: int) -> dict:
        """获取今天的日记摘要"""
        today_str = datetime.now(tz=self.config.timezone).strftime("%Y-%m-%d")
        journal = self.storage.get_journal(user_id, today_str)
        
        if not journal:
            return {
                "date": today_str,
                "entry_count": 0,
                "status": "none",
            }
        
        entries = self.storage.get_entries(journal.id)
        
        return {
            "date": today_str,
            "entry_count": len(entries),
            "status": journal.status,
        }
