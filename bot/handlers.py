"""
Telegram 消息处理器

处理用户通过 Telegram 发送的各种消息：
- 文本消息 → 添加到日记
- 图片消息 → 上传到仓库 + 添加到日记
- 标签解析（如 #读书 #思考）
- /end 命令 → 立即合并当天日记
"""

from __future__ import annotations

import io
import logging
import re
from datetime import datetime
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from .config import Config
from .github_client import GitHubClient
from .storage import Storage
from .diary_service import DiaryService

logger = logging.getLogger(__name__)


class MessageHandler:
    """Telegram 消息处理逻辑"""

    def __init__(self, config: Config, github: GitHubClient, 
                 storage: Storage | None = None,
                 diary_service: DiaryService | None = None):
        self.config = config
        self.github = github
        self.storage = storage or Storage()
        self.diary = diary_service or DiaryService(self.storage, github, config)

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理收到的消息（文本 + 图片）"""
        
        # 权限检查
        user_id = update.effective_user.id
        if self.config.allowed_user_ids and user_id not in self.config.allowed_user_ids:
            logger.warning(f"拒绝未授权用户: {user_id}")
            await update.message.reply_text("⚠️ 你没有权限使用这个 bot")
            return

        # 提取消息内容和图片
        text = update.message.text or update.message.caption or ""
        photos = update.message.photo or []
        
        if not text and not photos:
            await update.message.reply_text("🤔 发送点什么吧～")
            return

        try:
            # 先上传图片到 GitHub
            image_refs = []
            if photos:
                image_refs = await self._upload_photos(photos, context)
            
            # 将消息添加到日记
            entry = self.diary.add_message(user_id, update.message)
            
            # 获取今天日记的摘要
            summary = self.diary.get_today_summary(user_id)
            
            # 回复用户
            await update.message.reply_text(
                f"✅ 已记录（第 {summary['entry_count']} 条）\n\n"
                f"💡 发送 /end 结束今天的记录"
            )
            
        except Exception as e:
            logger.exception("处理消息失败")
            await update.message.reply_text(f"❌ 出错了: {e}")

    async def handle_end_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理 /end 命令 - 立即合并当天日记"""
        
        # 权限检查
        user_id = update.effective_user.id
        if self.config.allowed_user_ids and user_id not in self.config.allowed_user_ids:
            await update.message.reply_text("⚠️ 你没有权限使用这个 bot")
            return
        
        try:
            # 先上传任何待处理的图片（如果有）
            # 实际上图片已经在 handle_message 时上传了
            
            # 合并日记
            result = self.diary.merge_journal(
                user_id, 
                datetime.now(tz=self.config.timezone).strftime("%Y-%m-%d")
            )
            
            if result.success:
                await update.message.reply_text(
                    f"✅ 日记已生成\n\n🔗 {result.issue_url}\n\n"
                    f"明天继续记录吧！🌅"
                )
            else:
                await update.message.reply_text(f"❌ {result.error}")
                
        except Exception as e:
            logger.exception("合并日记失败")
            await update.message.reply_text(f"❌ 出错了: {e}")

    def _extract_tags(self, text: str) -> list[str]:
        """从文本中提取 #标签"""
        # 匹配 #标签（支持中文）
        pattern = r"#([\w\u4e00-\u9fa5]+)"
        matches = re.findall(pattern, text)
        
        # 去重 + 过滤掉 journal 标签（它会自动加上）
        tags = list(dict.fromkeys(matches))  # 保持顺序去重
        tags = [t for t in tags if t != self.config.journal_label]
        
        return tags

    async def _upload_photos(
        self,
        photos: list,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> list[str]:
        """
        上传图片到 GitHub 仓库，返回 Markdown 引用列表。

        Args:
            photos: Telegram 的 PhotoSize 列表
            context: Bot context

        Returns:
            Markdown 格式的图片引用列表，如 ["![](content/images/2024/01/15/photo_123.jpg)"]
        """
        refs = []

        # Telegram 的 message.photo 是同一张图的不同尺寸，取最大尺寸即可
        largest = max(photos, key=lambda p: p.file_size or 0)

        # 下载图片
        file = await context.bot.get_file(largest.file_id)
        bio = io.BytesIO()
        await file.download_to_memory(bio)
        content = bio.getvalue()

        # 生成文件路径：YYYY/MM/DD/photo_<timestamp>_<file_id>.jpg
        now = datetime.now(tz=self.config.timezone)
        date_path = now.strftime("%Y/%m/%d")
        filename = f"photo_{now.strftime('%H%M%S')}_{largest.file_id[-8:]}.jpg"

        file_path = f"{self.config.image_dir}/{date_path}/{filename}"

        # 上传
        self.github.upload_file(
            file_path=file_path,
            content=content,
            commit_message=f"Add image {filename}",
        )

        # 使用站点根相对路径，避免文章相对路径导致图片失效
        refs.append(f"![](/{file_path.lstrip('/')})")

        return refs

    def _build_issue_content(
        self,
        text: str,
        image_refs: list[str],
        tags: list[str],
    ) -> tuple[str, str]:
        """
        构建 Issue 的标题和正文。（保留用于兼容性）

        Args:
            text: 用户输入的文本
            image_refs: 图片的 Markdown 引用
            tags: 提取出的标签

        Returns:
            (title, body)
        """
        # 标题规则：固定为 yyyyMMdd
        title = datetime.now(tz=self.config.timezone).strftime("%Y%m%d")
        
        # 正文：原文 + 图片
        body_parts = []
        
        if text:
            body_parts.append(text)
        
        if image_refs:
            body_parts.append("\n---\n")
            body_parts.extend(image_refs)
        
        body = "\n\n".join(body_parts)
        
        return title, body
