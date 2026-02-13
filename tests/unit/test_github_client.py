"""
GitHubClient 模块单元测试

测试 GitHub API 交互功能。
"""

from __future__ import annotations

import base64
import json
from unittest.mock import Mock

import pytest
import respx
from httpx import Response

from bot.config import Config
from bot.github_client import GitHubAPIError, GitHubClient


@pytest.mark.unit
class TestGitHubClientInitialization:
    """测试 GitHubClient 初始化。"""

    def test_client_initialization(self, test_config: Config) -> None:
        """测试客户端初始化。"""
        client = GitHubClient(test_config)

        assert client.config == test_config
        assert client.base_url == "https://api.github.com"
        assert client.repo_url == "https://api.github.com/repos/test_owner/test_repo"

    def test_client_session_headers(self, test_config: Config) -> None:
        """测试 session 头信息设置。"""
        client = GitHubClient(test_config)

        assert client.session.headers["Authorization"] == "token test_github_token"
        assert client.session.headers["Accept"] == "application/vnd.github.v3+json"


@pytest.mark.unit
class TestCreateIssue:
    """测试创建 Issue 功能。"""

    @respx.mock
    def test_create_issue_success(self, test_config: Config) -> None:
        """测试成功创建 Issue。"""
        client = GitHubClient(test_config)

        # Mock API 响应
        route = respx.post("https://api.github.com/repos/test_owner/test_repo/issues").mock(
            return_value=Response(
                201,
                json={
                    "number": 42,
                    "html_url": "https://github.com/test_owner/test_repo/issues/42",
                    "title": "Test Issue",
                    "body": "Test body",
                    "labels": [{"name": "journal"}],
                },
            )
        )

        issue = client.create_issue(title="Test Issue", body="Test body", labels=["test"])

        assert issue["number"] == 42
        assert issue["html_url"] == "https://github.com/test_owner/test_repo/issues/42"
        assert route.called

        # 验证请求体
        request_body = route.calls[0].request.content
        import json

        body = json.loads(request_body)
        assert body["title"] == "Test Issue"
        assert body["body"] == "Test body"
        assert "journal" in body["labels"]  # 自动添加 journal 标签
        assert "test" in body["labels"]

    @respx.mock
    def test_create_issue_auto_add_journal_label(self, test_config: Config) -> None:
        """测试自动添加 journal 标签。"""
        client = GitHubClient(test_config)

        route = respx.post("https://api.github.com/repos/test_owner/test_repo/issues").mock(
            return_value=Response(
                201,
                json={
                    "number": 1,
                    "html_url": "https://github.com/test_owner/test_repo/issues/1",
                },
            )
        )

        # 不提供 labels，应该自动添加 journal
        client.create_issue(title="Test", body="Body")

        request_body = json.loads(route.calls[0].request.content)
        assert "journal" in request_body["labels"]

    @respx.mock
    def test_create_issue_without_duplicate_journal(self, test_config: Config) -> None:
        """测试避免重复添加 journal 标签。"""
        client = GitHubClient(test_config)

        route = respx.post("https://api.github.com/repos/test_owner/test_repo/issues").mock(
            return_value=Response(
                201,
                json={
                    "number": 1,
                    "html_url": "https://github.com/test_owner/test_repo/issues/1",
                },
            )
        )

        # 手动提供 journal 标签
        client.create_issue(title="Test", body="Body", labels=["journal", "other"])

        request_body = json.loads(route.calls[0].request.content)
        labels = request_body["labels"]
        assert labels.count("journal") == 1  # 不重复

    @respx.mock
    def test_create_issue_api_error(self, test_config: Config) -> None:
        """测试 API 错误处理。"""
        client = GitHubClient(test_config)

        respx.post("https://api.github.com/repos/test_owner/test_repo/issues").mock(
            return_value=Response(
                401,
                json={
                    "message": "Bad credentials",
                },
            )
        )

        with pytest.raises(GitHubAPIError):
            client.create_issue(title="Test", body="Body")


