"""
Telegram 消息处理器

处理用户通过 Telegram 发送的各种消息：
- 文本消息 → 添加到日记
- 图片消息 → 保存到日记 + 上传到仓库
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
from telegram.ext import ContextTypes, CommandHandler, MessageHandler as TelegramMessageHandler, filters

from .config import Config
from .diary_service import DiaryService
from .github_client import GitHubClient
from .scheduler import DiaryScheduler
from .storage import Storage

logger = logging.getLogger(__name__)


class BotHandlers:
    """Telegram Bot 处理器集合"""
    
    def __init__(self, config: Config, github: GitHubClient):
        self.config = config
        self.github = github
        
        # 初始化存储和服务
        self.storage = Storage()
        self.diary_service = DiaryService(self.storage, config, github)
        self.scheduler = DiaryScheduler(self.diary_service)
    
    async def start_scheduler(self):
        """启动调度器（需要在异步上下文中调用）"""
        await self.scheduler.start()
    
    def get_handlers(self):
        """获取所有处理器"""
        return [
            CommandHandler("end", self.handle_end),
            CommandHandler("start", self.handle_start),
            CommandHandler("help", self.handle_help),
            TelegramMessageHandler(filters.TEXT | filters.PHOTO, self.handle_message),
        ]
    
    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理 /start 命令"""
        await update.message.reply_text(
            "📔 Munin 日记机器人\n\n"
            "发送文字或图片来记录日记。\n"
            "使用 #标签 来添加标签。\n\n"
            "命令:\n"
            "/end - 立即合并今天的日记\n"
            "/help - 显示帮助"
        )
    
    async def handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理 /help 命令"""
        await update.message.reply_text(
            "📝 如何使用:\n\n"
            "1. 直接发送文字或图片\n"
            "2. 在消息中使用 #标签 来分类\n"
            "3. 每天的日记会自动合并到 GitHub\n"
            "4. 使用 /end 手动触发合并\n\n"
            "示例:\n"
            "今天读了一本书 #读书 #思考"
        )
    
    async def handle_end(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理 /end 命令 - 立即合并今天的日记"""
        user_id = update.effective_user.id
        
        # 权限检查
        if not self._check_permission(user_id):
            await update.message.reply_text("⚠️ 你没有权限使用这个 bot")
            return
        
        try:
            await update.message.reply_text("🔄 正在合并今天的日记...")
            
            # 先上传所有未上传的图片
            today = self.diary_service.get_or_create_today(user_id)
            entries = self.storage.get_entries(today.id)
            
            if not entries:
                await update.message.reply_text("📭 今天还没有日记内容")
                return
            
            # 强制合并
            issue_url = await self.scheduler.force_merge_today(user_id)
            
            if issue_url:
                await update.message.reply_text(
                    f"✅ 日记已合并\n\n🔗 {issue_url}"
                )
            else:
                await update.message.reply_text("⚠️ 合并失败，请检查日志")
                
        except Exception as e:
            logger.exception("手动合并失败")
            await update.message.reply_text(f"❌ 出错了: {e}")
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理收到的消息（文本 + 图片）"""
        user_id = update.effective_user.id
        
        # 权限检查
        if not self._check_permission(user_id):
            logger.warning(f"拒绝未授权用户: {user_id}")
            await update.message.reply_text("⚠️ 你没有权限使用这个 bot")
            return
        
        # 提取消息内容和图片
        text = update.message.text or update.message.caption or ""
        photos = update.message.photo or []
        message_id = update.message.message_id
        
        if not text and not photos:
            await update.message.reply_text("🤔 发送点什么吧～")
            return
        
        try:
            # 解析标签
            tags = self._extract_tags(text)
            
            # 处理图片上传
            image_refs = []
            if photos:
                image_refs = await self._upload_photos(photos, context)
            
            # 添加到日记
            entry = self.diary_service.add_message(
                user_id=user_id,
                message_id=message_id,
                content=text,
                images=image_refs,
                tags=tags,
            )
            
            # 获取今天的日记状态
            journal = self.diary_service.get_or_create_today(user_id)
            entries = self.storage.get_entries(journal.id)
            
            # 回复用户
            await update.message.reply_text(
                f"✅ 已记录 (#{len(entries)})\n\n"
                f"🏷️ 标签: {', '.join(tags) if tags else '无'}\n"
                f"发送 /end 结束今天的日记"
            )
            
        except Exception as e:
            logger.exception("处理消息失败")
            await update.message.reply_text(f"❌ 出错了: {e}")
    
    def _check_permission(self, user_id: int) -> bool:
        """检查用户权限"""
        if not self.config.allowed_user_ids:
            return True
        return user_id in self.config.allowed_user_ids
    
    def _extract_tags(self, text: str) -> list[str]:
        """从文本中提取 #标签"""
        # 匹配 #标签（支持中文）
        pattern = r"#([\w\u4e00-\u9fa5]+)"
        matches = re.findall(pattern, text)
        
        # 去重 + 过滤掉 journal 标签
        tags = list(dict.fromkeys(matches))
        tags = [t for t in tags if t != self.config.journal_label]
        
        return tags
    
    async def _upload_photos(
        self,
        photos: list,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> list[str]:
        """
        上传图片到 GitHub 仓库，返回图片 URL 列表。
        """
        refs = []
        
        # Telegram 的 message.photo 是同一张图的不同尺寸，取最大尺寸
        largest = max(photos, key=lambda p: p.file_size or 0)
        
        # 下载图片
        file = await context.bot.get_file(largest.file_id)
        bio = io.BytesIO()
        await file.download_to_memory(bio)
        content = bio.getvalue()
        
        # 生成文件路径
        now = datetime.now(tz=self.config.timezone)
        date_path = now.strftime("%Y/%m/%d")
        filename = f"photo_{now.strftime('%H%M%S')}_{largest.file_id[-8:]}.jpg"
        file_path = f"{self.config.image_dir}/{date_path}/{filename}"
        
        # 上传
        result = self.github.upload_file(
            file_path=file_path,
            content=content,
            commit_message=f"Add image {filename}",
        )
        
        # 获取图片 URL
        if result and "content" in result:
            image_url = result["content"].get("html_url", "")
            # 转换为相对路径
            refs.append(f"![](/{file_path.lstrip('/')})")
        
        return refs


# 向后兼容的 MessageHandler 类（单消息处理，不集成日记）
class MessageHandler:
    """Legacy: 单消息处理器（直接创建 Issue）"""
    
    def __init__(self, config: Config, github: GitHubClient):
        self.config = config
        self.github = github
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理收到的消息（向后兼容）"""
        user_id = update.effective_user.id
        if self.config.allowed_user_ids and user_id not in self.config.allowed_user_ids:
            logger.warning(f"拒绝未授权用户: {user_id}")
            await update.message.reply_text("⚠️ 你没有权限使用这个 bot")
            return
        
        text = update.message.text or update.message.caption or ""
        photos = update.message.photo or []
        
        if not text and not photos:
            await update.message.reply_text("🤔 发送点什么吧～")
            return
        
        try:
            tags = self._extract_tags(text)
            image_refs = []
            if photos:
                image_refs = await self._upload_photos(photos, context)
            
            issue_title, issue_body = self._build_issue_content(text, image_refs, tags)
            
            issue = self.github.create_issue(
                title=issue_title,
                body=issue_body,
                labels=tags,
            )
            
            await update.message.reply_text(
                f"✅ 已记录\n\n"
                f"🔗 {issue['html_url']}\n"
                f"🏷️ 标签: {', '.join(tags) if tags else '无'}"
            )
            
        except Exception as e:
            logger.exception("处理消息失败")
            await update.message.reply_text(f"❌ 出错了: {e}")
    
    def _extract_tags(self, text: str) -> list[str]:
        """从文本中提取 #标签"""
        pattern = r"#([\w\u4e00-\u9fa5]+)"
        matches = re.findall(pattern, text)
        tags = list(dict.fromkeys(matches))
        tags = [t for t in tags if t != self.config.journal_label]
        return tags
    
    async def _upload_photos(self, photos: list, context: ContextTypes.DEFAULT_TYPE) -> list[str]:
        """上传图片"""
        refs = []
        largest = max(photos, key=lambda p: p.file_size or 0)
        file = await context.bot.get_file(largest.file_id)
        bio = io.BytesIO()
        await file.download_to_memory(bio)
        content = bio.getvalue()
        
        now = datetime.now(tz=self.config.timezone)
        date_path = now.strftime("%Y/%m/%d")
        filename = f"photo_{now.strftime('%H%M%S')}_{largest.file_id[-8:]}.jpg"
        file_path = f"{self.config.image_dir}/{date_path}/{filename}"
        
        self.github.upload_file(
            file_path=file_path,
            content=content,
            commit_message=f"Add image {filename}",
        )
        
        refs.append(f"![](/{file_path.lstrip('/')})")
        return refs
    
    def _build_issue_content(self, text: str, image_refs: list[str], tags: list[str]) -> tuple[str, str]:
        """构建 Issue 标题和正文"""
        title = datetime.now(tz=self.config.timezone).strftime("%Y%m%d")
        
        body_parts = []
        if text:
            body_parts.append(text)
        if image_refs:
            body_parts.append("\n---\n")
            body_parts.extend(image_refs)
        
        body = "\n\n".join(body_parts)
        return title, body
