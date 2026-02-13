"""
测试共享 Fixtures

提供所有测试模块共享的 mock 对象和测试数据。
"""

from __future__ import annotations

import io
import json
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock
from zoneinfo import ZoneInfo

import pytest
import respx
from httpx import Response

from bot.config import Config
from bot.github_client import GitHubClient
from bot.handlers import MessageHandler

# ═══════════════════════════════════════════════════════════
# 路径 Fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture
def fixtures_dir() -> Path:
    """返回 fixtures 目录路径。"""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_messages(fixtures_dir: Path) -> dict:
    """加载样本消息数据。"""
    with open(fixtures_dir / "sample_messages.json", encoding="utf-8") as f:
        return json.load(f)


# ═══════════════════════════════════════════════════════════
# 配置 Fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture
def test_config() -> Config:
    """创建测试配置。"""
    return Config(
        telegram_token="test_telegram_token",
        allowed_user_ids=(123456789, 987654321),
        github_token="test_github_token",
        github_owner="test_owner",
        github_repo="test_repo",
        branch="main",
        article_dir="content/posts",
        image_dir="content/images",
        journal_label="journal",
        published_label="published",
        timezone=ZoneInfo("Asia/Shanghai"),
    )


@pytest.fixture
def test_config_no_whitelist() -> Config:
    """创建无白名单限制的测试配置。"""
    return Config(
        telegram_token="test_telegram_token",
        allowed_user_ids=(),
        github_token="test_github_token",
        github_owner="test_owner",
        github_repo="test_repo",
        branch="main",
        article_dir="content/posts",
        image_dir="content/images",
        journal_label="journal",
        published_label="published",
        timezone=ZoneInfo("Asia/Shanghai"),
    )


# ═══════════════════════════════════════════════════════════
# GitHub Fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture
def mock_github_client(test_config: Config) -> GitHubClient:
    """创建 GitHub 客户端实例。"""
    return GitHubClient(test_config)


@pytest.fixture
def github_api_mock() -> respx.MockRouter:
    """创建 GitHub API 的 mock 路由。"""
    with respx.mock(assert_all_mocked=False) as respx_mock:
        yield respx_mock


@pytest.fixture
def mock_github_responses() -> dict:
    """GitHub API 的标准响应数据。"""
    return {
        "issue_created": {
            "number": 42,
            "html_url": "https://github.com/test_owner/test_repo/issues/42",
            "title": "20240212",
            "body": "测试内容",
            "labels": [{"name": "journal"}],
        },
        "file_uploaded": {
            "content": {
                "name": "test.jpg",
                "path": "content/images/2024/02/12/test.jpg",
                "html_url": "https://github.com/test_owner/test_repo/blob/main/content/images/2024/02/12/test.jpg",
            }
        },
        "file_exists": {
            "sha": "abc123def456",
            "content": {
                "name": "existing.jpg",
                "path": "content/images/2024/02/12/existing.jpg",
            },
        },
    }


# ═══════════════════════════════════════════════════════════
# Telegram Fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture
def mock_telegram_user() -> MagicMock:
    """创建模拟 Telegram 用户。"""
    user = MagicMock()
    user.id = 123456789
    user.username = "test_user"
    user.first_name = "Test"
    user.last_name = "User"
    return user


@pytest.fixture
def mock_telegram_bot() -> AsyncMock:
    """创建模拟 Telegram Bot。"""
    bot = AsyncMock()

    # 模拟 get_file 返回的文件对象
    mock_file = AsyncMock()
    mock_file.file_id = "test_file_id_12345"
    mock_file.file_size = 1024

    async def mock_download_to_memory(bio: io.BytesIO) -> None:
        """模拟下载图片到内存。"""
        bio.write(b"fake_image_data_jpeg_content")

    mock_file.download_to_memory = mock_download_to_memory
    bot.get_file.return_value = mock_file

    return bot


@pytest.fixture
def mock_telegram_context(mock_telegram_bot: AsyncMock) -> MagicMock:
    """创建模拟 Telegram Context。"""
    context = MagicMock()
    context.bot = mock_telegram_bot
    return context


@pytest.fixture
def create_mock_photo():
    """工厂函数：创建模拟 PhotoSize 对象。"""

    def _create(file_id: str, file_size: int = 1024, width: int = 800, height: int = 600):
        photo = MagicMock()
        photo.file_id = file_id
        photo.file_size = file_size
        photo.width = width
        photo.height = height
        return photo

    return _create


@pytest.fixture
def create_mock_message():
    """工厂函数：创建模拟 Message 对象。"""

    def _create(
        message_id: int = 1,
        text: str | None = None,
        caption: str | None = None,
        photo: list | None = None,
        media_group_id: str | None = None,
        from_user: MagicMock | None = None,
    ):
        message = MagicMock()
        message.message_id = message_id
        message.text = text
        message.caption = caption
        message.photo = photo or []
        message.media_group_id = media_group_id
        message.from_user = from_user

        # 模拟 reply_text 方法
        message.reply_text = AsyncMock()

        return message

    return _create


@pytest.fixture
def create_mock_update():
    """工厂函数：创建模拟 Update 对象。"""

    def _create(message: MagicMock | None = None, effective_user: MagicMock | None = None):
        update = MagicMock()
        update.message = message
        update.effective_user = effective_user or message.from_user if message else None
        return update

    return _create


# ═══════════════════════════════════════════════════════════
# Handler Fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture
def message_handler(test_config: Config, mock_github_client: GitHubClient) -> MessageHandler:
    """创建 MessageHandler 实例。"""
    return MessageHandler(test_config, mock_github_client)


# ═══════════════════════════════════════════════════════════
# 测试图片数据
# ═══════════════════════════════════════════════════════════


@pytest.fixture
def sample_image_data() -> bytes:
    """返回模拟图片数据（JPEG 格式）。"""
    # 这是一个最小的有效 JPEG 文件头
    # 实际测试中可以使用内存中的模拟数据
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\x00" * 100


@pytest.fixture
def sample_png_data() -> bytes:
    """返回模拟 PNG 数据。"""
    # PNG 文件头
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
