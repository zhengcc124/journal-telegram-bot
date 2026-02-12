"""
Bot 端到端流程集成测试

测试完整的用户交互流程，包括各种消息类型的处理。
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from zoneinfo import ZoneInfo

import pytest
import respx
from httpx import Response

from bot.config import Config
from bot.github_client import GitHubClient
from bot.handlers import MessageHandler


@pytest.fixture
def setup_github_api():
    """
    设置完整的 GitHub API Mock。
    
    返回可以用于验证请求的路由对象。
    """
    with respx.mock(assert_all_mocked=False) as mock:
        routes = {}
        
        # 创建 Issue
        routes["create_issue"] = mock.post(
            "https://api.github.com/repos/test_owner/test_repo/issues"
        ).mock(return_value=Response(201, json={
            "number": 42,
            "html_url": "https://github.com/test_owner/test_repo/issues/42",
            "title": "20240212",
            "body": "Test body",
            "labels": [{"name": "journal"}],
        }))
        
        # 上传文件
        routes["upload_file"] = mock.put(
            url__regex=r"https://api\.github\.com/repos/test_owner/test_repo/contents/.*"
        ).mock(return_value=Response(201, json={
            "content": {
                "name": "test.jpg",
                "path": "content/images/2024/02/12/test.jpg",
                "html_url": "https://github.com/test_owner/test_repo/blob/main/content/images/2024/02/12/test.jpg",
            }
        }))
        
        # 检查文件存在
        routes["check_file"] = mock.get(
            url__regex=r"https://api\.github\.com/repos/test_owner/test_repo/contents/.*"
        ).mock(return_value=Response(404))  # 默认文件不存在
        
        # 添加标签
        routes["add_labels"] = mock.post(
            url__regex=r"https://api\.github\.com/repos/test_owner/test_repo/issues/\d+/labels"
        ).mock(return_value=Response(200, json=[]))
        
        routes["mock"] = mock
        yield routes


@pytest.fixture
def make_handler(test_config: Config) -> MessageHandler:
    """创建 MessageHandler 实例。"""
    github_client = GitHubClient(test_config)
    return MessageHandler(test_config, github_client)


@pytest.fixture
def make_update():
    """工厂函数：创建 Update 对象。"""
    def _make(message: MagicMock, user_id: int = 123456789):
        update = MagicMock()
        update.message = message
        update.effective_user = MagicMock(id=user_id)
        return update
    return _make


@pytest.fixture
def make_context(mock_telegram_bot):
    """工厂函数：创建 Context 对象。"""
    def _make():
        context = MagicMock()
        context.bot = mock_telegram_bot
        return context
    return _make


@pytest.mark.integration
class TestSinglePhotoFlow:
    """测试单张图片处理流程。"""
    
    @pytest.mark.asyncio
    async def test_single_photo_with_text(self, setup_github_api, make_handler, make_update, make_context,
                                         test_config, mock_telegram_user) -> None:
        """
        端到端测试：单张图片 + 文字
        
        流程：
        1. 用户发送带 caption 的图片
        2. 提取标签
        3. 上传图片到 GitHub
        4. 创建 Issue
        5. 回复用户成功消息
        """
        handler = make_handler
        context = make_context()
        
        # 创建消息
        message = MagicMock()
        message.message_id = 100
        message.from_user = mock_telegram_user
        message.media_group_id = None  # 不是 Media Group
        message.photo = [
            MagicMock(file_id="photo_small", file_size=500),
            MagicMock(file_id="photo_large", file_size=2000),
        ]
        message.caption = "今天的风景 #旅行 #摄影"
        message.text = None
        message.reply_text = AsyncMock()
        
        # 设置文件下载 mock
        async def mock_download(bio):
            bio.write(b"fake_jpeg_data")
        
        mock_file = AsyncMock()
        mock_file.file_id = "photo_large"
        mock_file.download_to_memory = mock_download
        context.bot.get_file.return_value = mock_file
        
        # 执行处理
        update = make_update(message)
        await handler.handle_message(update, context)
        
        # 验证 GitHub API 调用
        assert setup_github_api["upload_file"].called
        assert setup_github_api["create_issue"].called
        
        # 验证创建 Issue 的请求
        create_issue_call = setup_github_api["create_issue"].calls[0]
        request_body = json.loads(create_issue_call.request.content)
        
        # 验证标签包含提取的标签
        assert "journal" in request_body["labels"]
        assert "旅行" in request_body["labels"]
        assert "摄影" in request_body["labels"]
        
        # 验证回复用户
        assert message.reply_text.called
        reply_text = message.reply_text.call_args[0][0]
        assert "✅ 已记录" in reply_text
        assert "github.com" in reply_text
    
    @pytest.mark.asyncio
    async def test_single_photo_no_caption(self, setup_github_api, make_handler, make_update, 
                                           make_context, mock_telegram_user) -> None:
        """测试只有图片没有 caption。"""
        handler = make_handler
        context = make_context()
        
        message = MagicMock()
        message.message_id = 101
        message.from_user = mock_telegram_user
        message.media_group_id = None
        message.photo = [MagicMock(file_id="photo_only", file_size=2000)]
        message.caption = None
        message.text = None
        message.reply_text = AsyncMock()
        
        # 设置文件下载
        async def mock_download(bio):
            bio.write(b"fake_image")
        
        mock_file = AsyncMock()
        mock_file.download_to_memory = mock_download
        context.bot.get_file.return_value = mock_file
        
        update = make_update(message)
        await handler.handle_message(update, context)
        
        # 验证 API 调用
        assert setup_github_api["upload_file"].called
        assert setup_github_api["create_issue"].called
        
        # 验证 Issue 正文包含图片
        create_issue_call = setup_github_api["create_issue"].calls[0]
        request_body = json.loads(create_issue_call.request.content)
        assert "![](/" in request_body["body"]


@pytest.mark.integration
class TestTextOnlyFlow:
    """测试纯文本消息处理流程。"""
    
    @pytest.mark.asyncio
    async def test_text_only_with_tags(self, setup_github_api, make_handler, make_update,
                                       make_context, mock_telegram_user) -> None:
        """测试纯文本消息带标签。"""
        handler = make_handler
        context = make_context()
        
        message = MagicMock()
        message.message_id = 200
        message.from_user = mock_telegram_user
        message.text = "今天读了一本书，很有收获 #读书 #思考"
        message.caption = None
        message.photo = []
        message.reply_text = AsyncMock()
        
        update = make_update(message)
        await handler.handle_message(update, context)
        
        # 验证创建 Issue
        assert setup_github_api["create_issue"].called
        
        # 验证标签
        create_issue_call = setup_github_api["create_issue"].calls[0]
        request_body = json.loads(create_issue_call.request.content)
        assert "读书" in request_body["labels"]
        assert "思考" in request_body["labels"]
        assert "journal" in request_body["labels"]
        
        # 验证 Issue 正文是原文
        assert "今天读了一本书" in request_body["body"]
    
    @pytest.mark.asyncio
    async def test_text_only_no_tags(self, setup_github_api, make_handler, make_update,
                                    make_context, mock_telegram_user) -> None:
        """测试纯文本消息无标签。"""
        handler = make_handler
        context = make_context()
        
        message = MagicMock()
        message.message_id = 201
        message.from_user = mock_telegram_user
        message.text = "这是一段没有标签的日记"
        message.caption = None
        message.photo = []
        message.reply_text = AsyncMock()
        
        update = make_update(message)
        await handler.handle_message(update, context)
        
        # 验证只有 journal 标签
        create_issue_call = setup_github_api["create_issue"].calls[0]
        request_body = json.loads(create_issue_call.request.content)
        assert request_body["labels"] == ["journal"]


@pytest.mark.integration
class TestAuthorizationFlow:
    """测试权限验证流程。"""
    
    @pytest.mark.asyncio
    async def test_authorized_user(self, setup_github_api, make_handler, make_update,
                                   make_context) -> None:
        """测试授权用户可以正常使用。"""
        handler = make_handler
        context = make_context()
        
        # 白名单中的用户
        authorized_user = MagicMock()
        authorized_user.id = 123456789
        
        message = MagicMock()
        message.message_id = 300
        message.from_user = authorized_user
        message.text = "授权用户的消息"
        message.photo = []
        message.reply_text = AsyncMock()
        
        update = make_update(message, user_id=123456789)
        await handler.handle_message(update, context)
        
        # 应该创建 Issue
        assert setup_github_api["create_issue"].called
    
    @pytest.mark.asyncio
    async def test_unauthorized_user(self, setup_github_api, make_handler, make_update,
                                    make_context) -> None:
        """测试未授权用户被拒绝。"""
        handler = make_handler
        context = make_context()
        
        # 不在白名单中的用户
        unauthorized_user = MagicMock()
        unauthorized_user.id = 999999999
        
        message = MagicMock()
        message.message_id = 301
        message.from_user = unauthorized_user
        message.text = "未授权用户的消息"
        message.photo = []
        message.reply_text = AsyncMock()
        
        update = make_update(message, user_id=999999999)
        await handler.handle_message(update, context)
        
        # 不应该创建 Issue
        assert not setup_github_api["create_issue"].called
        
        # 应该回复权限错误
        assert message.reply_text.called
        reply_text = message.reply_text.call_args[0][0]
        assert "没有权限" in reply_text
    
    @pytest.mark.asyncio
    async def test_empty_whitelist(self, setup_github_api, test_config_no_whitelist,
                                   make_update, make_context) -> None:
        """测试空白名单允许所有用户。"""
        handler = MessageHandler(
            test_config_no_whitelist,
            GitHubClient(test_config_no_whitelist)
        )
        context = make_context()
        
        any_user = MagicMock()
        any_user.id = 555555555
        
        message = MagicMock()
        message.message_id = 302
        message.from_user = any_user
        message.text = "任意用户的消息"
        message.photo = []
        message.reply_text = AsyncMock()
        
        update = make_update(message, user_id=555555555)
        await handler.handle_message(update, context)
        
        # 应该创建 Issue
        assert setup_github_api["create_issue"].called


@pytest.mark.integration
class TestErrorHandlingFlow:
    """测试错误处理流程。"""
    
    @pytest.mark.asyncio
    async def test_github_api_error(self, make_handler, make_update, make_context,
                                    mock_telegram_user) -> None:
        """测试 GitHub API 错误处理。"""
        handler = make_handler
        context = make_context()
        
        # 设置 API 错误
        with respx.mock:
            respx.post(
                "https://api.github.com/repos/test_owner/test_repo/issues"
            ).mock(return_value=Response(500, json={
                "message": "Internal Server Error"
            }))
            
            message = MagicMock()
            message.message_id = 400
            message.from_user = mock_telegram_user
            message.text = "测试消息"
            message.photo = []
            message.reply_text = AsyncMock()
            
            update = make_update(message)
            await handler.handle_message(update, context)
            
            # 应该回复错误信息
            assert message.reply_text.called
            reply_text = message.reply_text.call_args[0][0]
            assert "❌" in reply_text
    
    @pytest.mark.asyncio
    async def test_empty_message(self, setup_github_api, make_handler, make_update,
                                make_context, mock_telegram_user) -> None:
        """测试空消息处理。"""
        handler = make_handler
        context = make_context()
        
        message = MagicMock()
        message.message_id = 401
        message.from_user = mock_telegram_user
        message.text = None
        message.caption = None
        message.photo = []
        message.reply_text = AsyncMock()
        
        update = make_update(message)
        await handler.handle_message(update, context)
        
        # 不应该创建 Issue
        assert not setup_github_api["create_issue"].called
        
        # 应该提示用户
        assert message.reply_text.called
        reply_text = message.reply_text.call_args[0][0]
        assert "发送点什么" in reply_text
    
    @pytest.mark.asyncio
    async def test_network_timeout(self, make_handler, make_update, make_context,
                                  mock_telegram_user) -> None:
        """测试网络超时处理。"""
        # 模拟网络超时
        pass  # 实际实现中需要测试


@pytest.mark.integration
class TestComplexScenarios:
    """测试复杂场景。"""
    
    @pytest.mark.asyncio
    async def test_chinese_tags_extraction(self, setup_github_api, make_handler, make_update,
                                          make_context, mock_telegram_user) -> None:
        """测试中文标签提取。"""
        handler = make_handler
        context = make_context()
        
        message = MagicMock()
        message.message_id = 500
        message.from_user = mock_telegram_user
        message.text = "今天读了一本书 #读书 #人生感悟 #思考"
        message.photo = []
        message.reply_text = AsyncMock()
        
        update = make_update(message)
        await handler.handle_message(update, context)
        
        # 验证标签
        create_issue_call = setup_github_api["create_issue"].calls[0]
        request_body = json.loads(create_issue_call.request.content)
        
        assert "读书" in request_body["labels"]
        assert "人生感悟" in request_body["labels"]
        assert "思考" in request_body["labels"]
    
    @pytest.mark.asyncio
    async def test_mixed_tags_extraction(self, setup_github_api, make_handler, make_update,
                                        make_context, mock_telegram_user) -> None:
        """测试中英文混合标签。"""
        handler = make_handler
        context = make_context()
        
        message = MagicMock()
        message.message_id = 501
        message.from_user = mock_telegram_user
        message.text = "周末计划 #周末 #plan #weekend"
        message.photo = []
        message.reply_text = AsyncMock()
        
        update = make_update(message)
        await handler.handle_message(update, context)
        
        create_issue_call = setup_github_api["create_issue"].calls[0]
        request_body = json.loads(create_issue_call.request.content)
        
        assert "周末" in request_body["labels"]
        assert "plan" in request_body["labels"]
        assert "weekend" in request_body["labels"]
    
    @pytest.mark.asyncio
    async def test_duplicate_tags_removal(self, setup_github_api, make_handler, make_update,
                                         make_context, mock_telegram_user) -> None:
        """测试重复标签去重。"""
        handler = make_handler
        context = make_context()
        
        message = MagicMock()
        message.message_id = 502
        message.from_user = mock_telegram_user
        message.text = "测试 #标签 #标签 #标签"
        message.photo = []
        message.reply_text = AsyncMock()
        
        update = make_update(message)
        await handler.handle_message(update, context)
        
        create_issue_call = setup_github_api["create_issue"].calls[0]
        request_body = json.loads(create_issue_call.request.content)
        
        # 标签应该只出现一次
        labels = request_body["labels"]
        assert labels.count("标签") == 1
    
    @pytest.mark.asyncio
    async def test_journal_label_exclusion(self, setup_github_api, make_handler, make_update,
                                          make_context, mock_telegram_user) -> None:
        """测试 journal 标签被排除。"""
        handler = make_handler
        context = make_context()
        
        message = MagicMock()
        message.message_id = 503
        message.from_user = mock_telegram_user
        message.text = "测试 #journal #其他标签"
        message.photo = []
        message.reply_text = AsyncMock()
        
        update = make_update(message)
        await handler.handle_message(update, context)
        
        create_issue_call = setup_github_api["create_issue"].calls[0]
        request_body = json.loads(create_issue_call.request.content)
        
        # journal 不应该在用户提供的标签中（但会自动添加）
        user_tags = [l for l in request_body["labels"] if l != "journal"]
        assert "journal" not in user_tags
        # 但应该自动添加一次
        assert request_body["labels"].count("journal") == 1


@pytest.mark.integration
@pytest.mark.slow
class TestPerformanceScenarios:
    """测试性能场景。"""
    
    @pytest.mark.asyncio
    async def test_multiple_messages_sequence(self, setup_github_api, make_handler, make_update,
                                             make_context, mock_telegram_user) -> None:
        """测试连续处理多条消息。"""
        handler = make_handler
        context = make_context()
        
        # 连续处理 5 条消息
        for i in range(5):
            message = MagicMock()
            message.message_id = 600 + i
            message.from_user = mock_telegram_user
            message.text = f"消息 {i} #测试"
            message.photo = []
            message.reply_text = AsyncMock()
            
            update = make_update(message)
            await handler.handle_message(update, context)
        
        # 验证创建了 5 个 Issue
        assert setup_github_api["create_issue"].call_count == 5
    
    @pytest.mark.asyncio
    async def test_large_text_message(self, setup_github_api, make_handler, make_update,
                                     make_context, mock_telegram_user) -> None:
        """测试大文本消息。"""
        handler = make_handler
        context = make_context()
        
        # 创建大文本（10KB）
        large_text = "这是一段很长的文本 " * 500 + "#大文本 #测试"
        
        message = MagicMock()
        message.message_id = 700
        message.from_user = mock_telegram_user
        message.text = large_text
        message.photo = []
        message.reply_text = AsyncMock()
        
        update = make_update(message)
        await handler.handle_message(update, context)
        
        # 验证创建 Issue
        assert setup_github_api["create_issue"].called
        
        # 验证正文包含完整内容
        create_issue_call = setup_github_api["create_issue"].calls[0]
        request_body = json.loads(create_issue_call.request.content)
        assert len(request_body["body"]) > 5000