@pytest.mark.unit
class TestUploadFile:
    """测试文件上传功能。"""

    @respx.mock
    def test_upload_new_file(self, test_config: Config) -> None:
        """测试上传新文件。"""
        client = GitHubClient(test_config)

        # Mock GET 检查文件不存在
        get_route = respx.get(
            "https://api.github.com/repos/test_owner/test_repo/contents/content/images/test.jpg",
            params={"ref": "main"},
        ).mock(return_value=Response(404))

        # Mock PUT 上传文件
        put_route = respx.put(
            "https://api.github.com/repos/test_owner/test_repo/contents/content/images/test.jpg"
        ).mock(
            return_value=Response(
                201,
                json={
                    "content": {
                        "name": "test.jpg",
                        "path": "content/images/test.jpg",
                        "html_url": "https://github.com/test_owner/test_repo/blob/main/content/images/test.jpg",
                    }
                },
            )
        )

        content = b"fake_image_content"
        result = client.upload_file(
            file_path="content/images/test.jpg", content=content, commit_message="Upload test image"
        )

        assert result["content"]["name"] == "test.jpg"
        assert get_route.called
        assert put_route.called

        # 验证请求体包含正确的 base64 编码
        request_body = json.loads(put_route.calls[0].request.content)
        expected_content = base64.b64encode(content).decode("utf-8")
        assert request_body["content"] == expected_content
        assert request_body["message"] == "Upload test image"
        assert request_body["branch"] == "main"
        assert "sha" not in request_body  # 新文件没有 sha

    @respx.mock
    def test_upload_overwrite_existing_file(self, test_config: Config) -> None:
        """测试覆盖已有文件。"""
        client = GitHubClient(test_config)

        # Mock GET 返回已有文件
        respx.get(
            "https://api.github.com/repos/test_owner/test_repo/contents/content/images/existing.jpg",
            params={"ref": "main"},
        ).mock(
            return_value=Response(
                200, json={"sha": "abc123def456", "content": {"name": "existing.jpg"}}
            )
        )

        # Mock PUT 更新文件
        put_route = respx.put(
            "https://api.github.com/repos/test_owner/test_repo/contents/content/images/existing.jpg"
        ).mock(
            return_value=Response(
                200,
                json={
                    "content": {
                        "name": "existing.jpg",
                        "path": "content/images/existing.jpg",
                        "html_url": "https://github.com/test_owner/test_repo/blob/main/content/images/existing.jpg",
                    }
                },
            )
        )

        client.upload_file(
            file_path="content/images/existing.jpg",
            content=b"new_content",
        )

        request_body = json.loads(put_route.calls[0].request.content)
        assert request_body["sha"] == "abc123def456"  # 包含 sha 以覆盖

    @respx.mock
    def test_upload_default_commit_message(self, test_config: Config) -> None:
        """测试默认提交消息。"""
        client = GitHubClient(test_config)

        respx.get(
            "https://api.github.com/repos/test_owner/test_repo/contents/content/images/test.jpg"
        ).mock(return_value=Response(404))

        put_route = respx.put(
            "https://api.github.com/repos/test_owner/test_repo/contents/content/images/test.jpg"
        ).mock(
            return_value=Response(
                201,
                json={
                    "content": {
                        "html_url": "https://github.com/test_owner/test_repo/blob/main/content/images/test.jpg"
                    }
                },
            )
        )

        client.upload_file(
            file_path="content/images/test.jpg",
            content=b"content",
            # 不提供 commit_message
        )

        request_body = json.loads(put_route.calls[0].request.content)
        assert "Upload content/images/test.jpg" in request_body["message"]


@pytest.mark.unit
class TestAddLabels:
    """测试添加标签功能。"""

    @respx.mock
    def test_add_labels_to_issue(self, test_config: Config) -> None:
        """测试为 Issue 添加标签。"""
        client = GitHubClient(test_config)

        route = respx.post(
            "https://api.github.com/repos/test_owner/test_repo/issues/42/labels"
        ).mock(return_value=Response(200, json=[{"name": "bug"}, {"name": "feature"}]))

        client.add_labels_to_issue(42, ["bug", "feature"])

        assert route.called
        request_body = json.loads(route.calls[0].request.content)
        assert request_body["labels"] == ["bug", "feature"]


@pytest.mark.unit
class TestCloseIssue:
    """测试关闭 Issue 功能。"""

    @respx.mock
    def test_close_issue(self, test_config: Config) -> None:
        """测试关闭 Issue。"""
        client = GitHubClient(test_config)

        route = respx.patch("https://api.github.com/repos/test_owner/test_repo/issues/42").mock(
            return_value=Response(200, json={"number": 42, "state": "closed"})
        )

        client.close_issue(42)

        assert route.called
        request_body = json.loads(route.calls[0].request.content)
        assert request_body["state"] == "closed"


