"""
Handlers 模块单元测试

测试 Telegram 消息处理逻辑。
"""

from __future__ import annotations

import io
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


@pytest.mark.unit
class TestMessageHandlerInitialization:
    """测试 MessageHandler 初始化。"""
    
    def test_handler_initialization(self, test_config: Config, mock_github_client: GitHubClient) -> None:
        """测试处理器初始化。"""
        handler = MessageHandler(test_config, mock_github_client)
        
        assert handler.config == test_config
        assert handler.github == mock_github_client


@pytest.mark.unit
class TestExtractTags:
    """测试标签提取功能。"""
    
    def test_extract_single_tag(self, test_config: Config, mock_github_client: GitHubClient) -> None:
        """测试提取单个标签。"""
        handler = MessageHandler(test_config, mock_github_client)
        
        tags = handler._extract_tags("这是一段文字 #标签")
        assert tags == ["标签"]
    
    def test_extract_multiple_tags(self, test_config: Config, mock_github_client: GitHubClient) -> None:
        """测试提取多个标签。"""
        handler = MessageHandler(test_config, mock_github_client)
        
        tags = handler._extract_tags("这是一段文字 #标签1 #标签2 #标签3")
        assert tags == ["标签1", "标签2", "标签3"]
    
    def test_extract_chinese_tags(self, test_config: Config, mock_github_client: GitHubClient) -> None:
        """测试提取中文标签。"""
        handler = MessageHandler(test_config, mock_github_client)
        
        tags = handler._extract_tags("今天读了一本书 #读书 #思考")
        assert tags == ["读书", "思考"]
    
    def test_extract_mixed_tags(self, test_config: Config, mock_github_client: GitHubClient) -> None:
        """测试提取中英文混合标签。"""
        handler = MessageHandler(test_config, mock_github_client)
        
        tags = handler._extract_tags("周末计划 #周末 #plan #todo")
        assert tags == ["周末", "plan", "todo"]
    
    def test_extract_no_tags(self, test_config: Config, mock_github_client: GitHubClient) -> None:
        """测试无标签情况。"""
        handler = MessageHandler(test_config, mock_github_client)
        
        tags = handler._extract_tags("这是一段没有标签的文字")
        assert tags == []
    
    def test_extract_empty_text(self, test_config: Config, mock_github_client: GitHubClient) -> None:
        """测试空文本。"""
        handler = MessageHandler(test_config, mock_github_client)
        
        tags = handler._extract_tags("")
        assert tags == []
    
    def test_extract_deduplicate_tags(self, test_config: Config, mock_github_client: GitHubClient) -> None:
        """测试标签去重（保持顺序）。"""
        handler = MessageHandler(test_config, mock_github_client)
        
        tags = handler._extract_tags("#标签1 #标签2 #标签1 #标签3")
        assert tags == ["标签1", "标签2", "标签3"]
    
    def test_exclude_journal_label(self, test_config: Config, mock_github_client: GitHubClient) -> None:
        """测试排除 journal 标签。"""
        handler = MessageHandler(test_config, mock_github_client)
        
        # journal 是配置中的 journal_label
        tags = handler._extract_tags("这是一段文字 #标签1 #journal #标签2")
        assert "journal" not in tags
        assert tags == ["标签1", "标签2"]


@pytest.mark.unit
class TestBuildIssueContent:
    """测试 Issue 内容构建。"""
    
    @patch('bot.handlers.datetime')
    def test_build_issue_title_format(self, mock_datetime, test_config: Config, mock_github_client: GitHubClient) -> None:
        """测试 Issue 标题格式。"""
        mock_now = MagicMock()
        mock_now.strftime.return_value = "20240212"
        mock_datetime.now.return_value = mock_now
        mock_datetime.now.return_value.tzinfo = ZoneInfo("Asia/Shanghai")
        
        handler = MessageHandler(test_config, mock_github_client)
        
        title, body = handler._build_issue_content("文本内容", [], ["标签"])
        
        assert title == "20240212"
    
    def test_build_issue_body_with_text_only(self, test_config: Config, mock_github_client: GitHubClient) -> None:
        """测试只有文本的 Issue 正文。"""
        handler = MessageHandler(test_config, mock_github_client)
        
        title, body = handler._build_issue_content("这是一段文本", [], ["标签"])
        
        assert "这是一段文本" in body
        assert "---" not in body  # 没有图片时不应有分隔线
    
    def test_build_issue_body_with_images_only(self, test_config: Config, mock_github_client: GitHubClient) -> None:
        """测试只有图片的 Issue 正文。"""
        handler = MessageHandler(test_config, mock_github_client)
        
        image_refs = ["![](/content/images/photo1.jpg)", "![](/content/images/photo2.jpg)"]
        title, body = handler._build_issue_content("", image_refs, [])
        
        assert "---" in body
        assert "![](/content/images/photo1.jpg)" in body
        assert "![](/content/images/photo2.jpg)" in body
    
    def test_build_issue_body_with_text_and_images(self, test_config: Config, mock_github_client: GitHubClient) -> None:
        """测试带文本和图片的 Issue 正文。"""
        handler = MessageHandler(test_config, mock_github_client)
        
        image_refs = ["![](/content/images/photo.jpg)"]
        title, body = handler._build_issue_content("这是一段文本", image_refs, ["标签"])
        
        assert "这是一段文本" in body
        assert "---" in body
        assert "![](/content/images/photo.jpg)" in body
    
    def test_build_issue_body_empty(self, test_config: Config, mock_github_client: GitHubClient) -> None:
        """测试空的 Issue 正文。"""
        handler = MessageHandler(test_config, mock_github_client)
        
        title, body = handler._build_issue_content("", [], [])
        
        assert body == ""


