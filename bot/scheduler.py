"""
跨天合并调度器

定时检查是否有需要自动合并的日记（跨天时）
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from .diary_service import DiaryService
from .config import Config

logger = logging.getLogger(__name__)


class DiaryScheduler:
    """定时检查跨天合并"""
    
    def __init__(self, diary_service: DiaryService, config: Config, 
                 check_interval_minutes: int = 5):
        self.diary_service = diary_service
        self.config = config
        self.check_interval = timedelta(minutes=check_interval_minutes)
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_check_date: str | None = None
    
    async def start(self) -> None:
        """启动调度器"""
        if self._running:
            logger.warning("调度器已在运行")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"日记调度器已启动，检查间隔: {self.check_interval}")
    
    async def stop(self) -> None:
        """停止调度器"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("日记调度器已停止")
    
    async def _run_loop(self) -> None:
        """主循环"""
        while self._running:
            try:
                await self.check_and_merge()
            except Exception as e:
                logger.exception("检查合并时出错")
            
            try:
                await asyncio.sleep(self.check_interval.total_seconds())
            except asyncio.CancelledError:
                break
    
    async def check_and_merge(self) -> None:
        """
        检查并合并跨天日记
        
        逻辑：
        1. 获取昨天的日期
        2. 检查是否有未合并的日记
        3. 自动合并到 GitHub Issue
        """
        now = datetime.now(tz=self.config.timezone)
        today_str = now.strftime("%Y-%m-%d")
        
        # 如果日期变了（跨天了），立即合并昨天的日记
        if self._last_check_date and self._last_check_date != today_str:
            yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
            logger.info(f"检测到跨天，准备合并 {yesterday} 的日记")
            
            results = self.diary_service.merge_all_pending(yesterday)
            for result in results:
                if result.success:
                    logger.info(f"自动合并成功: {result.issue_url}")
                else:
                    logger.warning(f"自动合并失败: {result.error}")
        
        # 合并所有昨天及之前的待处理日记（兜底）
        results = self.diary_service.merge_all_pending(today_str)
        
        for result in results:
            if result.success:
                logger.info(f"合并成功: {result.issue_url}")
            else:
                logger.warning(f"合并失败: {result.error}")
        
        self._last_check_date = today_str
    
    async def force_merge_today(self, user_id: int) -> str:
        """
        强制合并今天的日记（用于 /end 命令）
        
        Args:
            user_id: Telegram 用户 ID
            
        Returns:
            结果消息
        """
        today_str = datetime.now(tz=self.config.timezone).strftime("%Y-%m-%d")
        result = self.diary_service.merge_journal(user_id, today_str)
        
        if result.success:
            return f"✅ 日记已生成\n\n🔗 {result.issue_url}"
        else:
            return f"❌ {result.error}"
