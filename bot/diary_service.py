"""
日记服务层

处理日记业务逻辑：
- 添加消息到日记
- 合并日记生成 GitHub Issue
- 跨天检测
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from .storage import Entry, Journal, Storage

if TYPE_CHECKING:
    from .config import Config
    from .github_client import GitHubClient

logger = logging.getLogger(__name__)


class DiaryService:
    """处理日记逻辑"""

    def __init__(self, storage: Storage, config: Config, github: GitHubClient):
        self.storage = storage
        self.config = config
        self.github = github

    def add_message(
        self,
        user_id: int,
        message_id: int,
        content: str,
        images: list[str],
        tags: list[str],
    ) -> Entry:
        """
        添加消息到当天的日记

        Args:
            user_id: Telegram 用户 ID
            message_id: Telegram 消息 ID
            content: 消息文本内容
            images: 图片 file_id 列表
            tags: 提取的标签

        Returns:
            创建的 Entry
        """
        # 获取今天的日期（根据配置的时区）
        today = datetime.now(self.config.timezone).strftime("%Y-%m-%d")

        # 获取或创建今天的日记
        journal = self.storage.get_or_create_journal(user_id, today)

        # 创建条目（使用配置的时区）
        entry = Entry(
            id=0,  # 会被数据库自动设置
            journal_id=journal.id,
            source_type="telegram",
            message_id=message_id,
            content=content,
            images=images,
            tags=tags,
            created_at=datetime.now(self.config.timezone),
        )

        return self.storage.add_entry(entry)

    def merge_journal(self, user_id: int, date: str) -> str | None:
        """
        合并日记并生成或更新 GitHub Issue

        Args:
            user_id: 用户 ID
            date: 日期 (YYYY-MM-DD)

        Returns:
            GitHub Issue URL 或 None（如果没有条目）
        """
        # 获取日记
        journal = self.storage.get_journal(user_id, date)
        if not journal:
            logger.warning(f"没有找到日记: user={user_id}, date={date}")
            return None

        # 获取所有条目
        entries = self.storage.get_entries(journal.id)
        if not entries:
            logger.warning(f"日记没有条目: journal_id={journal.id}")
            return None

        # 构建 Issue 内容
        title, body = self._build_issue_content(user_id, date, entries)

        # 收集所有标签
        all_tags = set()
        for entry in entries:
            all_tags.update(entry.tags)
        all_tags.add(self.config.journal_label)

        try:
            if journal.status == "merged" and journal.github_issue_url:
                # 更新现有 Issue
                issue_number = self._extract_issue_number(journal.github_issue_url)
                self.github.update_issue_body(issue_number, body)
                logger.info(f"日记已更新: {date} -> {journal.github_issue_url}")
                return journal.github_issue_url
            else:
                # 创建新 Issue
                issue = self.github.create_issue(
                    title=title,
                    body=body,
                    labels=list(all_tags),
                )

                # 标记日记已合并
                self.storage.mark_journal_merged(journal.id, issue["html_url"])

                logger.info(f"日记已合并: {date} -> {issue['html_url']}")
                return issue["html_url"]

        except Exception:
            logger.exception(f"合并日记失败: {date}")
            raise

    def _extract_issue_number(self, issue_url: str) -> int:
        """从 Issue URL 提取 Issue 号"""
        # URL 格式: https://github.com/owner/repo/issues/123
        return int(issue_url.split("/")[-1])

    def should_merge(self, user_id: int, date: str) -> bool:
        """
        检查是否需要合并（跨天检测）

        Args:
            user_id: 用户 ID
            date: 日期 (YYYY-MM-DD)

        Returns:
            是否需要合并
        """
        # 获取今天的日期
        today = datetime.now(self.config.timezone).strftime("%Y-%m-%d")

        # 如果指定日期早于今天，且日记处于 collecting 状态，则需要合并
        if date < today:
            journal = self.storage.get_journal(user_id, date)
            if journal and journal.status == "collecting":
                return True

        return False

    def _build_issue_content(
        self, user_id: int, date: str, entries: list[Entry]
    ) -> tuple[str, str]:
        """
        构建 Issue 标题和正文

        Args:
            user_id: 用户 ID
            date: 日期 (YYYY-MM-DD)
            entries: 日记条目列表

        Returns:
            (title, body)
        """
        # 标题: YYYYMMDD
        title = date.replace("-", "")

        # 正文：合并所有条目
        body_parts = []

        # 获取用户配置
        user_config = self.storage.get_user_config(user_id)

        for entry in entries:
            entry_parts = []

            # 添加时间（如果用户配置启用）
            if user_config.get("show_entry_time", True):
                # 确保时间有时区信息，然后转换为配置时区
                entry_time = entry.created_at
                if entry_time.tzinfo is None:
                    # 如果数据库中的时间没有时区，假定为 UTC
                    from datetime import timezone

                    entry_time = entry_time.replace(tzinfo=timezone.utc)
                entry_time = entry_time.astimezone(self.config.timezone)
                time_format = user_config.get("entry_time_format", "%H:%M")
                time_str = entry_time.strftime(time_format)
                entry_parts.append(f"**{time_str}**")

            # 添加内容
            if entry.content:
                entry_parts.append(entry.content)

            # 添加图片引用 (img_id 已经是完整的 Markdown 图片语法)
            if entry.images:
                for img_ref in entry.images:
                    entry_parts.append(img_ref)

            if entry_parts:
                body_parts.append("\n\n".join(entry_parts))

        # 用换行连接各条目（不使用分割线）
        body = "\n\n".join(body_parts)

        return title, body

    def get_or_create_today(self, user_id: int) -> Journal:
        """获取或创建今天的日记"""
        today = datetime.now(self.config.timezone).strftime("%Y-%m-%d")
        return self.storage.get_or_create_journal(user_id, today)

    def get_pending_merges(self) -> list[tuple[int, str]]:
        """
        获取所有需要合并的日记

        Returns:
            [(user_id, date), ...]
        """
        today = datetime.now(self.config.timezone).strftime("%Y-%m-%d")
        journals = self.storage.get_collecting_journals(before_date=today)

        return [(j.user_id, j.date) for j in journals]