@pytest.mark.unit
class TestUploadPhotos:
    """测试图片上传功能。"""
    
    @pytest.mark.asyncio
    async def test_upload_single_photo(self, test_config: Config, mock_github_client: GitHubClient, 
                                       mock_telegram_context, create_mock_photo) -> None:
        """测试上传单张图片。"""
        handler = MessageHandler(test_config, mock_github_client)
        
        # 创建照片列表（模拟 Telegram 返回的多种尺寸）
        photos = [
            create_mock_photo("small_id", 500, 320, 240),
            create_mock_photo("medium_id", 1000, 800, 600),
            create_mock_photo("large_id", 2000, 1280, 960),
        ]
        
        with patch.object(mock_github_client, 'upload_file') as mock_upload:
            mock_upload.return_value = {"content": {"html_url": "https://github.com/test.jpg"}}
            
            refs = await handler._upload_photos(photos, mock_telegram_context)
            
            # 应该只上传最大尺寸的图片
            assert len(refs) == 1
            assert mock_upload.called
            
            # 验证使用了最大尺寸的文件
            call_args = mock_upload.call_args
            assert "large_id" in str(call_args)
    
    @pytest.mark.asyncio
    async def test_upload_photos_file_naming(self, test_config: Config, mock_github_client: GitHubClient,
                                             mock_telegram_context, create_mock_photo) -> None:
        """测试上传文件命名格式。"""
        handler = MessageHandler(test_config, mock_github_client)
        
        photos = [create_mock_photo("test_file_id_12345", 2000)]
        
        with patch.object(mock_github_client, 'upload_file') as mock_upload:
            mock_upload.return_value = {"content": {}}
            
            await handler._upload_photos(photos, mock_telegram_context)
            
            call_args = mock_upload.call_args
            file_path = call_args.kwargs.get('file_path') or call_args[1].get('file_path')
            
            # 路径格式: content/images/YYYY/MM/DD/photo_HHMMSS_<file_id>.jpg
            assert file_path.startswith("content/images/")
            assert "photo_" in file_path
            assert file_path.endswith(".jpg")
    
    @pytest.mark.asyncio
    async def test_upload_photo_markdown_format(self, test_config: Config, mock_github_client: GitHubClient,
                                                mock_telegram_context, create_mock_photo) -> None:
        """测试返回的 Markdown 格式。"""
        handler = MessageHandler(test_config, mock_github_client)
        
        photos = [create_mock_photo("test_id", 2000)]
        
        with patch.object(mock_github_client, 'upload_file') as mock_upload:
            mock_upload.return_value = {"content": {}}
            
            refs = await handler._upload_photos(photos, mock_telegram_context)
            
            # Markdown 格式应该是 ![](/path/to/image.jpg)
            assert len(refs) == 1
            assert refs[0].startswith("![](/")
            assert refs[0].endswith(".jpg)")


@pytest.mark.unit
class TestHandleMessageAuthorization:
    """测试消息处理的权限检查。"""
    
    @pytest.mark.asyncio
    async def test_authorized_user_allowed(self, test_config: Config, mock_github_client: GitHubClient,
                                           create_mock_message, create_mock_update, 
                                           mock_telegram_context, mock_telegram_user) -> None:
        """测试授权用户被允许。"""
        handler = MessageHandler(test_config, mock_github_client)
        
        # 创建消息（白名单中的用户）
        message = create_mock_message(text="测试", from_user=mock_telegram_user)
        update = create_mock_update(message=message, effective_user=mock_telegram_user)
        
        with patch.object(handler.github, 'create_issue') as mock_create:
            mock_create.return_value = {"html_url": "https://github.com/test/issue/1"}
            
            await handler.handle_message(update, mock_telegram_context)
            
            # 应该创建 issue
            assert mock_create.called
    
    @pytest.mark.asyncio
    async def test_unauthorized_user_rejected(self, test_config: Config, mock_github_client: GitHubClient,
                                             create_mock_message, create_mock_update,
                                             mock_telegram_context) -> None:
        """测试未授权用户被拒绝。"""
        handler = MessageHandler(test_config, mock_github_client)
        
        # 创建未授权用户
        unauthorized_user = MagicMock()
        unauthorized_user.id = 999999999
        
        message = create_mock_message(text="测试", from_user=unauthorized_user)
        update = create_mock_update(message=message, effective_user=unauthorized_user)
        
        with patch.object(handler.github, 'create_issue') as mock_create:
            await handler.handle_message(update, mock_telegram_context)
            
            # 不应该创建 issue
            assert not mock_create.called
            # 应该回复权限错误
            assert message.reply_text.called
            reply_text = message.reply_text.call_args[0][0]
            assert "没有权限" in reply_text
    
    @pytest.mark.asyncio
    async def test_empty_whitelist_allows_all(self, test_config_no_whitelist: Config, mock_github_client: GitHubClient,
                                             create_mock_message, create_mock_update,
                                             mock_telegram_context) -> None:
        """测试空白名单允许所有用户。"""
        handler = MessageHandler(test_config_no_whitelist, mock_github_client)
        
        any_user = MagicMock()
        any_user.id = 123456789
        
        message = create_mock_message(text="测试", from_user=any_user)
        update = create_mock_update(message=message, effective_user=any_user)
        
        with patch.object(handler.github, 'create_issue') as mock_create:
            mock_create.return_value = {"html_url": "https://github.com/test/issue/1"}
            
            await handler.handle_message(update, mock_telegram_context)
            
            # 应该创建 issue
            assert mock_create.called


