"""
Telegram Bot 入口

使用 Long Polling 方式运行，适合在本地 Mac mini 上 7x24 运行。
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

from .config import Config
from .github_client import GitHubClient
from .storage import Storage
from .diary_service import DiaryService
from .handlers import MessageHandler as JournalMessageHandler
from .scheduler import DiaryScheduler

# 配置日志
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def start_command(update, context) -> None:
    """处理 /start 命令"""
    await update.message.reply_text(
        "👋 你好！\n\n"
        "发送文字或图片给我，我会帮你记录到 GitHub 日志仓库。\n\n"
        "💡 小技巧：\n"
        "• 使用 #标签 来分类（如 #读书 #思考）\n"
        "• 发送图片时可以添加文字说明\n"
        "• 发送 /end 结束今天的记录并生成日记\n"
        "• 跨天时会自动合并昨天的记录"
    )


async def help_command(update, context) -> None:
    """处理 /help 命令"""
    await update.message.reply_text(
        "📖 使用帮助\n\n"
        "1️⃣ 直接发送文字 → 添加到当天日记\n"
        "2️⃣ 发送图片 + 文字说明 → 图文日记条目\n"
        "3️⃣ 使用 #标签 来分类（如 #工作 #生活）\n"
        "4️⃣ 发送 /end → 立即合并今天日记\n\n"
        "所有内容会先保存在本地，跨天或发送 /end 后生成 GitHub Issue。"
    )


async def end_command(update, context) -> None:
    """处理 /end 命令 - 由 MessageHandler 处理"""
    # 实际处理在 MessageHandler.handle_end_command
    pass


def main(env_path: str | Path | None = None) -> None:
    """主函数"""
    if env_path is None:
        env_path = os.getenv("MUNIN_ENV_PATH")

    # 加载配置
    config = Config.from_env(env_path=env_path)
    logger.info(f"配置加载完成: {config.github_owner}/{config.github_repo}")
    
    # 初始化组件
    github_client = GitHubClient(config)
    storage = Storage()
    diary_service = DiaryService(storage, github_client, config)
    message_handler = JournalMessageHandler(config, github_client, storage, diary_service)
    scheduler = DiaryScheduler(diary_service, config)
    
    # 构建 Telegram Bot Application
    app = (
        ApplicationBuilder()
        .token(config.telegram_token)
        .build()
    )
    
    # 注册命令处理器
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("end", message_handler.handle_end_command))
    
    # 注册消息处理器（文本 + 图片）
    app.add_handler(
        MessageHandler(
            filters.TEXT | filters.PHOTO,
            message_handler.handle_message,
        )
    )
    
    # 启动调度器（在后台运行）
    async def start_scheduler(app):
        await scheduler.start()
        logger.info("🕐 调度器已启动")
    
    async def stop_scheduler(app):
        await scheduler.stop()
        logger.info("🕐 调度器已停止")
    
    app.post_init = start_scheduler
    app.post_shutdown = stop_scheduler
    
    # 启动 Bot（Long Polling）
    logger.info("🚀 Bot 启动中...")
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
