"""
日记调度器

定时检查跨天合并，自动将昨天的日记合并为 GitHub Issue。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .diary_service import DiaryService

logger = logging.getLogger(__name__)


class DiaryScheduler:
    """定时检查跨天合并"""

    def __init__(
        self,
        diary_service: DiaryService,
        check_interval: int = 60,  # 每 60 秒检查一次
    ):
        self.diary_service = diary_service
        self.check_interval = check_interval
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """启动调度器"""
        if self._running:
            logger.warning("调度器已在运行")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"日记调度器已启动，检查间隔: {self.check_interval}s")

    async def stop(self) -> None:
        """停止调度器"""
        if not self._running:
            return

        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

        logger.info("日记调度器已停止")

    async def _run_loop(self) -> None:
        """主循环"""
        while self._running:
            try:
                await self.check_and_merge()
            except Exception:
                logger.exception("检查合并时出错")

            try:
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break

    async def check_and_merge(self) -> list[str]:
        """
        检查并合并需要处理的日记

        Returns:
            合并的 Issue URL 列表
        """
        merged_urls = []

        # 获取所有需要合并的日记
        pending = self.diary_service.get_pending_merges()

        if pending:
            logger.info(f"发现 {len(pending)} 个待合并日记")

        for user_id, date in pending:
            try:
                issue_url = self.diary_service.merge_journal(user_id, date)
                if issue_url:
                    merged_urls.append(issue_url)
                    logger.info(f"已合并日记: user={user_id}, date={date}, url={issue_url}")
            except Exception:
                logger.exception(f"合并日记失败: user={user_id}, date={date}")

        return merged_urls

    async def force_merge_today(self, user_id: int) -> str | None:
        """
        强制合并今天的日记（用于 /end 命令）

        Args:
            user_id: 用户 ID

        Returns:
            GitHub Issue URL 或 None
        """
        from datetime import datetime

        today = datetime.now(self.diary_service.config.timezone).strftime("%Y-%m-%d")

        logger.info(f"强制合并今天的日记: user={user_id}, date={today}")
        return self.diary_service.merge_journal(user_id, today)