@pytest.mark.unit
class TestHandleMessageValidation:
    """测试消息验证。"""
    
    @pytest.mark.asyncio
    async def test_empty_message(self, test_config: Config, mock_github_client: GitHubClient,
                                create_mock_message, create_mock_update,
                                mock_telegram_context, mock_telegram_user) -> None:
        """测试空消息处理。"""
        handler = MessageHandler(test_config, mock_github_client)
        
        # 既无文本也无图片的消息
        message = create_mock_message(text=None, caption=None, photo=[], from_user=mock_telegram_user)
        update = create_mock_update(message=message, effective_user=mock_telegram_user)
        
        with patch.object(handler.github, 'create_issue') as mock_create:
            await handler.handle_message(update, mock_telegram_context)
            
            # 不应该创建 issue
            assert not mock_create.called
            # 应该提示用户
            assert message.reply_text.called
            reply_text = message.reply_text.call_args[0][0]
            assert "发送点什么" in reply_text


@pytest.mark.unit
class TestHandleMessageEndToEnd:
    """测试端到端消息处理。"""
    
    @pytest.mark.asyncio
    async def test_text_only_message(self, test_config: Config, mock_github_client: GitHubClient,
                                     create_mock_message, create_mock_update,
                                     mock_telegram_context, mock_telegram_user) -> None:
        """测试纯文本消息处理。"""
        handler = MessageHandler(test_config, mock_github_client)
        
        message = create_mock_message(
            text="这是一段测试文字 #标签1 #标签2",
            from_user=mock_telegram_user
        )
        update = create_mock_update(message=message, effective_user=mock_telegram_user)
        
        with patch.object(handler.github, 'create_issue') as mock_create:
            mock_create.return_value = {
                "html_url": "https://github.com/test_owner/test_repo/issues/42",
                "number": 42
            }
            
            await handler.handle_message(update, mock_telegram_context)
            
            assert mock_create.called
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs['labels'] == ["标签1", "标签2"]
    
    @pytest.mark.asyncio
    async def test_single_photo_with_caption(self, test_config: Config, mock_github_client: GitHubClient,
                                            create_mock_message, create_mock_update,
                                            mock_telegram_context, mock_telegram_user,
                                            create_mock_photo) -> None:
        """测试单张图片带 caption。"""
        handler = MessageHandler(test_config, mock_github_client)
        
        photos = [create_mock_photo("photo_id", 2000)]
        message = create_mock_message(
            caption="图片说明 #图片",
            photo=photos,
            from_user=mock_telegram_user
        )
        update = create_mock_update(message=message, effective_user=mock_telegram_user)
        
        with patch.object(handler.github, 'upload_file') as mock_upload, \
             patch.object(handler.github, 'create_issue') as mock_create:
            mock_upload.return_value = {"content": {}}
            mock_create.return_value = {
                "html_url": "https://github.com/test_owner/test_repo/issues/1"
            }
            
            await handler.handle_message(update, mock_telegram_context)
            
            # 应该上传图片并创建 issue
            assert mock_upload.called
            assert mock_create.called
    
    @pytest.mark.asyncio
    async def test_error_handling(self, test_config: Config, mock_github_client: GitHubClient,
                                 create_mock_message, create_mock_update,
                                 mock_telegram_context, mock_telegram_user) -> None:
        """测试错误处理。"""
        handler = MessageHandler(test_config, mock_github_client)
        
        message = create_mock_message(
            text="测试",
            from_user=mock_telegram_user
        )
        update = create_mock_update(message=message, effective_user=mock_telegram_user)
        
        with patch.object(handler.github, 'create_issue') as mock_create:
            mock_create.side_effect = Exception("GitHub API Error")
            
            await handler.handle_message(update, mock_telegram_context)
            
            # 应该回复错误信息
            assert message.reply_text.called
            reply_text = message.reply_text.call_args[0][0]
            assert "❌" in reply_text
            assert "GitHub API Error" in reply_text
