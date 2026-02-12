"""
Telegram Bot 入口

使用 Long Polling 方式运行，适合在本地 Mac mini 上 7x24 运行。
"""

from __future__ import annotations

import logging
from pathlib import Path

from telegram.ext import ApplicationBuilder

from .config import Config
from .github_client import GitHubClient
from .handlers import BotHandlers

# 配置日志
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main(env_path: str | Path | None = None) -> None:
    """主函数"""
    # 加载配置
    config = Config.from_env(env_path=env_path)
    logger.info(f"配置加载完成: {config.github_owner}/{config.github_repo}")
    
    # 初始化 GitHub 客户端
    github_client = GitHubClient(config)
    
    # 初始化处理器（包含日记服务和调度器）
    bot_handlers = BotHandlers(config, github_client)
    
    # 构建 Telegram Bot Application
    app = (
        ApplicationBuilder()
        .token(config.telegram_token)
        .build()
    )
    
    # 注册所有处理器
    for handler in bot_handlers.get_handlers():
        app.add_handler(handler)
    
    # 启动调度器（在异步上下文中）
    import asyncio
    loop = asyncio.get_event_loop()
    loop.run_until_complete(bot_handlers.start_scheduler())
    
    # 启动 Bot（Long Polling）
    logger.info("🚀 Bot 启动中...")
    logger.info("命令: /start, /help, /end")
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