@pytest.mark.unit
class TestUpdateIssueBody:
    """测试更新 Issue 正文功能。"""

    @respx.mock
    def test_update_issue_body(self, test_config: Config) -> None:
        """测试更新 Issue 正文。"""
        client = GitHubClient(test_config)

        route = respx.patch("https://api.github.com/repos/test_owner/test_repo/issues/42").mock(
            return_value=Response(200, json={"number": 42, "body": "New body content"})
        )

        client.update_issue_body(42, "New body content")

        assert route.called
        request_body = json.loads(route.calls[0].request.content)
        assert request_body["body"] == "New body content"


@pytest.mark.unit
class TestGitHubApiErrors:
    """测试 API 错误处理。"""

    @respx.mock
    def test_rate_limit_error(self, test_config: Config) -> None:
        """测试限流错误。"""
        client = GitHubClient(test_config)

        respx.post("https://api.github.com/repos/test_owner/test_repo/issues").mock(
            return_value=Response(
                403,
                json={
                    "message": "API rate limit exceeded",
                    "documentation_url": "https://docs.github.com/rest/overview/resources-in-the-rest-api#rate-limiting",
                },
            )
        )

        with pytest.raises(Exception) as exc_info:
            client.create_issue(title="Test", body="Body")

        assert "rate limit" in str(exc_info.value).lower() or "403" in str(exc_info.value)

    @respx.mock
    def test_not_found_error(self, test_config: Config) -> None:
        """测试 404 错误。"""
        client = GitHubClient(test_config)

        respx.post("https://api.github.com/repos/test_owner/test_repo/issues").mock(
            return_value=Response(
                404,
                json={
                    "message": "Not Found",
                },
            )
        )

        with pytest.raises(GitHubAPIError):
            client.create_issue(title="Test", body="Body")

    @respx.mock
    def test_server_error(self, test_config: Config) -> None:
        """测试服务器错误。"""
        client = GitHubClient(test_config)

        respx.post("https://api.github.com/repos/test_owner/test_repo/issues").mock(
            return_value=Response(
                500,
                json={
                    "message": "Internal Server Error",
                },
            )
        )

        with pytest.raises(GitHubAPIError):
            client.create_issue(title="Test", body="Body")


@pytest.mark.unit
class TestGitHubClientEdgeCases:
    """测试边界情况。"""

    @respx.mock
    def test_empty_labels_list(self, test_config: Config) -> None:
        """测试空标签列表。"""
        client = GitHubClient(test_config)

        route = respx.post("https://api.github.com/repos/test_owner/test_repo/issues").mock(
            return_value=Response(
                201,
                json={
                    "number": 1,
                    "html_url": "https://github.com/test_owner/test_repo/issues/1",
                    "labels": [{"name": "journal"}],
                },
            )
        )

        client.create_issue(title="Test", body="Body", labels=[])

        request_body = json.loads(route.calls[0].request.content)
        assert request_body["labels"] == ["journal"]  # 只有 journal

    @respx.mock
    def test_unicode_content(self, test_config: Config) -> None:
        """测试 Unicode 内容。"""
        client = GitHubClient(test_config)

        respx.get("https://api.github.com/repos/test_owner/test_repo/contents/test.txt").mock(
            return_value=Response(404)
        )

        put_route = respx.put(
            "https://api.github.com/repos/test_owner/test_repo/contents/test.txt"
        ).mock(
            return_value=Response(
                201,
                json={
                    "content": {
                        "html_url": "https://github.com/test_owner/test_repo/blob/main/test.txt"
                    }
                },
            )
        )

        unicode_content = "中文测试 🎉 émojis".encode()
        client.upload_file(file_path="test.txt", content=unicode_content)

        request_body = json.loads(put_route.calls[0].request.content)
        expected_content = base64.b64encode(unicode_content).decode("utf-8")
        assert request_body["content"] == expected_content

    @respx.mock
    def test_large_file_upload(self, test_config: Config) -> None:
        """测试大文件上传。"""
        client = GitHubClient(test_config)

        respx.get("https://api.github.com/repos/test_owner/test_repo/contents/large.bin").mock(
            return_value=Response(404)
        )

        put_route = respx.put(
            "https://api.github.com/repos/test_owner/test_repo/contents/large.bin"
        ).mock(
            return_value=Response(
                201,
                json={
                    "content": {
                        "html_url": "https://github.com/test_owner/test_repo/blob/main/large.bin"
                    }
                },
            )
        )

        # 10MB 文件
        large_content = b"x" * (10 * 1024 * 1024)
        client.upload_file(file_path="large.bin", content=large_content)

        assert put_route.called
