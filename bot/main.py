"""
Telegram Bot 入口

使用 Long Polling 方式运行，适合在本地 Mac mini 上 7x24 运行。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

from .config import Config
from .github_client import GitHubClient
from .handlers import MessageHandler as JournalMessageHandler

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
        "• 所有内容会自动转换为 Markdown 文章"
    )


async def help_command(update, context) -> None:
    """处理 /help 命令"""
    await update.message.reply_text(
        "📖 使用帮助\n\n"
        "1️⃣ 直接发送文字 → 创建日志\n"
        "2️⃣ 发送图片 + 文字说明 → 图文日志\n"
        "3️⃣ 使用 #标签 来分类（如 #工作 #生活）\n\n"
        "所有内容会被转换为 GitHub Issue，然后由 Actions 自动发布为文章。"
    )


def main(env_path: str | Path | None = None) -> None:
    """主函数"""
    if env_path is None:
        env_path = os.getenv("MUNIN_ENV_PATH")

    # 加载配置
    config = Config.from_env(env_path=env_path)
    logger.info(f"配置加载完成: {config.github_owner}/{config.github_repo}")
    
    # 初始化 GitHub 客户端
    github_client = GitHubClient(config)
    
    # 初始化消息处理器
    message_handler = JournalMessageHandler(config, github_client)
    
    # 构建 Telegram Bot Application
    app = (
        ApplicationBuilder()
        .token(config.telegram_token)
        .build()
    )
    
    # 注册命令处理器
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    
    # 注册消息处理器（文本 + 图片）
    app.add_handler(
        MessageHandler(
            filters.TEXT | filters.PHOTO,
            message_handler.handle_message,
        )
    )
    
    # 启动 Bot（Long Polling）
    logger.info("🚀 Bot 启动中...")
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
