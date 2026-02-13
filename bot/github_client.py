"""
GitHub API 客户端

封装所有与 GitHub 交互的操作：
- 创建 Issue
- 上传文件（图片）到仓库
- 更新 Issue 标签
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from .config import Config

logger = logging.getLogger(__name__)


class GitHubAPIError(Exception):
    """GitHub API 错误"""

    pass


class GitHubClient:
    """GitHub API 客户端，使用 REST API v3"""

    def __init__(self, config: Config):
        self.config = config
        self.session = httpx.Client()
        self.session.headers.update(
            {
                "Authorization": f"token {config.github_token}",
                "Accept": "application/vnd.github.v3+json",
            }
        )
        self.base_url = "https://api.github.com"
        self.repo_url = f"{self.base_url}/repos/{config.github_owner}/{config.github_repo}"

    def __del__(self):
        """清理 session"""
        if hasattr(self, 'session'):
            self.session.close()

    def _handle_response(self, resp: httpx.Response, action: str) -> None:
        """处理 API 响应，记录错误并转换为自定义异常"""
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(f"{action} 失败: {e}")
            try:
                error_data = resp.json()
                message = error_data.get("message", str(e))
            except ValueError:
                message = str(e)
            raise GitHubAPIError(f"{action} 失败: {message}") from e

    def create_issue(
        self,
        title: str,
        body: str,
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        创建一个新 Issue。

        Args:
            title: Issue 标题
            body: Issue 正文（Markdown）
            labels: 标签列表（默认会自动加上 journal_label）

        Returns:
            GitHub API 返回的 Issue 对象

        Raises:
            GitHubAPIError: API 调用失败时抛出
        """
        url = f"{self.repo_url}/issues"

        # 确保包含 journal 标签
        all_labels = labels or []
        if self.config.journal_label not in all_labels:
            all_labels.append(self.config.journal_label)

        payload = {
            "title": title,
            "body": body,
            "labels": all_labels,
        }

        logger.info(f"创建 Issue: {title}")
        resp = self.session.post(url, json=payload)
        self._handle_response(resp, "创建 Issue")

        issue = resp.json()
        logger.info(f"Issue 创建成功: #{issue['number']} - {issue['html_url']}")
        return issue

    def upload_file(
        self,
        file_path: str,
        content: bytes,
        commit_message: str | None = None,
    ) -> dict[str, Any]:
        """
        上传文件到仓库（通过 Contents API）。

        Args:
            file_path: 文件在仓库中的路径（如 content/images/2024/01/15/photo.jpg）
            content: 文件二进制内容
            commit_message: 提交消息（可选）

        Returns:
            GitHub API 返回的响应

        Raises:
            GitHubAPIError: API 调用失败时抛出
        """
        url = f"{self.repo_url}/contents/{file_path}"

        # 先检查文件是否存在（获取 sha）
        get_resp = self.session.get(url, params={"ref": self.config.branch})
        existing_sha = None
        if get_resp.status_code == 200:
            existing_sha = get_resp.json().get("sha")
            logger.warning(f"文件已存在: {file_path}，将覆盖")

        payload = {
            "message": commit_message or f"Upload {file_path}",
            "content": base64.b64encode(content).decode("utf-8"),
            "branch": self.config.branch,
        }

        if existing_sha:
            payload["sha"] = existing_sha

        logger.info(f"上传文件: {file_path} ({len(content)} bytes)")
        resp = self.session.put(url, json=payload)
        self._handle_response(resp, "上传文件")

        result = resp.json()
        logger.info(f"文件上传成功: {result['content']['html_url']}")
        return result

    def add_labels_to_issue(self, issue_number: int, labels: list[str]) -> None:
        """给 Issue 添加标签。"""
        url = f"{self.repo_url}/issues/{issue_number}/labels"

        logger.info(f"为 Issue #{issue_number} 添加标签: {labels}")
        resp = self.session.post(url, json={"labels": labels})
        self._handle_response(resp, "添加标签")

    def close_issue(self, issue_number: int) -> None:
        """关闭 Issue。"""
        url = f"{self.repo_url}/issues/{issue_number}"

        logger.info(f"关闭 Issue #{issue_number}")
        resp = self.session.patch(url, json={"state": "closed"})
        self._handle_response(resp, "关闭 Issue")

    def update_issue_body(self, issue_number: int, new_body: str) -> None:
        """更新 Issue 正文。"""
        url = f"{self.repo_url}/issues/{issue_number}"

        logger.info(f"更新 Issue #{issue_number} 正文")
        resp = self.session.patch(url, json={"body": new_body})
        self._handle_response(resp, "更新 Issue")
